import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { compact, count, money, period, toNum } from "../lib/format";
import type { Reconciliation as R } from "../lib/types";
import { FindingsExplorer } from "../components/findings/FindingsExplorer";
import { Disclaimer, ErrorBox, Kpi, Loading, PageHeader, Panel, cx } from "../components/ui";
import { SERIES } from "../components/charts/charts";

export function Reconciliation() {
  const { data, isLoading, error } = useQuery({ queryKey: ["reconciliation"], queryFn: () => api.get<R>("/reconciliation") });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const s = data.summary;
  const matchRate = s.xml_documents ? s.matched / s.xml_documents : 0;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Tax Reconciliation" title="Cruzamento XML × escrituração × contabilidade"
        description="Documentos fiscais comparados com o que foi escriturado e com o que foi contabilizado nas contas de tributos a recuperar." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="NF-e na base" value={count(s.xml_documents)} />
        <Kpi label="Documentos escriturados" value={count(s.book_documents)} />
        <Kpi label="Conciliados" value={count(s.matched)} sub={`${(matchRate * 100).toFixed(1).replace(".", ",")}% dos XMLs`} accent={SERIES.recoverable} />
        <Kpi label="Só no XML" value={count(s.xml_only)} sub="Não escriturados" accent={SERIES.exposure} />
        <Kpi label="Só na escrituração" value={count(s.book_only)} sub="Sem XML na base" accent={SERIES.divergence} />
      </div>
      {s.uncovered_periods.length > 0 && (
        <Disclaimer>Períodos sem cobertura das duas fontes ({s.uncovered_periods.map(period).join(", ")}) não geram alertas de ausência, para evitar falsos positivos por carga parcial.</Disclaimer>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Conciliação documental por período" padded={false}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[12.5px]">
              <thead><tr className="border-b border-ink-600 text-right text-2xs uppercase tracking-wider text-fg-3">
                <th className="py-2 pl-4 text-left font-medium">Período</th><th className="px-2 py-2 font-medium">Entradas</th><th className="px-2 py-2 font-medium">Saídas</th>
                <th className="px-2 py-2 font-medium">Conciliados</th><th className="px-2 py-2 font-medium">Só XML</th><th className="px-2 py-2 font-medium">Só livro</th><th className="py-2 pl-2 pr-4 font-medium">Valor não escriturado</th>
              </tr></thead>
              <tbody>
                {data.by_period.map((p) => (
                  <tr key={p.period} className={cx("border-b border-ink-700/70 text-right last:border-0", !p.covered && "text-fg-4")}>
                    <td className="num py-2 pl-4 text-left text-fg-2">{period(p.period)}{!p.covered && <span className="ml-1.5 text-2xs">(sem cobertura)</span>}</td>
                    <td className="num px-2 py-2">{p.xml_in}</td><td className="num px-2 py-2">{p.xml_out}</td>
                    <td className="num px-2 py-2 text-fg">{p.matched}</td>
                    <td className={cx("num px-2 py-2", p.xml_only > 0 && p.covered && "text-[#f0a072]")}>{p.xml_only}</td>
                    <td className={cx("num px-2 py-2", p.book_only > 0 && "text-[#8fb8f0]")}>{p.book_only}</td>
                    <td className="num py-2 pl-2 pr-4">{toNum(p.unmatched_value) > 0 ? compact(p.unmatched_value) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Escrituração × contabilidade" subtitle={`Créditos escriturados vs. débitos nas contas ${Object.entries(data.ledger_accounts).map(([t, a]) => `${t} ${a.join("/")}`).join(" · ") || "(não mapeadas)"}`} padded={false}>
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full min-w-[520px] text-[12.5px]">
              <thead className="sticky top-0 bg-ink-750"><tr className="border-b border-ink-600 text-right text-2xs uppercase tracking-wider text-fg-3">
                <th className="py-2 pl-4 text-left font-medium">Período</th><th className="px-2 py-2 text-left font-medium">Tributo</th>
                <th className="px-2 py-2 font-medium">Escriturado</th><th className="px-2 py-2 font-medium">Contabilizado</th><th className="py-2 pl-2 pr-4 font-medium">Diferença</th>
              </tr></thead>
              <tbody>
                {data.ledger.map((l) => (
                  <tr key={l.period + l.tax} className={cx("border-b border-ink-700/70 text-right last:border-0", l.status === "DIVERGENT" && "bg-status-serious/5")}>
                    <td className="num py-1.5 pl-4 text-left text-fg-2">{period(l.period)}</td>
                    <td className="px-2 py-1.5 text-left text-fg-2">{l.tax}</td>
                    <td className="num px-2 py-1.5">{money(l.book)}</td>
                    <td className="num px-2 py-1.5">{money(l.ledger)}</td>
                    <td className={cx("num py-1.5 pl-2 pr-4", l.status === "DIVERGENT" ? "font-medium text-status-serious" : "text-fg-4")}>
                      {l.status === "DIVERGENT" ? `⚠ ${money(l.difference)}` : "✓ conciliado"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel title="Divergências de conciliação" subtitle="Ocorrências geradas pelas regras NX-REC-*" padded={false}>
        <FindingsExplorer preset={{ category: "RECONCILIATION" }} showCategory={false} />
      </Panel>
    </div>
  );
}
