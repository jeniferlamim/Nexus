# NEXUS — Enterprise Tax Intelligence
## Documento 01 · Oportunidade, concorrência, viabilidade e riscos

> Este documento separa explicitamente **fatos com fonte**, **hipóteses a validar** e **decisões**.
> Números de mercado sem fonte citada são hipóteses e devem ser validados em pesquisa primária
> (entrevistas com CFOs/diretores tributários) antes de qualquer uso comercial.

---

### 1. A oportunidade

**Fatos (com fonte pública):**
- O Brasil é historicamente um dos países com maior custo de conformidade tributária do mundo. O
  relatório *Doing Business 2020* (Banco Mundial) estimava ~1.500 horas/ano para uma empresa média
  cumprir obrigações tributárias, contra ~160h na média da OCDE.
- O estoque de contencioso tributário é da ordem de trilhões de reais (estudo Insper, *Contencioso
  Tributário no Brasil*, 2020, estimou ~R$ 5,4 tri / ~75% do PIB para 2019).
- A **Reforma Tributária do consumo** (EC 132/2023, regulamentada pela LC 214/2025) cria a CBS e o
  IBS, com ano de teste em 2026, extinção de PIS/COFINS a partir de 2027 e transição de ICMS/ISS
  até 2033. Durante a transição, grandes empresas operarão **dois sistemas tributários em paralelo**.
- A NF-e é um documento eletrônico estruturado (XML com schema público). Grandes empresas já
  possuem os dados — o problema não é acesso, é **cruzamento, interpretação e priorização**.

**Hipóteses de mercado (a validar):**
- H1. Grandes indústrias e varejistas multiestaduais perdem créditos por falhas de escrituração
  (XML recebido não escriturado, crédito parcial, CFOP de entrada incorreto) em volume material.
- H2. O mercado atual de "recuperação de créditos" é dominado por consultorias com **honorários de
  êxito** (tipicamente 10–30% do recuperado), em projetos pontuais e retroativos. Existe espaço
  para um modelo **contínuo** (licença anual) que detecta a perda no mês em que ela ocorre.
- H3. A transição 2026–2033 gera demanda por simulação e monitoramento que ERPs não resolvem bem,
  porque exige cruzar regras com vigência temporal e dados históricos.

### 2. Concorrência e posicionamento

| Categoria | Exemplos | O que fazem bem | Lacuna explorada pelo NEXUS |
|---|---|---|---|
| Compliance / obrigações acessórias | Thomson Reuters (ONESOURCE/Mastersaf), Sovos (Synchro/Taxweb), SAP DRC, TOTVS TAF | Geração de SPED, apuração, entrega | Foco em **entregar** a obrigação, não em **auditar** e priorizar valor financeiro |
| Gestão de XML / documentos | Qive (ex-Arquivei) e similares | Captura e guarda de NF-e | Pouca inteligência de cruzamento com escrituração e contabilidade |
| Auditoria eletrônica | e-Auditoria e similares | Cruzamentos SPED x XML | UX técnica; pouca leitura executiva; pouca governança de decisão |
| Conteúdo / classificação fiscal | Systax e similares | Base de regras e NCM | Não opera sobre os dados transacionais do cliente |
| Consultorias (Big Four, boutiques) | — | Profundidade jurídica | Projetos pontuais, caros, não contínuos; dados saem da empresa |

> A tabela usa categorias e nomes públicos de mercado; o mapeamento de funcionalidades de cada
> concorrente deve ser confirmado em demos/RFPs antes de material comercial.

**Diferenciais do NEXUS (decisão de produto):**
1. **Evidência antes de número.** Todo valor exibido carrega origem do dado, regra, versão da
   regra, metodologia, nível de confiança e status de validação humana. Isso é o que um CFO e um
   auditor externo precisam para agir — e o que um "chatbot fiscal" não entrega.
2. **Regras com vigência temporal e versionadas.** Cada análise registra qual versão de qual regra
   foi aplicada a cada documento, com base na data do fato gerador. Pré-requisito para atravessar
   a Reforma Tributária sem reescrever o histórico.
3. **Governança nativa.** Fluxo analista → diretor com segregação de funções, trilha de auditoria
   encadeada por hash e proibição arquitetural de executar compensações automaticamente.
4. **Leitura executiva.** Separação clara entre *recuperação potencial estimada*, *exposição a
   risco* e *divergências de dados* — três números que não podem ser somados.
5. **Modelo contínuo** (licença anual + módulos), alinhando incentivo com prevenção, não só com
   recuperação retroativa.

### 3. Viabilidade técnica

| Aspecto | Avaliação | Justificativa |
|---|---|---|
| Parsing de NF-e XML | **Alta** | Schema público (layout 4.00), determinístico |
| Conciliação XML × escrituração × contabilidade | **Alta** | Problema de *join* e tolerâncias; determinístico e auditável |
| Detecção de créditos | **Média** | Elegibilidade depende de fatos que nem sempre estão nos dados (destinação do bem, essencialidade de insumo). Por isso tudo sai como **estimativa** com confiança explícita |
| Anomalias estatísticas | **Média** | Útil para priorização, nunca para conclusão |
| Copilot com IA | **Média** | Viável com RAG sobre as evidências já estruturadas; risco de alucinação mitigado ao responder **apenas** a partir de findings/evidências citáveis. Fica para fase 2 |
| Escala (milhões de NF-e/mês) | **Alta** com arquitetura correta | Particionamento por tenant/período, processamento em filas, workers Python horizontais |

### 4. MVP — escopo decidido

Priorizado conforme pedido: **importação → validação → normalização → conciliação → divergências
→ oportunidades com evidência → revisão humana → trilha de auditoria**.

| Módulo | MVP | Observação |
|---|---|---|
| Ingestão (XML/ZIP, CSV, XLSX) | ✅ | Pipeline com 8 estágios rastreados |
| Tax Reconciliation | ✅ | XML × livro fiscal × razão contábil |
| Tax Intelligence | ✅ | Classificação (CFOP/NCM), qualidade de dados, anomalias |
| Credit Recovery | ✅ | ICMS e PIS/COFINS como **estimativas**, com fluxo de aprovação |
| Tax Risk | ✅ | Exposição por severidade, evidências e histórico de decisões |
| Executive Dashboard | ✅ | Sobre dados reais processados, nunca mock |
| Audit Trail | ✅ | Append-only, encadeado por hash, verificável |
| Regras versionadas | ✅ | Catálogo com vigência; versão gravada em cada finding |
| Planos/limites/RBAC/multi-tenant | ✅ | Aplicado na API e no banco (RLS) |
| Tax Simulator | 🔜 Fase 2 | Depende de catálogo de regras validado juridicamente |
| Supplier Intelligence | 🟡 Parcial | Ranking de fornecedores por ocorrência já no dashboard |
| Financial Intelligence | 🔜 Fase 2 | Requer integração de custos/margens (ERP) |
| AI Copilot | 🔜 Fase 2 | RAG sobre findings/evidências; só responde com citação |

### 5. Riscos

**Regulatórios / jurídicos**
| Risco | Mitigação implementada |
|---|---|
| Apresentar crédito potencial como garantido | Tipo do finding (`ESTIMATE`/`ALERT`/`VALIDATED`) obrigatório; UI e relatórios marcam "estimativa — sujeita a validação" |
| Regra/alíquota incorreta ou desatualizada | Regras com vigência, versão, base legal e `legal_review_status`; regras de crédito saem como "revisão jurídica recomendada" |
| Ação fiscal automática indevida | Não existe endpoint de compensação/retificação. Saída máxima: conclusão validada + relatório |
| Responsabilidade profissional | Termos: plataforma é ferramenta de apoio; decisão é do contribuinte e de seus responsáveis técnicos |
| LGPD | Minimização: CPF de pessoa física mascarado na ingestão; arquivo bruto não é persistido no MVP (apenas hash SHA-256); dados por tenant isolados |
| Reforma Tributária em evolução | Regras de 2026+ marcadas como sujeitas a notas técnicas e regulamentação vigentes |

**Técnicos**
| Risco | Mitigação |
|---|---|
| Vazamento entre tenants | Isolamento em duas camadas: filtro obrigatório no repositório + RLS no PostgreSQL |
| Layouts heterogêneos de exportação de ERP | Mapeamento de colunas com aliases e relatório de erros por linha |
| Volume | Processamento assíncrono por job; workers stateless; particionamento planejado |
| Falsos positivos | Tolerâncias parametrizadas por regra; confiança explícita; feedback da revisão humana |
| Adulteração de trilha | Hash encadeado (SHA-256) com endpoint de verificação |
