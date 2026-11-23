import { StrictMode, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./index.css";
import { ApiError } from "./lib/api";
import { SessionProvider } from "./lib/session";
import { Shell } from "./components/layout/Shell";
import { Empty, Panel } from "./components/ui";
import { Dashboard } from "./pages/Dashboard";
import { Ingestion } from "./pages/Ingestion";
import { Reconciliation } from "./pages/Reconciliation";
import { Credits, Intelligence, Risk } from "./pages/FindingPages";
import { Audit, Roadmap, Rules, Settings } from "./pages/Governance";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (n, err) => !(err instanceof ApiError && [401, 402, 403, 404].includes(err.status)) && n < 2,
    },
  },
});

function NotContracted() {
  return <Panel><Empty title="Página não encontrada" /></Panel>;
}

function App() {
  const reset = useCallback(() => queryClient.clear(), []);
  return (
    <QueryClientProvider client={queryClient}>
    <SessionProvider onChange={reset}>
      <BrowserRouter>
        <Shell>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/ingestion" element={<Ingestion />} />
            <Route path="/reconciliation" element={<Reconciliation />} />
            <Route path="/intelligence" element={<Intelligence />} />
            <Route path="/credits" element={<Credits />} />
            <Route path="/risk" element={<Risk />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/roadmap/:module" element={<Roadmap />} />
            <Route path="*" element={<NotContracted />} />
          </Routes>
        </Shell>
      </BrowserRouter>
    </SessionProvider>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
