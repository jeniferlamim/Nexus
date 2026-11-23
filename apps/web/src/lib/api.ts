import { getIdentity } from "./session";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function headers(extra?: HeadersInit): HeadersInit {
  const id = getIdentity();
  return { "X-Nexus-User": id.userId, "X-Nexus-Tenant": id.tenantId, ...(extra ?? {}) };
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not json */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => fetch(`/api${path}`, { headers: headers() }).then((r) => handle<T>(r)),
  post: <T,>(path: string, body?: unknown) =>
    fetch(`/api${path}`, { method: "POST", headers: headers({ "Content-Type": "application/json" }), body: body ? JSON.stringify(body) : undefined })
      .then((r) => handle<T>(r)),
  upload: <T,>(path: string, form: FormData) => fetch(`/api${path}`, { method: "POST", headers: headers(), body: form }).then((r) => handle<T>(r)),
  download: async (path: string, filename: string) => {
    const res = await fetch(`/api${path}`, { headers: headers() });
    if (!res.ok) throw new ApiError(res.status, "Falha ao exportar");
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    a.click();
    URL.revokeObjectURL(url);
  },
};
