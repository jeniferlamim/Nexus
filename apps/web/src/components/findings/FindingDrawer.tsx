import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Calculator, FileText, History, Lock, Scale, X } from "lucide-react";
import { api } from "../../lib/api";
import { cnpj, dateTime, money, period } from "../../lib/format";
import { AMOUNT, CATEGORY, LEGAL_REVIEW, ROLE, STATUS } from "../../lib/labels";
import type { FindingDetail, FindingStatus } from "../../lib/types";
import { AmountTypeDot, Button, Confidence, ErrorBox, KindTag, Loading, SeverityBadge, StatusBadge, cx } from "../ui";

const ACTION_LABEL: Record<string, string> = {
  start_review: "Iniciou análise", propose_validation: "Propôs validação", propose_dismissal: "Propôs descarte",
  approve: "Aprovou", return: "Devolveu para análise", reopen: "Reabriu",
};

function Section({ icon: Icon, title, children }: { icon: typeof FileText; title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-ink-600 px-5 py-4">
      <h3 className="label mb-2.5 flex items-center gap-1.5 text-fg-2"><Icon className="h-3.5 w-3.5" aria-hidden />{title}</h3>
      {children}
    </section>
  );
}

export function FindingDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: f, isLoading, error } = useQuery({ queryKey: ["finding", id], queryFn: () => api.get<FindingDetail>(`/findings/${id}`), enabled: !!id });
  const [action, setAction] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [amount, setAmount] = useState("");

  useEffect(() => { setAction(null); setComment(""); setAmount(""); }, [id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const m = useMutation({
    mutationFn: (body: { action: string; comment: string; validated_amount?: string }) => api.post<FindingDetail>(`/findings/${id}/transition`, body),
    onSuccess: (data) => {
      qc.setQueryData(["finding", id], data);
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setAction(null); setComment(""); setAmount("");
    },
  });

  if (!id) return null;
  const selected = f?.actions.find((a) => a.action === action);
  const submit = () => {
    if (!action) return;
    m.mutate({ action, comment, ...(action === "approve" && f?.proposal === "VALIDATE" && amount ? { validated_amount: amount.replace(/\./g, "").replace(",", ".") } : {}) });
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label="Detalhe da ocorrência">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-[720px] flex-col border-l border-ink-500 bg-ink-850 shadow-2xl">
        <div className="flex items-center justify-between border-b border-ink-600 px-5 py-3">
          <div className="flex items-center gap-2 text-xs text-fg-3">
            <span className="num text-fg-2">{f?.code}</span>
            {f && <span>· {CATEGORY[f.category]}</span>}
          </div>
          <button onClick={onClose} className="rounded p-1 text-fg-3 hover:bg-ink-700 hover:text-fg" aria-label="Fechar"><X className="h-4 w-4" /></button>
        </div>
        {isLoading && <Loading />}
        {error && <div className="p-5"><ErrorBox error={error} /></div>}
        {f && (
          <div className="flex-1 overflow-y-auto">
            <div className="px-5 pb-4 pt-4">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={f.severity} /><KindTag kind={f.kind} /><StatusBadge status={f.status} />
                {!f.is_active && <span className="text-2xs text-fg-3">Não detectada na última execução</span>}
              </div>
              <h2 className="mt-2.5 text-[17px] font-semibold leading-snug tracking-tight text-fg">{f.title}</h2>
              <p className="mt-2 text-[13px] leading-relaxed text-fg-2">{f.description}</p>

              <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-ink-600 bg-ink-600 sm:grid-cols-4">
                <div className="bg-ink-800 p-3">
                  <div className="label">{f.status === "VALIDATED" ? "Valor validado" : "Valor estimado"}</div>
                  <div className="num mt-1.5 text-[17px] text-fg">{f.amount_type === "NONE" ? "—" : money(f.validated_amount ?? f.estimated_amount)}</div>
                  <div className="mt-1"><AmountTypeDot type={f.amount_type} /></div>
                </div>
                <div className="bg-ink-800 p-3"><div className="label">Confiança</div><div className="mt-2"><Confidence value={f.confidence} label={f.confidence_label} /></div></div>
                <div className="bg-ink-800 p-3"><div className="label">Tributo · Período</div><div className="mt-1.5 text-[13px] text-fg">{f.tax ?? "—"} · {period(f.period)}</div></div>
                <div className="bg-ink-800 p-3"><div className="label">Regra aplicada</div><div className="num mt-1.5 text-[13px] text-fg">{f.rule_code} v{f.rule_version}</div></div>
              </div>
              {f.amount_type === "RECOVERABLE_ESTIMATE" && f.kind !== "VALIDATED" && (
                <p className="mt-3 rounded-md border border-status-warning/25 bg-status-warning/5 px-3 py-2 text-xs text-[#e8c777]">
                  Estimativa — não é crédito garantido. Depende de validação por profissional habilitado antes de qualquer aproveitamento.
                </p>
              )}
              {(f.counterparty_name || f.access_key) && (
                <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                  {f.counterparty_name && <div className="flex gap-2"><dt className="text-fg-3">Participante</dt><dd className="text-fg-2">{f.counterparty_name} · <span className="num">{cnpj(f.counterparty_cnpj)}</span></dd></div>}
                  {f.access_key && <div className="flex gap-2 sm:col-span-2"><dt className="shrink-0 text-fg-3">Chave NF-e</dt><dd className="num break-all text-fg-2">{f.access_key}</dd></div>}
                </dl>
              )}
            </div>

            {Object.keys(f.calculation).length > 0 && (
              <Section icon={Calculator} title="Memória de cálculo">
                <table className="w-full text-xs"><tbody>
                  {Object.entries(f.calculation).map(([k, v]) => (
                    <tr key={k} className="border-b border-ink-700 last:border-0"><td className="w-40 py-1.5 pr-3 align-top text-fg-3">{k}</td><td className="num py-1.5 text-fg-2">{v}</td></tr>
                  ))}
                </tbody></table>
              </Section>
            )}

            <Section icon={FileText} title={`Evidências (${f.evidence.length})`}>
              <div className="overflow-x-auto rounded-md border border-ink-600">
                <table className="w-full min-w-[560px] text-xs">
                  <thead className="bg-ink-800 text-left text-fg-3"><tr>
                    <th className="px-2.5 py-1.5 font-medium">Origem</th><th className="px-2.5 py-1.5 font-medium">Localização</th>
                    <th className="px-2.5 py-1.5 font-medium">Campo</th><th className="px-2.5 py-1.5 font-medium">Observado</th><th className="px-2.5 py-1.5 font-medium">Esperado</th>
                  </tr></thead>
                  <tbody>
                    {f.evidence.map((e, i) => (
                      <tr key={i} className="border-t border-ink-700 align-top">
                        <td className="max-w-[160px] truncate px-2.5 py-1.5 text-fg-2" title={e.source}>{e.source}</td>
                        <td className="num max-w-[170px] truncate px-2.5 py-1.5 text-fg-3" title={e.locator}>{e.locator}</td>
                        <td className="num px-2.5 py-1.5 text-fg-3">{e.field}</td>
                        <td className="num px-2.5 py-1.5 text-fg">{e.observed}</td>
                        <td className="num px-2.5 py-1.5 text-fg-2">{e.expected || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>

            <Section icon={BookOpenCheck} title="Metodologia e base legal">
              <p className="text-xs leading-relaxed text-fg-2">{f.methodology}</p>
              <p className="mt-2 flex gap-1.5 text-xs leading-relaxed text-fg-3"><Scale className="mt-0.5 h-3.5 w-3.5 shrink-0" />{f.legal_basis}</p>
              {f.rule && (
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-fg-3">
                  <span>Vigência: <span className="num text-fg-2">{f.rule.valid_from} → {f.rule.valid_to ?? "em vigor"}</span></span>
                  <span>Status jurídico: <span className="text-fg-2">{LEGAL_REVIEW[f.rule.legal_review_status]}</span></span>
                  {f.rule.change_note && <span>Mudança desta versão: <span className="text-fg-2">{f.rule.change_note}</span></span>}
                </div>
              )}
            </Section>

            <Section icon={History} title="Decisões e histórico">
              {f.reviews.length === 0 && <p className="text-xs text-fg-3">Nenhuma decisão registrada. Toda conclusão exige revisão humana.</p>}
              <ol className="space-y-2.5">
                {f.reviews.map((r, i) => (
                  <li key={i} className="relative border-l border-ink-500 pl-3">
                    <span className="absolute -left-[3.5px] top-1.5 h-1.5 w-1.5 rounded-full bg-fg-3" />
                    <div className="text-xs text-fg"><span className="font-medium">{r.actor_name}</span> <span className="text-fg-3">({ROLE[r.actor_role] ?? r.actor_role})</span> · {ACTION_LABEL[r.action] ?? r.action}</div>
                    <div className="text-2xs text-fg-3">{dateTime(r.at)} · {STATUS[r.from_status as FindingStatus]} → {STATUS[r.to_status as FindingStatus]}{r.validated_amount ? ` · valor validado ${money(r.validated_amount)}` : ""}</div>
                    {r.comment && <p className="mt-1 text-xs text-fg-2">“{r.comment}”</p>}
                  </li>
                ))}
              </ol>
            </Section>
          </div>
        )}

        {f && (
          <div className="border-t border-ink-600 bg-ink-800 px-5 py-3">
            {f.actions.length === 0 ? (
              <p className="flex items-center gap-1.5 text-xs text-fg-3"><Lock className="h-3.5 w-3.5" />Sem ações disponíveis para o seu perfil neste status.</p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  {f.actions.map((a) => (
                    <Button key={a.action} size="sm" disabled={!!a.blocked_reason} title={a.blocked_reason ?? undefined}
                            variant={action === a.action ? "primary" : a.action === "propose_dismissal" ? "ghost" : "secondary"}
                            onClick={() => (a.needs_comment ? setAction(a.action === action ? null : a.action) : m.mutate({ action: a.action, comment: "" }))}>
                      {a.blocked_reason && <Lock className="h-3 w-3" />}{a.label}
                    </Button>
                  ))}
                </div>
                {f.actions.some((a) => a.blocked_reason) && (
                  <p className="mt-2 text-2xs text-fg-3">{f.actions.find((a) => a.blocked_reason)?.blocked_reason}</p>
                )}
                {selected && (
                  <div className="mt-3 space-y-2">
                    {action === "approve" && f.proposal && (
                      <p className="text-xs text-fg-2">Proposta em avaliação: <strong className="text-fg">{f.proposal === "VALIDATE" ? "validar ocorrência" : "descartar ocorrência"}</strong>.
                        {f.proposal === "VALIDATE" && " A aprovação registra uma conclusão validada; nenhuma compensação ou retificação é executada pela plataforma."}</p>
                    )}
                    <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3}
                              placeholder="Justificativa (obrigatória, mín. 10 caracteres) — será gravada na trilha de auditoria"
                              className="w-full rounded-md border border-ink-500 bg-ink-850 px-3 py-2 text-xs text-fg outline-none placeholder:text-fg-4 focus:border-accent" />
                    {action === "approve" && f.proposal === "VALIDATE" && f.amount_type !== "NONE" && (
                      <label className="flex items-center gap-2 text-xs text-fg-2">
                        Valor validado (R$)
                        <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={Number(f.estimated_amount).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                               className="num h-7 w-40 rounded border border-ink-500 bg-ink-850 px-2 text-xs text-fg outline-none focus:border-accent" />
                        <span className="text-2xs text-fg-3">vazio = valor estimado</span>
                      </label>
                    )}
                    <div className="flex items-center gap-2">
                      <Button variant="primary" size="sm" loading={m.isPending} disabled={comment.trim().length < 10} onClick={submit}>Confirmar: {selected.label}</Button>
                      <Button variant="ghost" size="sm" onClick={() => setAction(null)}>Cancelar</Button>
                    </div>
                  </div>
                )}
                {m.error && <div className="mt-2"><ErrorBox error={m.error} /></div>}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function AmountCell({ type, value, validated }: { type: keyof typeof AMOUNT; value: string; validated?: string | null }) {
  if (type === "NONE") return <span className="text-fg-4">—</span>;
  return (
    <span className={cx("num inline-flex items-center gap-1.5", type === "DIVERGENCE_VALUE" ? "text-fg-2" : "text-fg")}>
      <span className="h-1.5 w-1.5 rounded-sm" style={{ background: type === "RECOVERABLE_ESTIMATE" ? "#199e70" : type === "EXPOSURE_ESTIMATE" ? "#d95926" : "#3987e5" }} aria-hidden />
      {money(validated ?? value)}
    </span>
  );
}
