const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
const brl0 = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("pt-BR");

export const toNum = (v: string | number | null | undefined) => (v == null ? 0 : typeof v === "number" ? v : Number(v));
export const money = (v: string | number | null | undefined) => brl.format(toNum(v));
export const money0 = (v: string | number | null | undefined) => brl0.format(toNum(v));
export const count = (v: number) => int.format(v);
export function compact(v: string | number): string {
  const n = toNum(v);
  const a = Math.abs(n);
  if (a >= 1e9) return `R$ ${(n / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} bi`;
  if (a >= 1e6) return `R$ ${(n / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} mi`;
  if (a >= 1e3) return `R$ ${(n / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil`;
  return money0(n);
}
export const pct = (v: number) => `${Math.round(v * 100)}%`;
export function period(p: string | null | undefined) {
  if (!p) return "—";
  const [y, m] = p.split("-");
  const names = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  return `${names[Number(m) - 1]}/${y.slice(2)}`;
}
export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
export const cnpj = (v: string | null | undefined) =>
  v && v.length === 14 ? `${v.slice(0, 2)}.${v.slice(2, 5)}.${v.slice(5, 8)}/${v.slice(8, 12)}-${v.slice(12)}` : v ?? "—";
export const shortKey = (k: string | null | undefined) => (k ? `${k.slice(0, 4)}…${k.slice(-8)}` : "—");
export const bytes = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(0)} KB`);
