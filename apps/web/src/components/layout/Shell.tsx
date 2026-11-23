import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, BookOpenCheck, Bot, Building2, ChevronDown, Coins, FileSearch, GitCompareArrows, LayoutDashboard, Lock, Menu,
  ScrollText, ShieldAlert, SlidersHorizontal, Truck, UploadCloud, X, Calculator,
} from "lucide-react";
import { api } from "../../lib/api";
import { useSession } from "../../lib/session";
import type { Me, Persona } from "../../lib/types";
import { cx } from "../ui";

interface NavItem { to: string; label: string; icon: typeof Activity; module: string; roadmap?: boolean }
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Executivo", items: [{ to: "/", label: "Executive Dashboard", icon: LayoutDashboard, module: "executive_dashboard" }] },
  { group: "Dados", items: [{ to: "/ingestion", label: "Ingestão de dados", icon: UploadCloud, module: "ingestion" }] },
  {
    group: "Inteligência", items: [
      { to: "/reconciliation", label: "Tax Reconciliation", icon: GitCompareArrows, module: "tax_reconciliation" },
      { to: "/intelligence", label: "Tax Intelligence", icon: FileSearch, module: "tax_intelligence" },
      { to: "/credits", label: "Credit Recovery", icon: Coins, module: "credit_recovery" },
      { to: "/risk", label: "Tax Risk", icon: ShieldAlert, module: "tax_risk" },
    ],
  },
  {
    group: "Governança", items: [
      { to: "/rules", label: "Regras fiscais", icon: BookOpenCheck, module: "tax_intelligence" },
      { to: "/audit", label: "Audit Trail", icon: ScrollText, module: "audit_trail" },
      { to: "/settings", label: "Empresa e plano", icon: SlidersHorizontal, module: "executive_dashboard" },
    ],
  },
  {
    group: "Próximas fases", items: [
      { to: "/roadmap/tax_simulator", label: "Tax Simulator", icon: Calculator, module: "tax_simulator", roadmap: true },
      { to: "/roadmap/supplier_intelligence", label: "Supplier Intelligence", icon: Truck, module: "supplier_intelligence", roadmap: true },
      { to: "/roadmap/financial_intelligence", label: "Financial Intelligence", icon: Activity, module: "financial_intelligence", roadmap: true },
      { to: "/roadmap/ai_copilot", label: "AI Copilot", icon: Bot, module: "ai_copilot", roadmap: true },
    ],
  },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#0f1a2e" stroke="#243149" />
        <path d="M9 23V9l14 14V9" fill="none" stroke="#2ed39a" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-[13px] font-semibold tracking-[0.18em] text-fg">NEXUS</div>
        <div className="text-[9.5px] uppercase tracking-[0.14em] text-fg-3">Enterprise Tax Intelligence</div>
      </div>
    </div>
  );
}

function Sidebar({ me, onNavigate }: { me?: Me; onNavigate?: () => void }) {
  const modules = new Set(me?.plan.modules ?? []);
  return (
    <nav className="flex h-full flex-col" aria-label="Módulos">
      <div className="px-4 pb-4 pt-4"><Logo /></div>
      <div className="flex-1 space-y-5 overflow-y-auto px-2.5 pb-4">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="label px-2 pb-1.5 text-fg-4">{g.group}</div>
            <ul className="space-y-0.5">
              {g.items.map((it) => {
                const locked = !it.roadmap && me && !modules.has(it.module);
                return (
                  <li key={it.to}>
                    <NavLink
                      to={it.to}
                      end={it.to === "/"}
                      onClick={onNavigate}
                      className={({ isActive }) => cx(
                        "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors",
                        isActive ? "bg-ink-600/80 text-fg shadow-[inset_2px_0_0_#2ed39a]" : "text-fg-2 hover:bg-ink-700 hover:text-fg",
                        (it.roadmap || locked) && "text-fg-3",
                      )}
                    >
                      <it.icon className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
                      <span className="flex-1 truncate">{it.label}</span>
                      {it.roadmap && <span className="rounded bg-ink-700 px-1 text-[9.5px] uppercase tracking-wide text-fg-4">Fase 2</span>}
                      {locked && <Lock className="h-3 w-3 text-fg-4" aria-label="Não contratado" />}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-ink-600 px-4 py-3 text-2xs text-fg-4">
        <div className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-accent" /> Motor determinístico · regras versionadas</div>
        <div className="mt-1">Nenhuma compensação é executada automaticamente.</div>
      </div>
    </nav>
  );
}

function PersonaSwitcher({ me }: { me?: Me }) {
  const { identity, setIdentity } = useSession();
  const [open, setOpen] = useState(false);
  const { data: personas } = useQuery({ queryKey: ["personas"], queryFn: () => api.get<Persona[]>("/demo/users"), staleTime: Infinity, retry: false });
  const tenants = Array.from(new Map((personas ?? []).map((p) => [p.tenant_id, p.tenant_name])).entries());
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
              className="flex items-center gap-2.5 rounded-md border border-ink-600 bg-ink-800 py-1 pl-1.5 pr-2 text-left hover:border-ink-500">
        <span className="flex h-7 w-7 items-center justify-center rounded bg-navy text-[11px] font-semibold text-fg">
          {me?.user.name.split(" ").map((n) => n[0]).slice(0, 2).join("") ?? "··"}
        </span>
        <span className="hidden leading-tight sm:block">
          <span className="block text-xs font-medium text-fg">{me?.user.name ?? "…"}</span>
          <span className="block text-2xs text-fg-3">{me?.role_label ?? ""}</span>
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-fg-3" />
      </button>
      {open && personas && (
        <div className="absolute right-0 z-30 mt-1.5 w-80 rounded-lg border border-ink-500 bg-ink-800 p-1.5 shadow-2xl">
          <div className="label px-2 pb-1 pt-1">Ambiente de demonstração · trocar perfil</div>
          {tenants.map(([tid, tname]) => (
            <div key={tid} className="py-1">
              <div className="flex items-center gap-1.5 px-2 py-1 text-2xs text-fg-3"><Building2 className="h-3 w-3" />{tname}</div>
              {personas.filter((p) => p.tenant_id === tid).map((p) => {
                const active = p.user_id === identity.userId && p.tenant_id === identity.tenantId;
                return (
                  <button key={p.user_id + tid}
                          onClick={() => { setIdentity({ userId: p.user_id, tenantId: p.tenant_id }); setOpen(false); }}
                          className={cx("flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-ink-700", active && "bg-ink-700")}>
                    <span><span className="text-fg">{p.name}</span> <span className="text-fg-3">· {p.title}</span></span>
                    <span className="text-2xs text-fg-3">{p.role_label}</span>
                  </button>
                );
              })}
            </div>
          ))}
          <div className="border-t border-ink-600 px-2 pt-1.5 text-2xs text-fg-4">Em produção, a identidade vem do SSO (Supabase Auth); a troca de perfil só existe no modo demo.</div>
        </div>
      )}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-ink-600 bg-ink-850 lg:block"><Sidebar me={me} /></aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-ink-600 bg-ink-850">
            <button className="absolute right-2 top-3 p-1 text-fg-3" onClick={() => setMobileOpen(false)} aria-label="Fechar menu"><X className="h-4 w-4" /></button>
            <Sidebar me={me} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-ink-600 bg-ink-900/80 px-4 backdrop-blur">
          <div className="flex min-w-0 items-center gap-3">
            <button className="rounded p-1 text-fg-2 hover:bg-ink-700 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Abrir menu"><Menu className="h-5 w-5" /></button>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-[13px] font-semibold text-fg">{me?.tenant.legal_name ?? "…"}</span>
                {me && <span className="hidden rounded border border-ink-500 px-1.5 py-px text-2xs text-fg-3 sm:inline">Plano {me.plan.name}</span>}
              </div>
              <div className="hidden truncate text-2xs text-fg-3 sm:block">{me?.tenant.segment} · Raiz CNPJ {me?.tenant.cnpj_roots.join(", ")} · PIS/COFINS {me?.tenant.tax_regime === "NON_CUMULATIVE" ? "não cumulativo" : "cumulativo"}</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 text-2xs text-fg-3 md:flex" key={location.pathname}>
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" /> Isolamento por tenant ativo
            </span>
            <PersonaSwitcher me={me} />
          </div>
        </header>
        <main className="grid-bg min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
