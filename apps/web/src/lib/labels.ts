import type { AmountType, FindingStatus, Kind, Severity } from "./types";

export const CATEGORY: Record<string, string> = {
  RECONCILIATION: "Conciliação", CREDIT_OPPORTUNITY: "Oportunidade de crédito", CLASSIFICATION: "Classificação fiscal",
  COMPLIANCE_RISK: "Risco de conformidade", DATA_QUALITY: "Qualidade de dados", ANOMALY: "Padrão anormal",
  TAX_REFORM: "Reforma Tributária",
};
export const KIND: Record<Kind, string> = { ESTIMATE: "Estimativa", ALERT: "Alerta", VALIDATED: "Conclusão validada" };
export const STATUS: Record<FindingStatus, string> = {
  OPEN: "Aberta", IN_REVIEW: "Em análise", PENDING_APPROVAL: "Aguardando aprovação", VALIDATED: "Validada", DISMISSED: "Descartada",
};
export const SEVERITY: Record<Severity, string> = { CRITICAL: "Crítica", HIGH: "Alta", MEDIUM: "Média", LOW: "Baixa", INFO: "Info" };
export const AMOUNT: Record<AmountType, string> = {
  RECOVERABLE_ESTIMATE: "Recuperação potencial", EXPOSURE_ESTIMATE: "Exposição estimada", DIVERGENCE_VALUE: "Divergência de dados", NONE: "Sem valor",
};
export const SOURCE: Record<string, string> = { NFE_XML: "NF-e (XML/ZIP)", FISCAL_BOOK: "Escrituração fiscal", LEDGER: "Razão contábil" };
export const LEGAL_REVIEW: Record<string, string> = {
  NOT_REQUIRED: "Consistência de dados", RECOMMENDED: "Revisão jurídica recomendada", PENDING: "Regulamentação em evolução", APPROVED: "Aprovada juridicamente",
};
export const ROLE: Record<string, string> = {
  admin: "Administrador", tax_director: "Diretor Tributário", tax_analyst: "Analista Tributário", auditor: "Auditor", viewer: "Leitura",
};
export const SEV_ORDER: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
