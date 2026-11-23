import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Database, Play, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { cnpj, compact, count, dateTime, money, period, toNum } from "../lib/format";
import { STATUS } from "../lib/labels";
import type { Dashboard as D, Me } from "../lib/types";
import { GroupedBars, Legend, MiniBars, PairedHBars, SERIES, SegmentBar } from "../components/charts/charts";
import { AmountCell, FindingDrawer } from "../components/findings/FindingDrawer";
import { Button, Confidence, Disclaimer, Empty, ErrorBox, Kpi, Loading, PageHeader, Panel, SeverityBadge, StatusBadge } from "../components/ui";

const PIPE_COLOR: Record<string, string> = { OPEN: "#33425e", IN_REVIEW: "#3987e5", PENDING_APPROVAL: "#fab219", VALIDATED: "#199e70", DISMISSED: "#243149" };

export function DemoLoader({ compactMode = false }: { compactMode?: boolean }) {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  const m = useMutation({
    mutationFn: () => api.post("/demo/load"),
    onSuccess: () => setTimeout(() => qc.invalidateQueries(), 1200),
  });
  const can = me?.permissions.includes("ingest");
  return (
    <div className={compactMode ? "" : "flex flex-col items-center gap-3"}>
      <Button variant="primary" onClick={() => m.mutate()} loading={m.isPending} disabled={!can}
              title={can ? undefined : "Seu perfil não pode importar dados"}>
        <Database className="h-4 w-4" />Carregar dataset de demonstração
      </Button>
      {m.isSuccess && <p className="text-xs text-fg-3">Processando pelo pipeline completo (8 estágios)…</p>}
      {m.error && <ErrorBox error={m.error} />}
    </div>
  );
}

export function Dashboard() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const { data: d, isLoading, error } = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<D>("/dashboard"), refetchInterval: 15000 });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  const run = useMutation({ mutationFn: () => api.post("/analysis/run"), onSuccess: () => setTimeout(() => qc.invalidateQueries(), 800) });

  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!d) return null;
  const k = d.kpis;
  const lastRun = d.runs[0];

  if (d.coverage.documents === 0) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Executive Dashboard" title="Inteligência tributária" />
        <Panel>
          <Empty title="Nenhum dado processado para esta empresa" icon={<Database className="h-8 w-8 text-fg-4" />}>
            <p>Importe NF-e (XML/ZIP), escrituração fiscal e razão contábil em <Link to="/ingestion" className="text-accent hover:underline">Ingestão de dados</Link>,
              ou carregue o dataset sintético de demonstração. Todos os indicadores desta tela são calculados pelo motor a partir dos arquivos — nada é pré-preenchido.</p>
            <div className="mt-5"><DemoLoader /></div>
          </Empty>
        </Panel>
      </div>
    );
  }

  const sev = d.by_severity;
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Executive Dashboard"
        title="Onde a empresa pode estar perdendo dinheiro"
        description={<>Base analisada: <span className="num text-fg-2">{count(d.coverage.documents)}</span> NF-e, <span className="num text-fg-2">{count(d.coverage.book_entries)}</span> lançamentos fiscais e <span className="num text-fg-2">{count(d.coverage.ledger_entries)}</span> contábeis · períodos {period(d.coverage.periods[0])} a {period(d.coverage.periods[d.coverage.periods.length - 1])}.</>}
        actions={<>
          {lastRun && <span className="text-2xs text-fg-3">Última análise {dateTime(lastRun.started_at)} · motor v{lastRun.engine_version}</span>}
          <Button size="sm" onClick={() => run.mutate()} loading={run.isPending} disabled={!me?.permissions.includes("run_analysis")}>
            <RefreshCw className="h-3.5 w-3.5" />Reexecutar análise
          </Button>
        </>}
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Recuperação potencial" accent={SERIES.recoverable} value={compact(k.recoverable_estimate)}
             hint="Soma das estimativas de crédito não aproveitado. Não é valor garantido."
             sub={<>Ponderada pela confiança: <span className="num text-fg-2">{compact(k.recoverable_weighted)}</span></>} />
        <Kpi label="Exposição a risco" accent={SERIES.exposure} value={compact(k.exposure_estimate)}
             hint="Créditos possivelmente indevidos e débitos não apurados."
             sub={<>Ponderada pela confiança: <span className="num text-fg-2">{compact(k.exposure_weighted)}</span></>} />
        <Kpi label="Divergências de dados" accent={SERIES.divergence} value={compact(k.divergence_value)}
             hint="Diferenças entre XML, escrituração e contabilidade. Não é valor de tributo."
             sub="Valor absoluto das diferenças entre fontes" />
        <Kpi label="Conclusões validadas" value={money(k.validated_recoverable)}
             sub={<><span className="num text-fg-2">{k.validated_count}</span> crédito(s) aprovados por diretor tributário</>} />
      </div>

      <Disclaimer>
        As três naturezas de valor <strong className="text-fg-2">não são somáveis</strong>: recuperação potencial é estimativa de crédito; exposição é risco de autuação;
        divergência é diferença de dados. Toda oportunidade exige validação humana — a plataforma nunca executa compensações ou retificações.
      </Disclaimer>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Impacto financeiro por competência"
               subtitle="Recuperação potencial × exposição estimada, por período do documento"
               actions={<Legend items={[{ label: "Recuperação potencial", color: SERIES.recoverable }, { label: "Exposição", color: SERIES.exposure }]} />}>
          <GroupedBars data={d.by_period} series={[{ key: "recoverable", label: "Recuperação potencial", color: SERIES.recoverable }, { key: "exposure", label: "Exposição", color: SERIES.exposure }]} />
        </Panel>
        <Panel title="Por tributo" subtitle="Valores estimados ativos"
               actions={<Legend items={[{ label: "Recup.", color: SERIES.recoverable }, { label: "Exp.", color: SERIES.exposure }]} />}>
          <PairedHBars rows={d.by_tax.map((t) => ({ label: t.tax, values: t }))}
                       series={[{ key: "recoverable", label: "Recuperação potencial", color: SERIES.recoverable }, { key: "exposure", label: "Exposição", color: SERIES.exposure }]} />
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Pipeline de recuperação de créditos" subtitle="Estimativas por etapa do fluxo de aprovação"
               actions={<Link to="/credits" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">Abrir <ArrowRight className="h-3 w-3" /></Link>}>
          <ul className="space-y-2.5">
            {d.credit_pipeline.map((p) => {
              const max = Math.max(...d.credit_pipeline.map((x) => toNum(x.amount)), 1);
              return (
                <li key={p.status}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="text-fg-2">{STATUS[p.status]} <span className="num text-fg-4">· {p.count}</span></span>
                    <span className="num text-fg">{compact(p.amount)}</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-ink-700">
                    <div className="h-full rounded-full" style={{ width: `${(toNum(p.amount) / max) * 100}%`, background: PIPE_COLOR[p.status] }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Panel>
        <Panel className="xl:col-span-2" title="Riscos pendentes de atenção" subtitle="Ocorrências ativas não concluídas, por severidade"
               actions={<Link to="/risk" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">Tax Risk <ArrowRight className="h-3 w-3" /></Link>}>
          <SegmentBar segments={[
            { label: "Crítica", value: sev.CRITICAL ?? 0, color: "#d03b3b" }, { label: "Alta", value: sev.HIGH ?? 0, color: "#ec835a" },
            { label: "Média", value: sev.MEDIUM ?? 0, color: "#fab219" }, { label: "Baixa", value: sev.LOW ?? 0, color: "#4b5a76" },
            { label: "Info", value: sev.INFO ?? 0, color: "#2a364d" },
          ]} />
          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-600 pt-3 sm:grid-cols-4">
            {[["Abertas", k.open], ["Em análise", k.in_review], ["Aguardando aprovação", k.pending_approval], ["Críticas sem tratamento", k.critical_open]].map(([l, v]) => (
              <div key={l as string}><div className="label">{l}</div><div className="num mt-1 text-lg text-fg">{v}</div></div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Panel className="xl:col-span-3" title="Maiores ocorrências por impacto financeiro" subtitle="Clique para ver evidências, memória de cálculo e decidir" padded={false}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[12.5px]">
              <tbody>
                {d.top_findings.map((f) => (
                  <tr key={f.id} onClick={() => setSelected(f.id)} className="cursor-pointer border-b border-ink-700/70 last:border-0 hover:bg-ink-700/50">
                    <td className="py-2.5 pl-4 pr-2"><SeverityBadge severity={f.severity} compact /></td>
                    <td className="max-w-[340px] px-2 py-2.5"><div className="truncate text-fg">{f.title}</div><div className="num text-2xs text-fg-3">{f.rule_code} · {f.tax}</div></td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right"><AmountCell type={f.amount_type} value={f.amount} /></td>
                    <td className="px-2 py-2.5"><Confidence value={f.confidence} /></td>
                    <td className="py-2.5 pl-2 pr-4"><StatusBadge status={f.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel className="xl:col-span-2" title="Fornecedores com mais ocorrências" subtitle="Supplier Intelligence (prévia)" padded={false}>
          <table className="w-full text-[12.5px]">
            <thead><tr className="border-b border-ink-600 text-left text-2xs uppercase tracking-wider text-fg-3">
              <th className="py-2 pl-4 font-medium">Fornecedor</th><th className="px-2 py-2 text-right font-medium">Ocorr.</th><th className="py-2 pl-2 pr-4 text-right font-medium">Impacto</th>
            </tr></thead>
            <tbody>
              {d.top_suppliers.map((s) => (
                <tr key={s.cnpj} className="border-b border-ink-700/70 last:border-0">
                  <td className="max-w-[220px] py-2 pl-4"><div className="truncate text-fg">{s.name}</div><div className="num text-2xs text-fg-3">{cnpj(s.cnpj)}</div></td>
                  <td className="num px-2 py-2 text-right text-fg-2">{s.findings}{s.critical > 0 && <span className="ml-1 text-status-serious">({s.critical}↑)</span>}</td>
                  <td className="num py-2 pl-2 pr-4 text-right text-fg">{compact(toNum(s.recoverable) + toNum(s.exposure))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <Panel title="Histórico de execuções" subtitle="Cada execução registra a versão do motor e as versões de regra aplicadas">
        <div className="flex flex-wrap items-end gap-8">
          <div>
            <div className="label mb-2">Ocorrências ativas por execução</div>
            <MiniBars values={[...d.runs].reverse().map((r) => r.findings_total)} />
          </div>
          {lastRun && (
            <div className="min-w-0 flex-1 text-xs text-fg-3">
              <div>Última: <span className="text-fg-2">{dateTime(lastRun.started_at)}</span> · gatilho {lastRun.trigger === "MANUAL" ? "manual" : "ingestão"} ·
                <span className="num text-fg-2"> {lastRun.findings_total}</span> ativas, <span className="num text-fg-2">{lastRun.findings_new}</span> novas, <span className="num text-fg-2">{lastRun.findings_resolved}</span> não mais detectadas</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(lastRun.rule_versions).map(([code, vs]) => (
                  <span key={code} className="num rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 text-2xs text-fg-3">{code} v{vs.join(",v")}</span>
                ))}
              </div>
            </div>
          )}
          <Link to="/ingestion"><Button size="sm" variant="ghost"><Play className="h-3.5 w-3.5" />Pipeline de ingestão</Button></Link>
        </div>
      </Panel>
      <FindingDrawer id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
