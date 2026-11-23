export type AmountType = "RECOVERABLE_ESTIMATE" | "EXPOSURE_ESTIMATE" | "DIVERGENCE_VALUE" | "NONE";
export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type FindingStatus = "OPEN" | "IN_REVIEW" | "PENDING_APPROVAL" | "VALIDATED" | "DISMISSED";
export type Kind = "ESTIMATE" | "ALERT" | "VALIDATED";

export interface Me {
  user: { id: string; name: string; email: string; title: string };
  role: string;
  role_label: string;
  permissions: string[];
  tenant: { id: string; name: string; legal_name: string; segment: string; cnpj_roots: string[]; tax_regime: string;
            ledger_accounts: Record<string, string[]>; data_retention_days: number };
  plan: { code: string; name: string; modules: string[]; max_documents_month: number; max_users: number; max_file_mb: number };
  tenants: { id: string; name: string; role: string }[];
}

export interface Persona { user_id: string; name: string; title: string; tenant_id: string; tenant_name: string; role: string; role_label: string }

export interface FindingSummary {
  id: string; seq: number; code: string; rule_code: string; rule_version: number; category: string; kind: Kind;
  severity: Severity; title: string; status: FindingStatus; amount_type: AmountType; estimated_amount: string;
  validated_amount: string | null; confidence: number; confidence_label: string; tax: string | null; period: string | null;
  access_key: string | null; counterparty_cnpj: string | null; counterparty_name: string | null; is_active: boolean;
  requires_human_validation: boolean; proposal: string | null; updated_at: string | null;
}

export interface Evidence { source: string; locator: string; field: string; observed: string; expected: string; note: string }
export interface Review { actor_name: string; actor_role: string; action: string; from_status: string; to_status: string; comment: string; validated_amount: string | null; at: string }
export interface Rule { code: string; version: number; name: string; category: string; valid_from: string; valid_to: string | null;
  methodology: string; legal_basis: string; legal_review_status: string; parameters: Record<string, unknown>; change_note: string }
export interface Action { action: string; label: string; needs_comment: boolean; blocked_reason: string | null }

export interface FindingDetail extends FindingSummary {
  description: string; methodology: string; legal_basis: string; calculation: Record<string, string>;
  rule: Rule | null; evidence: Evidence[]; reviews: Review[]; actions: Action[];
}

export interface FindingList { total: number; totals_by_amount_type: Record<string, string>; items: FindingSummary[] }

export interface Stage { stage: string; label: string; status: "DONE" | "FAILED" | "SKIPPED" | "PENDING"; at: string | null; detail: string }
export interface Batch {
  id: string; source_type: "NFE_XML" | "FISCAL_BOOK" | "LEDGER"; filename: string; sha256: string; size_bytes: number;
  status: string; records_total: number; records_valid: number; records_rejected: number; warnings: number; periods: string[];
  error: string | null; created_at: string; finished_at: string | null; stages: Stage[];
  errors?: { source: string; locator: string; field: string; value: string; message: string; severity: string }[];
}

export interface Dashboard {
  kpis: Record<string, string | number>;
  by_tax: { tax: string; recoverable: string; exposure: string }[];
  by_period: { period: string; recoverable: string; exposure: string; divergence: string }[];
  by_category: { category: string; count: number; amount: string }[];
  by_severity: Record<string, number>;
  credit_pipeline: { status: FindingStatus; count: number; amount: string }[];
  top_findings: (Pick<FindingSummary, "id" | "seq" | "title" | "amount_type" | "severity" | "confidence" | "status" | "rule_code" | "tax" | "kind"> & { amount: string })[];
  top_suppliers: { cnpj: string; name: string; findings: number; recoverable: string; exposure: string; critical: number }[];
  coverage: { documents: number; periods: string[]; book_entries: number; ledger_entries: number; tax_regime: string };
  runs: { id: string; started_at: string; trigger: string; findings_total: number; findings_new: number; findings_resolved: number;
          engine_version: string; rule_versions: Record<string, number[]>; stats: Record<string, unknown>; amount_by_type: Record<string, string> }[];
}

export interface Reconciliation {
  summary: { xml_documents: number; book_documents: number; matched: number; xml_only: number; book_only: number;
             covered_periods: string[]; uncovered_periods: string[] };
  by_period: { period: string; covered: boolean; xml_in: number; xml_out: number; matched: number; xml_only: number; book_only: number; xml_value: string; unmatched_value: string }[];
  ledger: { period: string; tax: string; book: string; ledger: string; difference: string; status: "OK" | "DIVERGENT" }[];
  ledger_accounts: Record<string, string[]>;
}

export interface AuditEntry { seq: number; at: string; actor_name: string; action: string; entity_type: string; entity_id: string; payload: Record<string, unknown>; hash: string; prev_hash: string }
