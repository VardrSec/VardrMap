"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiEndpoint } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel } from "./ui";

const methodColor: Record<string, string> = {
  GET: "#4ade80", POST: "#89b4fa", PUT: "#f59e0b", PATCH: "#c084fc", DELETE: "#f87171",
};

export default function ApiSurfaceSection({ engagementId }: { engagementId: string }) {
  const { authFetch, setMessage } = useAppContext();
  const [endpoints, setEndpoints] = useState<ApiEndpoint[]>([]);
  const [selected, setSelected] = useState<ApiEndpoint | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [method, setMethod] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (method) params.set("method", method);
      const res = await authFetch(`/engagements/${engagementId}/api/endpoints?${params}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setEndpoints(data.endpoints ?? []);
    } catch { setMessage("Failed to load API surface."); } finally { setLoading(false); }
  }, [authFetch, engagementId, method, search, setMessage]);

  useEffect(() => { const timer = setTimeout(() => void load(), 180); return () => clearTimeout(timer); }, [load]);

  async function inspect(endpoint: ApiEndpoint) {
    try {
      const res = await authFetch(`/engagements/${engagementId}/api/endpoints/${endpoint.id}`);
      if (!res.ok) throw new Error();
      setSelected(await res.json());
    } catch { setMessage("Failed to load captured exchanges."); }
  }

  const stats = useMemo(() => ({
    exchanges: endpoints.reduce((sum, item) => sum + item.observation_count, 0),
    identities: new Set(endpoints.flatMap((item) => item.identities)).size,
    hosts: new Set(endpoints.map((item) => item.host)).size,
  }), [endpoints]);

  return <div className="space-y-5">
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {[["Operations", endpoints.length], ["Exchanges", stats.exchanges], ["Hosts", stats.hosts], ["Identity labels", stats.identities]].map(([label, value]) =>
        <div key={label} className="rounded-lg border border-[#2e2e2e] bg-[#171717] p-4">
          <div className="font-mono text-2xl text-[#f1f5f9]">{value}</div>
          <div className="mt-1 text-[10px] uppercase tracking-widest text-[#52525b]">{label}</div>
        </div>)}
    </div>

    <Panel title="Observed API operations">
      <div className="mb-4 flex flex-wrap gap-2">
        <input aria-label="Search API operations" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search host or route…"
          className="min-w-64 flex-1 rounded border border-[#2e2e2e] bg-[#111] px-3 py-2 text-xs text-[#f1f5f9] outline-none focus:border-[#52525b]" />
        <select aria-label="Filter by method" value={method} onChange={(e) => setMethod(e.target.value)}
          className="rounded border border-[#2e2e2e] bg-[#111] px-3 py-2 text-xs text-[#94a3b8]">
          <option value="">All methods</option>
          {["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"].map((item) => <option key={item}>{item}</option>)}
        </select>
      </div>
      {loading && <p className="py-8 text-center text-sm text-[#52525b]">Loading API map…</p>}
      {!loading && endpoints.length === 0 && <div className="py-10 text-center">
        <p className="text-sm text-[#94a3b8]">No API exchanges promoted yet.</p>
        <p className="mt-1 text-xs text-[#52525b]">In Burp, select a request or response and choose “Send to VardrMap”. Automatic capture stays off.</p>
      </div>}
      {!loading && endpoints.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-xs">
        <thead><tr className="border-b border-[#2e2e2e]">{["Method", "Operation", "Responses", "Identities", "Seen", ""].map((h) => <th key={h} className="pb-2 pr-4 font-semibold uppercase tracking-widest text-[#52525b]">{h}</th>)}</tr></thead>
        <tbody>{endpoints.map((item) => <tr key={item.id} className="border-b border-[#1e1e1e] hover:bg-[#161616]">
          <td className="py-2.5 pr-4 font-mono font-bold" style={{ color: methodColor[item.method] ?? "#94a3b8" }}>{item.method}</td>
          <td className="py-2.5 pr-4"><div className="font-mono text-[#f1f5f9]">{item.path_template}</div><div className="mt-0.5 text-[10px] text-[#52525b]">{item.host}</div></td>
          <td className="py-2.5 pr-4 font-mono text-[#94a3b8]">{item.statuses.join(" · ") || "—"}</td>
          <td className="py-2.5 pr-4 text-[#94a3b8]">{item.identities.join(", ") || "—"}</td>
          <td className="py-2.5 pr-4 font-mono text-[#52525b]">{item.observation_count}</td>
          <td className="py-2.5 text-right"><button onClick={() => void inspect(item)} className="rounded px-2 py-1 text-[10px] text-[#89b4fa] hover:bg-[#2e2e2e]">Inspect</button></td>
        </tr>)}</tbody>
      </table></div>}
    </Panel>

    {selected && <Panel title={`${selected.method} ${selected.path_template}`}>
      <div className="mb-3 flex flex-wrap gap-2">{selected.identities.map((identity) => <span key={identity} className="rounded bg-[#242424] px-2 py-1 font-mono text-[10px] text-[#c084fc]">{identity}</span>)}</div>
      <div className="space-y-2">{selected.exchanges?.map((exchange) => <details key={exchange.id} className="rounded border border-[#2e2e2e] bg-[#111] p-3">
        <summary className="cursor-pointer font-mono text-xs text-[#94a3b8]">
          <span className="mr-3 text-[#f1f5f9]">{exchange.response_status ?? "—"}</span>{exchange.identity_label}<span className="ml-3 text-[#52525b]">{exchange.source_tool} · {exchange.response_time_ms ?? "—"} ms</span>
        </summary>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <Message title="Request" headers={exchange.request_headers} body={exchange.request_body} />
          <Message title="Response" headers={exchange.response_headers} body={exchange.response_body} />
        </div>
      </details>)}</div>
    </Panel>}
  </div>;
}

function Message({ title, headers, body }: { title: string; headers: string; body: string }) {
  return <div><div className="mb-1 text-[10px] uppercase tracking-widest text-[#52525b]">{title} · redacted</div>
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded bg-[#0a0a0a] p-3 font-mono text-[10px] leading-relaxed text-[#94a3b8]">{[headers, body].filter(Boolean).join("\n\n") || "No retained content"}</pre></div>;
}
