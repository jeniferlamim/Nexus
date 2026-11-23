import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download, Search } from "lucide-react";
import { api } from "../../lib/api";
import { count, money, period } from "../../lib/format";
import { AMOUNT, CATEGORY, SEVERITY, STATUS } from "../../lib/labels";
import type { FindingList } from "../../lib/types";
import { Button, Confidence, Empty, ErrorBox, KindTag, Loading, Select, SeverityBadge, StatusBadge } from "../ui";
import { AmountCell, FindingDrawer } from "./FindingDrawer";

export interface Preset { category?: string; amount_type?: string; severity?: string; status?: string }

const all = (label: string) => ({ value: "", label });

export function FindingsExplorer({ preset = {}, showCategory = true, pageSize = 50, initialSort = "amount" }: { preset?: Preset; showCategory?: boolean; pageSize?: number; initialSort?: string }) {
  const [filters, setFilters] = useState({ category: "", severity: "", status: "", tax: "", amount_type: "", q: "", sort: initialSort });
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const set = (k: keyof typeof filters) => (v: string) => { setFilters((f) => ({ ...f, [k]: v })); setPage(0); };

  const params = useMemo(() => {
    // A user filter narrows the page preset; an empty user filter falls back to the preset.
    const p = new URLSearchParams();
    const f = filters as Record<string, string>;
    const pr = preset as Record<string, string | undefined>;
    new Set([...Object.keys(f), ...Object.keys(pr)]).forEach((k) => {
      const v = f[k] || pr[k];
      if (v) p.set(k, v);
    });
    return p;
  }, [filters, preset]);

  const query = `/findings?${params.toString()}&limit=${pageSize}&offset=${page * pageSize}`;
  const { data, isLoading, error, isFetching } = useQuery({ queryKey: ["findings", query], queryFn: () => api.get<FindingList>(query), placeholderData: keepPreviousData });

  const exportParams = new URLSearchParams(params);
  exportParams.delete("sort");

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 px-4 py-3">
        <label className="relative flex-1 basis-56">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-fg-4" aria-hidden />
          <input value={filters.q} onChange={(e) => set("q")(e.target.value)} placeholder="Buscar por título, fornecedor, CNPJ, chave ou regra"
                 aria-label="Buscar ocorrências"
                 className="h-8 w-full rounded-md border border-ink-500 bg-ink-800 pl-8 pr-3 text-xs text-fg outline-none placeholder:text-fg-4 focus:border-accent" />
        </label>
        {showCategory && <Select label="Categoria" value={filters.category} onChange={set("category")}
                                 options={[all("Todas as categorias"), ...Object.entries(CATEGORY).filter(([k]) => !preset.category || preset.category.split(",").includes(k)).map(([value, label]) => ({ value, label }))]} />}
        <Select label="Severidade" value={filters.severity} onChange={set("severity")} options={[all("Severidade"), ...Object.entries(SEVERITY).map(([value, label]) => ({ value, label }))]} />
        <Select label="Status" value={filters.status} onChange={set("status")} options={[all("Status"), ...Object.entries(STATUS).map(([value, label]) => ({ value, label }))]} />
        <Select label="Tributo" value={filters.tax} onChange={set("tax")} options={[all("Tributo"), ...["ICMS", "PIS/COFINS", "IBS/CBS", "ICMS/PIS/COFINS", "PIS", "COFINS"].map((t) => ({ value: t, label: t }))]} />
        {!preset.amount_type && <Select label="Natureza do valor" value={filters.amount_type} onChange={set("amount_type")} options={[all("Natureza do valor"), ...Object.entries(AMOUNT).map(([value, label]) => ({ value, label }))]} />}
        <Select label="Ordenar" value={filters.sort} onChange={set("sort")} options={[{ value: "amount", label: "Maior valor" }, { value: "severity", label: "Severidade" }, { value: "confidence", label: "Maior confiança" }, { value: "recent", label: "Mais recentes" }, { value: "seq", label: "ID" }]} />
        <Button size="sm" variant="ghost" onClick={() => api.download(`/reports/findings.xlsx?${exportParams}`, "nexus-ocorrencias.xlsx")}><Download className="h-3.5 w-3.5" />XLSX</Button>
      </div>

      {data && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-ink-700 bg-ink-800/50 px-4 py-2 text-xs text-fg-3">
          <span><span className="num text-fg">{count(data.total)}</span> ocorrências</span>
          {Object.entries(data.totals_by_amount_type).filter(([k]) => k !== "NONE").map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1.5">{AMOUNT[k as keyof typeof AMOUNT]}: <span className="num text-fg-2">{money(v)}</span></span>
          ))}
          {isFetching && <span className="text-fg-4">atualizando…</span>}
        </div>
      )}

      {isLoading && <Loading />}
      {error && <div className="p-4"><ErrorBox error={error} /></div>}
      {data && data.items.length === 0 && <Empty title="Nenhuma ocorrência com esses filtros">Ajuste os filtros ou importe dados na tela de Ingestão.</Empty>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-[12.5px]">
            <thead>
              <tr className="border-b border-ink-600 text-left text-2xs uppercase tracking-wider text-fg-3">
                <th className="py-2 pl-4 pr-2 font-medium">ID</th>
                <th className="px-2 py-2 font-medium">Sev.</th>
                <th className="px-2 py-2 font-medium">Ocorrência</th>
                <th className="px-2 py-2 font-medium">Tipo</th>
                <th className="px-2 py-2 text-right font-medium">Valor</th>
                <th className="px-2 py-2 font-medium">Confiança</th>
                <th className="px-2 py-2 font-medium">Período</th>
                <th className="px-2 py-2 font-medium">Regra</th>
                <th className="py-2 pl-2 pr-4 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((f) => (
                <tr key={f.id} onClick={() => setSelected(f.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelected(f.id)}
                    className="cursor-pointer border-b border-ink-700/70 hover:bg-ink-700/50 focus:bg-ink-700/50 focus:outline-none">
                  <td className="num py-2 pl-4 pr-2 text-fg-3">{f.code}</td>
                  <td className="px-2 py-2"><SeverityBadge severity={f.severity} compact /></td>
                  <td className="max-w-[460px] px-2 py-2">
                    <div className="truncate text-fg">{f.title}</div>
                    <div className="truncate text-2xs text-fg-3">{CATEGORY[f.category]}{f.counterparty_name ? ` · ${f.counterparty_name}` : ""}{f.tax ? ` · ${f.tax}` : ""}</div>
                  </td>
                  <td className="px-2 py-2"><KindTag kind={f.kind} /></td>
                  <td className="whitespace-nowrap px-2 py-2 text-right"><AmountCell type={f.amount_type} value={f.estimated_amount} validated={f.validated_amount} /></td>
                  <td className="px-2 py-2"><Confidence value={f.confidence} /></td>
                  <td className="num px-2 py-2 text-fg-2">{period(f.period)}</td>
                  <td className="num whitespace-nowrap px-2 py-2 text-fg-3">{f.rule_code} <span className="text-fg-4">v{f.rule_version}</span></td>
                  <td className="py-2 pl-2 pr-4"><StatusBadge status={f.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > pageSize && (
        <div className="flex items-center justify-between px-4 py-3 text-xs text-fg-3">
          <span>Página {page + 1} de {Math.ceil(data.total / pageSize)}</span>
          <div className="flex gap-2">
            <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Anterior</Button>
            <Button size="sm" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage((p) => p + 1)}>Próxima</Button>
          </div>
        </div>
      )}
      <FindingDrawer id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
