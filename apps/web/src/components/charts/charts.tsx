import { useEffect, useRef, useState, type ReactNode } from "react";
import { compact, money, period as fmtPeriod, toNum } from "../../lib/format";

/* Palette validated (dataviz validator, dark, surface #0f1726): slots 1–3, all pairs pass. */
export const SERIES = { recoverable: "#199e70", exposure: "#d95926", divergence: "#3987e5" } as const;

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceMax(v: number) {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / exp;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return step * exp;
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-fg-2">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} aria-hidden />
          {i.label}
        </span>
      ))}
    </div>
  );
}

function Tooltip({ x, y, children, containerW }: { x: number; y: number; children: ReactNode; containerW: number }) {
  const left = Math.min(Math.max(x, 90), containerW - 90);
  return (
    <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-ink-500 bg-ink-850/95 px-3 py-2 text-xs shadow-xl backdrop-blur"
         style={{ left, top: y - 8 }}>
      {children}
    </div>
  );
}

export interface PeriodDatum { period: string; [k: string]: string | number }

/** Grouped vertical bars over time. One y-axis; series share a unit (R$). */
export function GroupedBars({ data, series, height = 240 }: {
  data: PeriodDatum[]; series: { key: string; label: string; color: string }[]; height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { l: 92, r: 8, t: 12, b: 26 };
  const iw = width - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => toNum(d[s.key] as string)))));
  const band = iw / Math.max(1, data.length);
  const gap = 2;
  const groupW = Math.min(band * 0.7, 18 * series.length + gap * (series.length - 1));
  const barW = (groupW - gap * (series.length - 1)) / series.length;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const y = (v: number) => pad.t + ih - (v / max) * ih;

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label={`Gráfico por período: ${series.map((s) => s.label).join(", ")}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="#1a2538" strokeDasharray={t === 0 ? undefined : "2 4"} />
            <text x={pad.l - 8} y={y(t)} dy="0.32em" textAnchor="end" className="num" fontSize={10.5} fill="#76839a">{compact(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const gx = pad.l + band * i + (band - groupW) / 2;
          return (
            <g key={d.period}>
              {hover === i && <rect x={pad.l + band * i} y={pad.t} width={band} height={ih} fill="#ffffff" opacity={0.03} />}
              {series.map((s, j) => {
                const v = toNum(d[s.key] as string);
                const h = Math.max(0, (v / max) * ih);
                const x = gx + j * (barW + gap);
                const r = Math.min(4, barW / 2, h);
                return v > 0 ? (
                  <path key={s.key} fill={s.color}
                        d={`M${x},${y(0)} V${y(0) - h + r} Q${x},${y(0) - h} ${x + r},${y(0) - h} H${x + barW - r} Q${x + barW},${y(0) - h} ${x + barW},${y(0) - h + r} V${y(0)} Z`} />
                ) : null;
              })}
              <text x={pad.l + band * i + band / 2} y={height - 8} textAnchor="middle" fontSize={10.5} fill="#76839a">{fmtPeriod(d.period)}</text>
              <rect x={pad.l + band * i} y={pad.t} width={band} height={ih + pad.b} fill="transparent"
                    onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            </g>
          );
        })}
      </svg>
      {hover !== null && data[hover] && (
        <Tooltip x={pad.l + band * hover + band / 2} y={pad.t + 10} containerW={width}>
          <div className="mb-1 font-medium text-fg">{fmtPeriod(data[hover].period)}</div>
          {series.map((s) => (
            <div key={s.key} className="flex items-center justify-between gap-6">
              <span className="inline-flex items-center gap-1.5 text-fg-2"><span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.label}</span>
              <span className="num text-fg">{money(data[hover][s.key] as string)}</span>
            </div>
          ))}
        </Tooltip>
      )}
    </div>
  );
}

/** Horizontal paired bars by category (e.g. tax). Labels and values are text, not color. */
export function PairedHBars({ rows, series }: {
  rows: { label: string; values: Record<string, string | number> }[]; series: { key: string; label: string; color: string }[];
}) {
  const max = Math.max(1, ...rows.flatMap((r) => series.map((s) => toNum(r.values[s.key]))));
  return (
    <div className="space-y-3.5">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="mb-1.5 text-xs font-medium text-fg">{r.label}</div>
          <div className="space-y-[2px]">
            {series.map((s) => {
              const v = toNum(r.values[s.key]);
              return (
                <div key={s.key} className="group flex items-center gap-2" title={`${s.label}: ${money(v)}`}>
                  <div className="h-2.5 flex-1">
                    <div className="h-full rounded-r-[4px] transition-opacity group-hover:opacity-80"
                         style={{ width: `${Math.max(v > 0 ? 0.8 : 0, (v / max) * 100)}%`, background: s.color }} />
                  </div>
                  <span className="num w-24 shrink-0 text-right text-xs text-fg-2">{v > 0 ? compact(v) : "—"}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Segmented bar for status-coded counts. Status colors carry icon+label in the legend below. */
export function SegmentBar({ segments }: { segments: { label: string; value: number; color: string }[] }) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  return (
    <div>
      <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded" role="img"
           aria-label={segments.map((s) => `${s.label}: ${s.value}`).join(", ")}>
        {segments.filter((s) => s.value > 0).map((s) => (
          <div key={s.label} title={`${s.label}: ${s.value}`} style={{ width: `${(s.value / total) * 100}%`, background: s.color }} />
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-5">
        {segments.map((s) => (
          <div key={s.label} className="flex items-center justify-between gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 text-fg-2"><span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.label}</span>
            <span className="num text-fg">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Spark-style mini bars for history (single series, no legend needed). */
export function MiniBars({ values, color = "#3987e5", height = 32 }: { values: number[]; color?: string; height?: number }) {
  const max = Math.max(1, ...values);
  return (
    <div className="flex items-end gap-[2px]" style={{ height }} aria-hidden>
      {values.map((v, i) => (
        <div key={i} className="w-1.5 rounded-t-[2px]" style={{ height: `${Math.max(4, (v / max) * 100)}%`, background: color, opacity: i === values.length - 1 ? 1 : 0.55 }} />
      ))}
    </div>
  );
}
