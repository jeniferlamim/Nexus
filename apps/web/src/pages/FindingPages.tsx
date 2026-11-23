import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { compact, count, toNum } from "../lib/format";
import { CATEGORY, STATUS } from "../lib/labels";
import type { Dashboard } from "../lib/types";
import { FindingsExplorer } from "../components/findings/FindingsExplorer";
import { SERIES } from "../components/charts/charts";
import { Disclaimer, Kpi, PageHeader, Panel } from "../components/ui";

function useDash() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/dashboard") }).data;
}

export function Intelligence() {
  const d = useDash();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Tax Intelligence" title="Todas as ocorrências"
        description="Inconsistências, classificações potencialmente incorretas, padrões anormais e impactos da Reforma Tributária — cada uma com regra, versão, evidência e confiança." />
      {d && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          {Object.keys(CATEGORY).map((c) => {
            const row = d.by_category.find((x) => x.category === c);
            return <Kpi key={c} label={CATEGORY[c]} value={count(row?.count ?? 0)} sub={toNum(row?.amount) > 0 ? compact(row!.amount) : "sem valor monetário"} />;
          })}
        </div>
      )}
      <Panel padded={false}><FindingsExplorer /></Panel>
    </div>
  );
}

export function Credits() {
  const d = useDash();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Credit Recovery" title="Oportunidades de recuperação de créditos"
        description="Créditos potencialmente não aproveitados, rastreados até o documento de origem. Fluxo: analista analisa e propõe → diretor tributário aprova (segregação de funções)." />
      {d && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {d.credit_pipeline.map((p) => (
            <Kpi key={p.status} label={STATUS[p.status]} value={compact(p.amount)} sub={`${p.count} ocorrência(s)`}
                 accent={p.status === "VALIDATED" ? SERIES.recoverable : undefined} />
          ))}
        </div>
      )}
      <Disclaimer>
        Valores são <strong className="text-fg-2">estimativas</strong> calculadas a partir dos próprios documentos (imposto destacado × escriturado, ou base × alíquota legal vigente na data do documento).
        Elegibilidade depende de fatos não presentes nos dados (destinação, essencialidade do insumo, exceções). Aprovação gera uma conclusão documentada — o aproveitamento é decisão da empresa.
      </Disclaimer>
      <Panel padded={false}><FindingsExplorer preset={{ amount_type: "RECOVERABLE_ESTIMATE" }} /></Panel>
    </div>
  );
}

export function Risk() {
  const d = useDash();
  const k = d?.kpis;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Tax Risk" title="Riscos de conformidade"
        description="Créditos possivelmente indevidos, débitos não apurados, documentos sem lastro e inconsistências classificadas por criticidade." />
      {k && d && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Kpi label="Exposição estimada" value={compact(k.exposure_estimate)} accent={SERIES.exposure} sub={`Ponderada: ${compact(k.exposure_weighted)}`} />
          <Kpi label="Críticas sem tratamento" value={String(k.critical_open)} />
          <Kpi label="Altas pendentes" value={String(d.by_severity.HIGH ?? 0)} />
          <Kpi label="Aguardando aprovação" value={String(k.pending_approval)} />
        </div>
      )}
      <Panel padded={false}>
        <FindingsExplorer preset={{ category: "COMPLIANCE_RISK,RECONCILIATION,CLASSIFICATION,DATA_QUALITY,TAX_REFORM,ANOMALY" }} initialSort="severity" />
      </Panel>
    </div>
  );
}
