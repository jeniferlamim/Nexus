import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, FileSpreadsheet, FileCode2, Landmark, Loader2, Minus, UploadCloud, X } from "lucide-react";
import { api } from "../lib/api";
import { bytes, count, dateTime, period } from "../lib/format";
import { SOURCE } from "../lib/labels";
import type { Batch, Me } from "../lib/types";
import { Button, Disclaimer, Empty, ErrorBox, Loading, PageHeader, Panel, cx } from "../components/ui";
import { DemoLoader } from "./Dashboard";

const SOURCES = [
  { type: "NFE_XML", icon: FileCode2, title: "NF-e", formats: ".xml ou .zip", accept: ".xml,.zip", desc: "XMLs de entrada e saída (layout 4.00, inclusive grupo IBS/CBS)" },
  { type: "FISCAL_BOOK", icon: FileSpreadsheet, title: "Escrituração fiscal", formats: ".csv ou .xlsx", accept: ".csv,.txt,.xlsx", desc: "Livro de entradas/saídas por item (export do ERP / EFD)" },
  { type: "LEDGER", icon: Landmark, title: "Razão contábil", formats: ".csv ou .xlsx", accept: ".csv,.txt,.xlsx", desc: "Lançamentos das contas de tributos a recuperar" },
] as const;

function StageTrack({ b }: { b: Batch }) {
  return (
    <ol className="grid grid-cols-4 gap-1 sm:grid-cols-8">
      {b.stages.map((s) => (
        <li key={s.stage} title={`${s.label}${s.detail ? ` — ${s.detail}` : ""}`}>
          <div className={cx("h-1 rounded-full",
            s.status === "DONE" && "bg-accent", s.status === "FAILED" && "bg-status-critical",
            s.status === "SKIPPED" && "bg-ink-500", s.status === "PENDING" && (b.status === "RUNNING" || b.status === "QUEUED" ? "animate-pulse bg-ink-500" : "bg-ink-600"))} />
          <div className="mt-1 flex items-center gap-1 text-2xs text-fg-3">
            {s.status === "DONE" && <Check className="h-3 w-3 text-accent" />}
            {s.status === "FAILED" && <X className="h-3 w-3 text-status-critical" />}
            {s.status === "SKIPPED" && <Minus className="h-3 w-3" />}
            <span className="truncate">{s.label}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function BatchStatus({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    QUEUED: ["Na fila", "text-fg-3"], RUNNING: ["Processando", "text-[#8fb8f0]"], COMPLETED: ["Concluído", "text-accent"],
    COMPLETED_WITH_WARNINGS: ["Concluído com avisos", "text-status-warning"], FAILED: ["Falhou", "text-[#f08a8a]"],
  };
  const [label, cls] = map[status] ?? [status, "text-fg-2"];
  return <span className={cx("inline-flex items-center gap-1 text-xs font-medium", cls)}>{status === "RUNNING" && <Loader2 className="h-3 w-3 animate-spin" />}{label}</span>;
}

function BatchDetail({ id }: { id: string }) {
  const { data } = useQuery({ queryKey: ["batch", id], queryFn: () => api.get<Batch>(`/ingestion/batches/${id}`) });
  if (!data) return <Loading />;
  return (
    <div className="space-y-3 bg-ink-850 px-4 py-4">
      <div className="grid gap-2 sm:grid-cols-2">
        {data.stages.map((s) => (
          <div key={s.stage} className="flex gap-2 text-xs">
            <span className={cx("mt-0.5 h-2 w-2 shrink-0 rounded-full", s.status === "DONE" ? "bg-accent" : s.status === "FAILED" ? "bg-status-critical" : "bg-ink-500")} />
            <div><span className="text-fg">{s.label}</span> <span className="text-fg-3">{s.detail}</span></div>
          </div>
        ))}
      </div>
      <div className="num text-2xs text-fg-4">SHA-256 {data.sha256} · o arquivo bruto não é armazenado (minimização de dados)</div>
      {data.errors && data.errors.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-ink-600">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="bg-ink-800 text-left text-fg-3"><tr>
              <th className="px-2.5 py-1.5 font-medium">Severidade</th><th className="px-2.5 py-1.5 font-medium">Arquivo / local</th>
              <th className="px-2.5 py-1.5 font-medium">Campo</th><th className="px-2.5 py-1.5 font-medium">Valor</th><th className="px-2.5 py-1.5 font-medium">Problema</th>
            </tr></thead>
            <tbody>
              {data.errors.slice(0, 100).map((e, i) => (
                <tr key={i} className="border-t border-ink-700">
                  <td className="px-2.5 py-1.5">{e.severity === "BLOCKING" ? <span className="text-[#f08a8a]">Bloqueante</span> : <span className="text-status-warning">Aviso</span>}</td>
                  <td className="max-w-[240px] truncate px-2.5 py-1.5 text-fg-3" title={e.source}>{e.source.split("/").pop()} · {e.locator}</td>
                  <td className="num px-2.5 py-1.5 text-fg-2">{e.field}</td>
                  <td className="num max-w-[160px] truncate px-2.5 py-1.5 text-fg-2">{e.value}</td>
                  <td className="px-2.5 py-1.5 text-fg">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.errors.length > 100 && <div className="px-2.5 py-1.5 text-2xs text-fg-3">+{data.errors.length - 100} registros</div>}
        </div>
      )}
    </div>
  );
}

export function Ingestion() {
  const qc = useQueryClient();
  const [source, setSource] = useState<(typeof SOURCES)[number]["type"]>("NFE_XML");
  const [drag, setDrag] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  const { data: batches, isLoading } = useQuery({
    queryKey: ["batches"], queryFn: () => api.get<Batch[]>("/ingestion/batches"),
    refetchInterval: (q) => ((q.state.data ?? []).some((b) => b.status === "RUNNING" || b.status === "QUEUED") ? 1000 : 10000),
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("source_type", source);
      fd.append("file", file);
      return api.upload<Batch>("/ingestion/upload", fd);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["batches"] }); setTimeout(() => qc.invalidateQueries(), 1500); },
  });
  const can = me?.permissions.includes("ingest");
  const cur = SOURCES.find((s) => s.type === source)!;
  const onFiles = (files: FileList | null) => { if (files?.[0]) upload.mutate(files[0]); };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Dados" title="Ingestão de dados"
        description="Upload → validação → identificação de erros → normalização → armazenamento → análise → detecção de divergências → relatórios. Cada estágio é rastreado por lote."
        actions={<DemoLoader compactMode />} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Novo lote">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Tipo de fonte">
            {SOURCES.map((s) => (
              <button key={s.type} role="radio" aria-checked={source === s.type} onClick={() => setSource(s.type)}
                      className={cx("rounded-md border px-3 py-2.5 text-left transition-colors", source === s.type ? "border-accent/60 bg-accent/5" : "border-ink-600 bg-ink-800 hover:border-ink-500")}>
                <div className="flex items-center gap-2 text-[13px] font-medium text-fg"><s.icon className="h-4 w-4 text-fg-2" />{s.title}<span className="text-2xs font-normal text-fg-3">{s.formats}</span></div>
                <div className="mt-1 text-2xs text-fg-3">{s.desc}</div>
              </button>
            ))}
          </div>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); if (can) onFiles(e.dataTransfer.files); }}
            className={cx("mt-3 flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-9 text-center transition-colors",
              drag ? "border-accent bg-accent/5" : "border-ink-500 bg-ink-800/50")}>
            <UploadCloud className="h-7 w-7 text-fg-3" />
            <p className="mt-2 text-[13px] text-fg">Arraste o arquivo de <strong>{cur.title}</strong> ou</p>
            <input ref={input} type="file" accept={cur.accept} className="hidden" onChange={(e) => { onFiles(e.target.files); e.target.value = ""; }} />
            <Button className="mt-2" size="sm" onClick={() => input.current?.click()} disabled={!can} loading={upload.isPending}>Selecionar arquivo</Button>
            <p className="mt-2 text-2xs text-fg-4">Limite do plano: {me?.plan.max_file_mb} MB por arquivo · {count(me?.plan.max_documents_month ?? 0)} documentos/mês</p>
            {!can && <p className="mt-1 text-2xs text-status-warning">Seu perfil ({me?.role_label}) não pode importar dados.</p>}
          </div>
          {upload.error && <div className="mt-3"><ErrorBox error={upload.error} /></div>}
          {upload.isSuccess && <p className="mt-2 text-xs text-accent">Lote recebido e enfileirado para processamento.</p>}
        </Panel>
        <Panel title="Regras de carga">
          <ul className="space-y-2.5 text-xs text-fg-2">
            <li><strong className="text-fg">Idempotência:</strong> arquivo idêntico (mesmo SHA-256) é recusado.</li>
            <li><strong className="text-fg">NF-e:</strong> chave existente é substituída pela nova versão do XML.</li>
            <li><strong className="text-fg">Escrituração e razão:</strong> substituem os lançamentos dos mesmos períodos.</li>
            <li><strong className="text-fg">Cobertura:</strong> cruzamentos de ausência só rodam em períodos presentes nas duas fontes.</li>
            <li><strong className="text-fg">LGPD:</strong> CPF de pessoa física é mascarado; o arquivo bruto não é retido.</li>
            <li><strong className="text-fg">Segurança:</strong> XML com entidades externas ou estruturas maliciosas é rejeitado.</li>
          </ul>
        </Panel>
      </div>

      <Panel title="Lotes processados" padded={false}>
        {isLoading && <Loading />}
        {batches && batches.length === 0 && <Empty title="Nenhum lote importado ainda" />}
        <ul>
          {batches?.map((b) => (
            <li key={b.id} className="border-b border-ink-700 last:border-0">
              <button className="w-full px-4 py-3 text-left hover:bg-ink-700/40" onClick={() => setOpen(open === b.id ? null : b.id)} aria-expanded={open === b.id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[13px] text-fg">{b.filename}</div>
                    <div className="text-2xs text-fg-3">{SOURCE[b.source_type]} · {bytes(b.size_bytes)} · {dateTime(b.created_at)}{b.periods.length > 0 && ` · ${period(b.periods[0])}–${period(b.periods[b.periods.length - 1])}`}</div>
                  </div>
                  <div className="flex items-center gap-5 text-xs">
                    <span className="text-fg-3"><span className="num text-fg">{count(b.records_valid)}</span>/{count(b.records_total)} válidos</span>
                    {b.records_rejected > 0 && <span className="text-[#f08a8a]">{b.records_rejected} rejeitados</span>}
                    {b.warnings > 0 && <span className="inline-flex items-center gap-1 text-status-warning"><AlertTriangle className="h-3 w-3" />{b.warnings} avisos</span>}
                    <BatchStatus status={b.status} />
                  </div>
                </div>
                <div className="mt-2.5"><StageTrack b={b} /></div>
                {b.error && <p className="mt-2 text-xs text-[#f08a8a]">{b.error}</p>}
              </button>
              {open === b.id && <BatchDetail id={b.id} />}
            </li>
          ))}
        </ul>
      </Panel>
      <Disclaimer>Em produção, conectores de ERP (SAP, TOTVS, Oracle) entregam os mesmos três tipos de fonte a este pipeline, via API e fila de processamento.</Disclaimer>
    </div>
  );
}
