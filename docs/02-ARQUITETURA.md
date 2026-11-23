# NEXUS — Documento 02 · Arquitetura e modelo de dados

## 1. Visão geral

```
                 ┌──────────────────────────────────────────────────────────┐
                 │                 apps/web  (React + TS + Tailwind)        │
                 │ Dashboard · Ingestão · Conciliação · Intelligence ·      │
                 │ Credit Recovery · Risk · Regras · Audit · Configurações  │
                 └───────────────▲──────────────────────────────────────────┘
                                 │ HTTPS / JSON  (JWT Supabase em produção)
┌────────────────────────────────┴─────────────────────────────────────────────┐
│ services/engine  (Python · FastAPI)                                          │
│                                                                              │
│  api/ ──► security/ (authn, RBAC, planos)  ──► audit/ (hash chain)           │
│   │                                                                          │
│   ├─► ingestion/  upload → validação → normalização → armazenamento          │
│   │      parsers: NF-e XML/ZIP · CSV · XLSX  | validators: CNPJ, chave, CFOP │
│   ├─► analysis/   conciliação · créditos · classificação · anomalias ·       │
│   │               reforma tributária   (motor determinístico)                │
│   ├─► rules/      catálogo versionado com vigência temporal                  │
│   ├─► reports/    exportação CSV/XLSX de findings com evidências             │
│   └─► persistence/ SQLAlchemy  (SQLite local · PostgreSQL/Supabase produção) │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────────┐
│ Supabase / PostgreSQL : schema `nexus`, RLS por tenant, audit append-only,   │
│ Storage (arquivos brutos com retenção), pgmq (filas), PITR (backup)          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Decisões
| Decisão | Motivo |
|---|---|
| Motor de análise em Python, isolado da UI | Ecossistema de dados, testabilidade, escalar workers independentemente |
| Motor **determinístico** antes de IA | Confiabilidade e auditabilidade. IA entra para explicar e consultar evidências, não para gerar números |
| Regras como dados versionados (não `if` espalhado) | Vigência temporal, registro da versão aplicada, revisão jurídica independente do deploy |
| `Decimal` em todo cálculo monetário | Sem erro de ponto flutuante em valores fiscais |
| Arquivo bruto não persistido no MVP | Minimização de dados (LGPD). Em produção: Supabase Storage com criptografia e retenção configurável por contrato |
| Fila abstraída (`JobRunner`) | Local: thread em processo. Produção: pgmq/Redis + workers |

## 2. Multi-tenancy e segurança

- **Isolamento em profundidade**: (1) todo acesso a dados passa por `TenantScopedRepository`,
  que exige `tenant_id` do contexto autenticado; (2) no PostgreSQL, todas as tabelas de negócio têm
  RLS `tenant_id = nexus.current_tenant_id()` com vínculo à tabela `memberships`.
- **RBAC** (`security/rbac.py` e `supabase/migrations/0001`):

| Permissão | admin | tax_director | tax_analyst | auditor | viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| Ver dashboards e findings | ✅ | ✅ | ✅ | ✅ | ✅ |
| Importar dados / rodar análise | ✅ | ✅ | ✅ | | |
| Revisar finding (triagem, submeter) | ✅ | ✅ | ✅ | | |
| **Aprovar/rejeitar** finding | ✅ | ✅ | | | |
| Ver trilha de auditoria | ✅ | ✅ | | ✅ | |
| Gerir regras e configurações | ✅ | | | | |

- **Segregação de funções**: quem submete para aprovação não pode aprovar o mesmo finding.
- **Criptografia**: TLS em trânsito; at-rest pelo provedor (Supabase/AWS); colunas sensíveis
  (credenciais de integração ERP) em `pgsodium`/Vault — nunca em texto claro.
- **Planos**: `plans` define módulos e limites (documentos/mês, usuários); verificado na API.

## 3. Pipeline de ingestão (8 estágios)

`UPLOADED → VALIDATED → NORMALIZED → STORED → ANALYZED → RECONCILED → REPORTED → COMPLETED`
(ou `FAILED` com motivo). Cada estágio grava timestamp, contadores e erros por linha
(`batch_errors`: linha/arquivo, campo, valor, mensagem, severidade). Lotes com erros bloqueantes
não seguem para análise; avisos não bloqueiam.

## 4. Modelo de dados (resumo — DDL completo em `supabase/migrations`)

```
tenants ─┬─ memberships ── users(auth)          plans ── tenants.plan_id
         ├─ establishments (CNPJs da empresa)
         ├─ ingestion_batches ── batch_errors
         ├─ fiscal_documents ── fiscal_document_items        (NF-e normalizada)
         ├─ book_entries                                      (escrituração fiscal)
         ├─ ledger_entries                                    (razão contábil)
         ├─ analysis_runs ── findings ── finding_evidence
         │                       └──── finding_reviews        (decisões humanas)
         └─ audit_log  (append-only, hash encadeado)

tax_rules (code, version, valid_from, valid_to, parameters, legal_basis,
           methodology, legal_review_status)   — catálogo global versionado
```

### Finding — contrato mínimo
| Campo | Significado |
|---|---|
| `kind` | `ESTIMATE` (oportunidade estimada), `ALERT` (inconsistência/risco), `VALIDATED` (conclusão após aprovação humana) |
| `amount_type` | `RECOVERABLE_ESTIMATE`, `EXPOSURE_ESTIMATE`, `DIVERGENCE_VALUE`, `NONE` — **não somáveis entre si** |
| `rule_code` + `rule_version` | Regra aplicada, com versão vigente na data do documento |
| `methodology` / `legal_basis` | Como o valor foi calculado e fundamento citado |
| `confidence` | 0–1 com rótulo; reflete o quanto os dados sustentam a conclusão |
| `evidence[]` | Arquivo de origem, lote, linha/xpath, campo, valor observado × esperado |
| `requires_human_validation` | Sempre verdadeiro para estimativas |
| `fingerprint` | Deduplicação entre execuções (mesma ocorrência não duplica) |

## 5. Escala, operação e continuidade
- **Volume**: ingestão em streaming por arquivo; inserção em lote; índices por
  `(tenant_id, period)`, `(tenant_id, access_key)`; particionamento de `fiscal_document_items`
  por período em produção.
- **Filas**: job por lote; idempotência pela `sha256` do arquivo por tenant.
- **Monitoramento**: logs estruturados JSON, `/health`, métricas por estágio do pipeline
  (pronto para OpenTelemetry).
- **Backup/recuperação**: PITR do Supabase; RPO ≤ 5 min / RTO ≤ 1h como meta contratual;
  trilha de auditoria verificável após restauração.
- **Integrações ERP** (fase 2): conectores SAP (OData/RFC), TOTVS Protheus, Oracle via
  `integrations/` com o mesmo contrato do pipeline de ingestão.
