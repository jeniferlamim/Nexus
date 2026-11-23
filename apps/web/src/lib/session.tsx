import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

/**
 * Dev-mode identity: the selected persona is sent as X-Nexus-User / X-Nexus-Tenant.
 * In production (AUTH_MODE=supabase) this is replaced by the Supabase session JWT; the
 * tenant header remains, and the API checks it against the user's memberships.
 */
export interface Identity { userId: string; tenantId: string }

const DEFAULT: Identity = { userId: "11111111-1111-4111-8111-111111111111", tenantId: "7a1f3c52-0d4e-4b8a-9a61-2f0c5e9b1a01" };
const KEY = "nexus.identity";

function load(): Identity {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Identity;
  } catch { /* storage unavailable */ }
  return DEFAULT;
}

let current = load();
export const getIdentity = () => current;

const Ctx = createContext<{ identity: Identity; setIdentity: (i: Identity) => void }>({ identity: current, setIdentity: () => {} });

export function SessionProvider({ children, onChange }: { children: ReactNode; onChange: () => void }) {
  const [identity, setState] = useState(current);
  const setIdentity = useCallback((i: Identity) => {
    current = i;
    try { localStorage.setItem(KEY, JSON.stringify(i)); } catch { /* ignore */ }
    setState(i);
    onChange();
  }, [onChange]);
  return <Ctx.Provider value={{ identity, setIdentity }}>{children}</Ctx.Provider>;
}

export const useSession = () => useContext(Ctx);
