# NEXUS — Enterprise Tax Intelligence

Plataforma B2B de inteligência tributária para grandes empresas brasileiras: cruza NF-e, escrituração fiscal e
contabilidade para encontrar **créditos possivelmente não aproveitados, divergências e riscos**, sempre com
evidência, regra versionada, nível de confiança e aprovação humana.

> **Princípio do produto:** evidência antes de número. Nenhum valor é inventado, nenhuma alíquota de ICMS é
> presumida, nenhuma compensação é executada. Estimativas, alertas e conclusões validadas são tipos distintos.

| Documento | Conteúdo |
|---|---|
| [`docs/01-ESTRATEGIA.md`](docs/01-ESTRATEGIA.md) | Oportunidade, concorrência, viabilidade, escopo do MVP, riscos técnicos e regulatórios |
| [`docs/02-ARQUITETURA.md`](docs/02-ARQUITETURA.md) | Arquitetura, multi-tenancy, RBAC, pipeline, modelo de dados, operação |

## O que está implementado (MVP)

```
apps/web            React 18 + TypeScript + Tailwind · 9 telas, tema escuro enterprise, responsivo
services/engine     Python · FastAPI · SQLAlchemy (SQLite local / PostgreSQL em produção)
  ingestion/        parsers NF-e XML/ZIP (defusedxml), CSV e XLSX; validadores CNPJ, chave (DV), CFOP, NCM
  rules/            catálogo de 21 versões de regras com vigência temporal (+ sync para SQL)
  analysis/         motor determinístico: conciliação, créditos, classificação, risco, anomalias, Reforma
  services/         pipeline de 8 estágios, execução de análise, workflow de revisão, read models
  audit/            trilha append-only encadeada por SHA-256
  demo/             gerador de dataset sintético com gabarito das anomalias plantadas
supabase/
  migrations/       schema `nexus`, RLS forçado, SoD no banco, audit imutável, vigência sem sobreposição
  tests/            11 verificações de isolamento/governança em PostgreSQL real
```

| Módulo | Estado |
|---|---|
| Executive Dashboard, Ingestão, Tax Reconciliation, Tax Intelligence, Credit Recovery, Tax Risk, Audit Trail, Regras | ✅ funcional |
| Supplier Intelligence | 🟡 prévia (ranking de fornecedores no dashboard) |
| Tax Simulator, Financial Intelligence, AI Copilot | 🔜 fase 2 (escopo e dependências descritos na própria UI) |

### Regras do motor

| Código | O que detecta | Natureza do valor |
|---|---|---|
| NX-REC-001/002 | NF-e de entrada/saída sem escrituração | recuperação estimada / exposição |
| NX-REC-003 | Escrituração sem XML | exposição |
| NX-REC-004/005 | Divergência de valor / item não escriturado | divergência / recuperação |
| NX-REC-006 | Escrituração × razão contábil por período e tributo | divergência |
| NX-CRD-001 | ICMS destacado não creditado (CFOP elegível) | recuperação estimada |
| NX-CRD-002 | ICMS de ativo (CIAP) — só parcelas 1/48 já transcorridas | recuperação estimada |
| NX-CRD-003 v1/v2 | PIS/COFINS não cumulativo; v2 exclui ICMS da base (05/2023), extinta em 12/2026 | recuperação estimada |
| NX-RSK-001/002/003 | Crédito acima do destacado, duplicidade, documento não autorizado | exposição |
| NX-CLS-001/002/003 | CFOP incompatível com UFs, NCM divergente, mesmo produto com NCMs distintos | — |
| NX-DQ-001/002 | Chave inconsistente com emitente, CNPJ inválido | — |
| NX-ANM-001 | Alíquota efetiva atípica por NCM (mediana/MAD, desvio mínimo 0,5 p.p.) | — |
| NX-RTC-001/002 | NF-e 2026+ sem grupo IBS/CBS; IBS/CBS fora das alíquotas de teste de 2026 | divergência |

## Rodando localmente

Requisitos: **Python 3.10+** ([python.org](https://www.python.org/downloads/) — no Windows, marque
*Add python.exe to PATH*) e **Node.js LTS** ([nodejs.org](https://nodejs.org/), usado só para compilar a
interface na primeira execução).

**Windows:** dê dois cliques em `iniciar.bat`.

**macOS / Linux** (ou qualquer sistema, no terminal, dentro da pasta do projeto):

```bash
python3 iniciar.py
```

O script cria o ambiente Python, instala as dependências, compila a interface na primeira vez e abre o
NEXUS no navegador em **http://localhost:8000** (se a porta estiver ocupada, usa a próxima livre). Na tela
inicial, clique em **Carregar dataset de demonstração**. Para encerrar: `Ctrl+C` na janela do terminal.

Opções: `--porta 8080` para outra porta; `--rebuild` para recompilar a interface após alterações.

O dataset (empresa fictícia, ~600 NF-e, ~1.000 lançamentos fiscais, razão contábil) passa pelo **pipeline
real**; todos os números exibidos são calculados pelo motor a partir dos arquivos.

Desenvolvimento (recarga automática, API em :8000 e interface em :5173): `make setup` e depois `make dev`.

Testes:

```bash
make test
```

```bash
PGHOST=localhost PGPORT=5432 PGUSER=postgres make test-db
```

## Roteiro de demonstração (CFO de indústria, ~10 min)

1. **Ingestão** — carregar o dataset; mostrar os 8 estágios por lote, avisos por linha, SHA-256 e a recusa de reenvio.
2. **Executive Dashboard** — três números que *não se somam*: recuperação potencial (e o valor ponderado pela
   confiança), exposição a risco e divergência de dados. Impacto por competência e por tributo.
3. **Credit Recovery** — abrir uma ocorrência: memória de cálculo, evidência até a linha do CSV e o xpath do XML,
   regra e versão, base legal, confiança, aviso de “não é crédito garantido”.
4. **Workflow** — como *Camila (Analista)*: iniciar análise → propor validação. Trocar para *Ricardo (Diretor)*:
   aprovar com justificativa. Tentar aprovar a própria proposta → bloqueado (segregação de funções).
5. **Tax Reconciliation** — XML × livro × razão; períodos divergentes na contabilidade.
6. **Regras fiscais** — NX-CRD-003 v1 → v2: a mesma análise aplica versões diferentes conforme a data do documento.
7. **Audit Trail** — como *Paulo (Auditor)*: verificar integridade da cadeia.
8. **Isolamento** — trocar para *Rede Aurora* (outro tenant, plano Professional): nenhum dado da Vértice visível.

## Segurança e governança

- Isolamento por tenant na API **e** no banco (RLS forçado; o motor usa papel sem `BYPASSRLS`).
- RBAC com 5 papéis; aprovação exige papel de diretor/admin e pessoa diferente do proponente — também via trigger.
- Trilha de auditoria append-only com hash encadeado; `UPDATE/DELETE` bloqueados por trigger.
- XML de terceiros processado com `defusedxml`; limites de tamanho e de entradas em ZIP.
- Minimização (LGPD): CPF mascarado; arquivo bruto não persistido no MVP (apenas SHA-256).
- `AUTH_MODE=dev` (troca de persona) é recusado com `NEXUS_ENV=production`; produção usa JWT do Supabase.

## Limitações conhecidas (honestas)

- **Base legal** das regras de crédito foi redigida a partir de legislação pública e está marcada como
  *revisão jurídica recomendada*; deve ser validada por tributarista antes de uso comercial.
- **Reforma Tributária**: regras de 2026 refletem LC 214/2025 e o leiaute com grupo IBS/CBS; marcadas como
  *regulamentação em evolução*.
- Fila de processamento é um executor em processo (1 worker); produção deve usar pgmq/Redis + workers.
- Leiaute de escrituração é um CSV/XLSX por item (aliases de colunas); parser nativo de EFD ICMS/IPI (SPED) é fase 2.
- A análise recarrega todos os dados do tenant a cada execução — adequado ao MVP; produção deve particionar por período.
- Dados de demonstração são sintéticos e de empresas fictícias.
