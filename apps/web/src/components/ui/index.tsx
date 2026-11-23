import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, Circle, Info, Loader2, ShieldAlert } from "lucide-react";
import { AMOUNT, KIND, SEVERITY, STATUS } from "../../lib/labels";
import type { AmountType, FindingStatus, Kind, Severity } from "../../lib/types";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Panel({ title, subtitle, actions, children, className, padded = true }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean;
}) {
  return (
    <section className={cx("rounded-lg border border-ink-600 bg-ink-750 shadow-panel", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-ink-600/70 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold tracking-tight text-fg">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-fg-3">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function Button({ variant = "secondary", size = "md", className, loading, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; loading?: boolean;
}) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]",
        variant === "primary" && "bg-accent text-accent-ink hover:bg-[#46e0aa]",
        variant === "secondary" && "border border-ink-500 bg-ink-700 text-fg hover:border-ink-400 hover:bg-ink-600",
        variant === "ghost" && "text-fg-2 hover:bg-ink-700 hover:text-fg",
        variant === "danger" && "border border-status-critical/50 bg-status-critical/10 text-[#f19a9a] hover:bg-status-critical/20",
        className,
      )}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

const SEV_STYLE: Record<Severity, { cls: string; Icon: typeof Info }> = {
  CRITICAL: { cls: "text-[#f08a8a] bg-status-critical/12 ring-status-critical/40", Icon: AlertOctagon },
  HIGH: { cls: "text-status-serious bg-status-serious/10 ring-status-serious/35", Icon: ShieldAlert },
  MEDIUM: { cls: "text-status-warning bg-status-warning/10 ring-status-warning/30", Icon: AlertTriangle },
  LOW: { cls: "text-fg-2 bg-ink-600/60 ring-ink-500", Icon: Circle },
  INFO: { cls: "text-fg-3 bg-ink-700 ring-ink-500", Icon: Info },
};

export function SeverityBadge({ severity, compact }: { severity: Severity; compact?: boolean }) {
  const { cls, Icon } = SEV_STYLE[severity];
  return (
    <span className={cx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide ring-1 ring-inset", cls)}>
      <Icon className="h-3 w-3" aria-hidden />
      {!compact && SEVERITY[severity]}
      {compact && <span className="sr-only">{SEVERITY[severity]}</span>}
    </span>
  );
}

const STATUS_CLS: Record<FindingStatus, string> = {
  OPEN: "text-fg-2 ring-ink-500",
  IN_REVIEW: "text-[#8fb8f0] ring-[#3987e5]/40",
  PENDING_APPROVAL: "text-status-warning ring-status-warning/35",
  VALIDATED: "text-accent ring-accent/40",
  DISMISSED: "text-fg-4 ring-ink-500 line-through decoration-fg-4/60",
};

export function StatusBadge({ status }: { status: FindingStatus }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-medium ring-1 ring-inset", STATUS_CLS[status])}>
      {status === "VALIDATED" && <CheckCircle2 className="h-3 w-3" aria-hidden />}
      {STATUS[status]}
    </span>
  );
}

export function KindTag({ kind }: { kind: Kind }) {
  return (
    <span className={cx("rounded px-1.5 py-0.5 text-2xs font-medium",
      kind === "ESTIMATE" && "bg-series-rec/10 text-[#5fd3a8]",
      kind === "ALERT" && "bg-ink-600 text-fg-2",
      kind === "VALIDATED" && "bg-accent/15 text-accent")}>
      {KIND[kind]}
    </span>
  );
}

export const AMOUNT_COLOR: Record<AmountType, string> = {
  RECOVERABLE_ESTIMATE: "#199e70", EXPOSURE_ESTIMATE: "#d95926", DIVERGENCE_VALUE: "#3987e5", NONE: "#525e73",
};

export function AmountTypeDot({ type, label = true }: { type: AmountType; label?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-fg-2">
      <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: AMOUNT_COLOR[type] }} aria-hidden />
      {label && AMOUNT[type]}
    </span>
  );
}

export function Confidence({ value, label }: { value: number; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2" title={`Confiança ${Math.round(value * 100)}%`}>
      <span className="relative h-1.5 w-12 overflow-hidden rounded-full bg-ink-600" aria-hidden>
        <span className="absolute inset-y-0 left-0 rounded-full bg-fg-2" style={{ width: `${value * 100}%` }} />
      </span>
      <span className="num text-xs text-fg-2">{Math.round(value * 100)}%</span>
      {label && <span className="text-2xs text-fg-3">{label}</span>}
    </span>
  );
}

export function Kpi({ label, value, sub, accent, hint }: { label: string; value: ReactNode; sub?: ReactNode; accent?: string; hint?: string }) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-ink-600 bg-ink-750 px-4 py-3.5 shadow-panel" title={hint}>
      {accent && <span className="absolute inset-x-0 top-0 h-px" style={{ background: `linear-gradient(90deg, ${accent}, transparent 70%)` }} />}
      <div className="label flex items-center gap-1.5">
        {accent && <span className="h-2 w-2 rounded-sm" style={{ background: accent }} aria-hidden />}
        {label}
      </div>
      <div className="num mt-2 text-[22px] font-medium leading-none text-fg">{value}</div>
      {sub && <div className="mt-2 text-xs text-fg-3">{sub}</div>}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon}
      <p className="text-sm font-medium text-fg">{title}</p>
      {children && <div className="max-w-md text-xs text-fg-3">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Carregando" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-10 text-xs text-fg-3">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}…
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="rounded-md border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-xs text-[#f3a5a5]">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-ink-600 bg-ink-800 px-3 py-2 text-xs text-fg-3">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function Select({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string;
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-md border border-ink-500 bg-ink-800 px-2 pr-7 text-xs text-fg outline-none hover:border-ink-400 focus:border-accent"
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="label text-accent/80">{eyebrow}</div>
        <h1 className="mt-1 text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-[13px] text-fg-3">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
