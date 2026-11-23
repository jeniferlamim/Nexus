import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Link2, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../lib/api";
import { count, dateTime } from "../lib/format";
import { CATEGORY, LEGAL_REVIEW } from "../lib/labels";
import type { AuditEntry, Me, Rule } from "../lib/types";
import { Button, Disclaimer, Empty, ErrorBox, Loading, PageHeader, Panel, cx } from "../components/ui";

const LEGAL_CLS: Record<string, string> = {
  NOT_REQUIRED: "text-fg-3 ring-ink-500", RECOMMENDED: "text-status-warning ring-status-warning/30",
  PENDING: "text-[#8fb8f0] ring-[#3987e5]/40", APPROVED: "text-accent ring-accent/40",
};

export function Rules() {
  const { data, isLoading, error } = useQuery({ queryKey: ["rules"], queryFn: () => api.get<Rule[]>("/rules") });
  const [open, setOpen] = useState<string | null>(null);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const grouped = Object.entries((data ?? []).reduce<Record<string, Rule[]>>((acc, r) => ((acc[r.code] ??= []).push(r), acc), {}));
  const minYear = 2002, maxYear = 2030;
  const x = (d: string | null) => {
    const y = d ? Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12 : maxYear;
    return ((Math.min(Math.max(y, minYear), maxYear) - minYear) / (maxYear - minYear)) * 100;
  };
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Governança" title="Catálogo de regras fiscais versionadas"
        description="Cada regra tem vigência temporal. A análise aplica a versão vigente na data do documento e grava código + versão em cada ocorrência." />
      <Disclaimer>
        Alíquotas de ICMS não são presumidas: o motor usa o valor destacado no próprio documento. Parâmetros legais (ex.: PIS 1,65% / COFINS 7,6%) aparecem somente com base legal citada.
        Regras marcadas como “revisão jurídica recomendada” ou “regulamentação em evolução” sempre geram estimativas ou alertas — nunca conclusões.
      </Disclaimer>
      <Panel padded={false}>
        <div className="hidden border-b border-ink-600 px-4 py-2 md:grid md:grid-cols-[110px_1fr_200px_1fr] md:gap-4">
          <span className="label">Código</span><span className="label">Regra</span><span className="label">Status jurídico</span>
          <span className="label flex justify-between"><span>{minYear}</span><span>Vigência</span><span>{maxYear}</span></span>
        </div>
        {grouped.map(([code, versions]) => {
          const latest = versions[versions.length - 1];
          return (
            <div key={code} className="border-b border-ink-700 last:border-0">
              <button onClick={() => setOpen(open === code ? null : code)} aria-expanded={open === code}
                      className="grid w-full grid-cols-1 gap-2 px-4 py-2.5 text-left hover:bg-ink-700/40 md:grid-cols-[110px_1fr_200px_1fr] md:items-center md:gap-4">
                <span className="num text-xs text-fg-2">{code}</span>
                <span><span className="text-[13px] text-fg">{latest.name}</span><span className="ml-2 text-2xs text-fg-3">{CATEGORY[latest.category]} · {versions.length} versão(ões)</span></span>
                <span><span className={cx("rounded-full px-2 py-0.5 text-2xs ring-1 ring-inset", LEGAL_CLS[latest.legal_review_status])}>{LEGAL_REVIEW[latest.legal_review_status]}</span></span>
                <span className="relative h-4" aria-label={`Vigência de ${code}`}>
                  <span className="absolute inset-x-0 top-1/2 h-px bg-ink-600" />
                  {versions.map((v, i) => (
                    <span key={v.version} title={`v${v.version}: ${v.valid_from} → ${v.valid_to ?? "em vigor"}`}
                          className="absolute top-1/2 h-2 -translate-y-1/2 rounded-sm"
                          style={{ left: `${x(v.valid_from)}%`, width: `${Math.max(1, x(v.valid_to) - x(v.valid_from))}%`, background: i % 2 ? "#3987e5" : "#2ed39a", opacity: 0.85 }} />
                  ))}
                </span>
              </button>
              {open === code && (
                <div className="space-y-3 bg-ink-850 px-4 py-4">
                  {versions.map((v) => (
                    <div key={v.version} className="rounded-md border border-ink-600 p-3">
                      <div className="flex flex-wrap items-center gap-3 text-xs">
                        <span className="num rounded bg-ink-700 px-1.5 py-0.5 text-fg">v{v.version}</span>
                        <span className="num text-fg-2">{v.valid_from} → {v.valid_to ?? "em vigor"}</span>
                        {v.change_note && <span className="text-status-warning">Mudança: {v.change_note}</span>}
                      </div>
                      <p className="mt-2 text-xs leading-relaxed text-fg-2">{v.methodology}</p>
                      <p className="mt-1.5 text-xs text-fg-3">Base: {v.legal_basis}</p>
                      {Object.keys(v.parameters).length > 0 && (
                        <pre className="num mt-2 overflow-x-auto rounded bg-ink-900 p-2 text-2xs text-fg-3">{JSON.stringify(v.parameters, null, 2)}</pre>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </Panel>
    </div>
  );
}

const ACTIONS: Record<string, string> = {
  "ingestion.uploaded": "Arquivo enviado", "ingestion.processed": "Lote processado", "analysis.completed": "Análise executada",
  "finding.start_review": "Análise iniciada", "finding.propose_validation": "Validação proposta", "finding.propose_dismissal": "Descarte proposto",
  "finding.approve": "Proposta aprovada", "finding.return": "Devolvida para análise", "finding.reopen": "Reaberta", "report.exported": "Relatório exportado",
};

export function Audit() {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  const allowed = me?.permissions.includes("view_audit");
  const { data, isLoading, error } = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditEntry[]>("/audit?limit=300"), enabled: !!allowed });
  const verify = useMutation({ mutationFn: () => api.get<{ valid: boolean; entries: number; head?: string; broken_at_seq?: number; reason?: string }>("/audit/verify") });
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Audit Trail" title="Trilha de auditoria"
        description="Registro append-only de cargas, análises, decisões e exportações. Cada entrada é encadeada à anterior por SHA-256: qualquer alteração quebra a cadeia."
        actions={allowed && <Button onClick={() => verify.mutate()} loading={verify.isPending}><ShieldCheck className="h-4 w-4" />Verificar integridade</Button>} />
      {me && !allowed && <Panel><Empty title="Acesso restrito">A trilha de auditoria é visível para administradores, diretores tributários e auditores. Seu perfil: {me.role_label}.</Empty></Panel>}
      {verify.data && (
        <div className={cx("flex items-center gap-3 rounded-lg border px-4 py-3 text-[13px]", verify.data.valid ? "border-accent/40 bg-accent/5 text-fg" : "border-status-critical/50 bg-status-critical/10 text-[#f3a5a5]")}>
          {verify.data.valid ? <CheckCircle2 className="h-5 w-5 text-accent" /> : <ShieldX className="h-5 w-5" />}
          {verify.data.valid
            ? <span>Cadeia íntegra: <span className="num">{count(verify.data.entries)}</span> entradas verificadas · head <span className="num text-fg-3">{verify.data.head?.slice(0, 16)}…</span></span>
            : <span>Integridade violada na entrada #{verify.data.broken_at_seq}: {verify.data.reason}</span>}
        </div>
      )}
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <Panel padded={false}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-[12.5px]">
              <thead><tr className="border-b border-ink-600 text-left text-2xs uppercase tracking-wider text-fg-3">
                <th className="py-2 pl-4 font-medium">#</th><th className="px-2 py-2 font-medium">Quando</th><th className="px-2 py-2 font-medium">Responsável</th>
                <th className="px-2 py-2 font-medium">Evento</th><th className="px-2 py-2 font-medium">Detalhes</th><th className="py-2 pl-2 pr-4 font-medium">Hash</th>
              </tr></thead>
              <tbody>
                {data.map((e) => (
                  <tr key={e.seq} className="border-b border-ink-700/70 align-top last:border-0">
                    <td className="num py-2 pl-4 text-fg-3">{e.seq}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-fg-2">{dateTime(e.at)}</td>
                    <td className="px-2 py-2 text-fg">{e.actor_name}</td>
                    <td className="px-2 py-2 text-fg-2">{ACTIONS[e.action] ?? e.action}</td>
                    <td className="max-w-[420px] px-2 py-2 text-xs text-fg-3">
                      {Object.entries(e.payload).filter(([, v]) => v !== null && typeof v !== "object").slice(0, 6).map(([k, v]) => (
                        <span key={k} className="mr-3 inline-block"><span className="text-fg-4">{k}:</span> <span className="text-fg-2">{String(v).slice(0, 80)}</span></span>
                      ))}
                    </td>
                    <td className="num whitespace-nowrap py-2 pl-2 pr-4 text-2xs text-fg-4" title={`prev ${e.prev_hash}\nhash ${e.hash}`}><Link2 className="mr-1 inline h-3 w-3" />{e.hash.slice(0, 12)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

const MODULE_LABEL: Record<string, string> = {
  executive_dashboard: "Executive Dashboard", ingestion: "Ingestão", tax_reconciliation: "Tax Reconciliation", tax_intelligence: "Tax Intelligence",
  credit_recovery: "Credit Recovery", tax_risk: "Tax Risk", audit_trail: "Audit Trail", tax_simulator: "Tax Simulator",
  supplier_intelligence: "Supplier Intelligence", financial_intelligence: "Financial Intelligence", ai_copilot: "AI Copilot",
};

export function Settings() {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  if (!me) return <Loading />;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Governança" title="Empresa, plano e acesso" description="Parâmetros do contrato enterprise e do perfil de análise desta empresa." />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Empresa">
          <dl className="space-y-2 text-xs">
            {[["Razão social", me.tenant.legal_name], ["Segmento", me.tenant.segment], ["Raízes de CNPJ", me.tenant.cnpj_roots.join(", ")],
              ["Regime PIS/COFINS", me.tenant.tax_regime === "NON_CUMULATIVE" ? "Não cumulativo (Lucro Real)" : "Cumulativo"],
              ["Retenção de dados", `${me.tenant.data_retention_days} dias`],
              ["Contas de tributos a recuperar", Object.entries(me.tenant.ledger_accounts).map(([t, a]) => `${t}: ${a.join(", ")}`).join(" · ") || "não mapeadas"]].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-ink-700 pb-2 last:border-0"><dt className="text-fg-3">{k}</dt><dd className="text-right text-fg">{v}</dd></div>
            ))}
          </dl>
        </Panel>
        <Panel title={`Plano ${me.plan.name}`} subtitle="Licença anual · limites aplicados pela API">
          <dl className="space-y-2 text-xs">
            <div className="flex justify-between"><dt className="text-fg-3">Documentos / mês</dt><dd className="num text-fg">{count(me.plan.max_documents_month)}</dd></div>
            <div className="flex justify-between"><dt className="text-fg-3">Usuários</dt><dd className="num text-fg">{me.plan.max_users}</dd></div>
            <div className="flex justify-between"><dt className="text-fg-3">Tamanho máximo de arquivo</dt><dd className="num text-fg">{me.plan.max_file_mb} MB</dd></div>
          </dl>
          <div className="label mb-2 mt-4">Módulos</div>
          <ul className="grid grid-cols-1 gap-1 text-xs">
            {Object.entries(MODULE_LABEL).map(([k, l]) => (
              <li key={k} className={cx("flex items-center gap-2", me.plan.modules.includes(k) ? "text-fg" : "text-fg-4")}>
                <span className={cx("h-1.5 w-1.5 rounded-full", me.plan.modules.includes(k) ? "bg-accent" : "bg-ink-500")} />{l}
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Seu acesso">
          <div className="text-[13px] text-fg">{me.user.name}</div>
          <div className="text-xs text-fg-3">{me.user.title} · {me.role_label}</div>
          <div className="label mb-2 mt-4">Permissões</div>
          <div className="flex flex-wrap gap-1.5">
            {me.permissions.map((p) => <span key={p} className="num rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 text-2xs text-fg-2">{p}</span>)}
          </div>
          <p className="mt-4 text-2xs text-fg-3">Aprovações exigem perfil de Diretor Tributário ou Administrador e pessoa diferente de quem propôs (segregação de funções, aplicada também no banco de dados).</p>
        </Panel>
      </div>
    </div>
  );
}

const ROADMAP: Record<string, { title: string; summary: string; points: string[]; dependency: string }> = {
  tax_simulator: {
    title: "Tax Simulator", summary: "Simulação de cenários tributários com regras parametrizadas e vigência temporal, incluindo a transição 2026–2033.",
    points: ["Cenários sobre a base real de documentos da empresa", "Comparação lado a lado de cenários", "Parametrização por regra versionada (mesmo catálogo do motor)", "Impacto em caixa e margem por cenário"],
    dependency: "Catálogo de alíquotas de IBS/CBS validado juridicamente para os anos de transição.",
  },
  supplier_intelligence: {
    title: "Supplier Intelligence", summary: "Indicadores de risco por fornecedor a partir do histórico de ocorrências e documentos.",
    points: ["Score de risco documental por fornecedor", "Histórico de inconsistências e prontidão para IBS/CBS", "Concentração de compras e exposição", "Já disponível em prévia no Executive Dashboard"],
    dependency: "Consulta a cadastros públicos (situação cadastral) via integração autorizada.",
  },
  financial_intelligence: {
    title: "Financial Intelligence", summary: "Custo tributário por produto, unidade e cliente, e impacto nas margens.",
    points: ["Carga tributária efetiva por linha de produto", "Despesas fora do padrão", "Indicadores de rentabilidade pós-tributo"],
    dependency: "Integração de custos e receitas com o ERP (conectores SAP/TOTVS).",
  },
  ai_copilot: {
    title: "AI Copilot", summary: "Consultas em linguagem natural sobre ocorrências, documentos e regras — respondendo apenas com base em evidências citáveis.",
    points: ["Recuperação sobre findings, evidências e catálogo de regras (RAG)", "Toda resposta cita IDs de ocorrência, documentos e regras", "Recusa responder sem evidência na base", "Nunca gera valores: lê os valores calculados pelo motor"],
    dependency: "Motor determinístico estável (concluído no MVP) e avaliação de qualidade das respostas.",
  },
};

export function Roadmap() {
  const { module = "" } = useParams();
  const r = ROADMAP[module];
  if (!r) return <Empty title="Módulo não encontrado" />;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Próxima fase" title={r.title} description={r.summary} />
      <Panel title="Escopo planejado">
        <ul className="space-y-2 text-[13px] text-fg-2">{r.points.map((p) => <li key={p} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />{p}</li>)}</ul>
        <p className="mt-4 text-xs text-fg-3">Dependência: {r.dependency}</p>
      </Panel>
      <Disclaimer>Este módulo não está implementado no MVP. A prioridade foi entregar primeiro uma base confiável de importação, conciliação e detecção de divergências.</Disclaimer>
    </div>
  );
}
