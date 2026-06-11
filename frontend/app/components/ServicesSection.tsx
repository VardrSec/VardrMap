"use client";

import { useCallback, useEffect, useState } from "react";
import { Service } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, SectionHeader } from "./ui";

export default function ServicesSection({ programId, hideHeader }: { programId: string; hideHeader?: boolean }) {
  const { authFetch, setMessage, dispatch } = useAppContext();
  const [services, setServices] = useState<Service[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch(`/programs/${programId}/services`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setServices(data.services ?? []);
    } catch { setMessage("Failed to load services."); } finally { setLoading(false); }
  }, [programId, authFetch, setMessage]);

  useEffect(() => { void load(); }, [load]);

  async function handleDelete(id: string) {
    setDeleting(id);
    try {
      const res = await authFetch(`/programs/${programId}/services/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setServices((prev) => prev.filter((s) => s.id !== id));
    } catch { setMessage("Failed to delete service."); } finally { setDeleting(null); }
  }

  function handleInvestigate(svc: Service) {
    dispatch({
      type: "NAVIGATE_TO_REVIEW",
      tab: "manual",
      manualTest: {
        title: `Investigate ${svc.service_name || "service"} on ${svc.host}:${svc.port}`,
        hypothesis: `Port ${svc.port}/${svc.protocol} is open on ${svc.host} (${svc.service_name || "unknown"} — ${[svc.product, svc.version].filter(Boolean).join(" ") || "no version info"}). Investigate for misconfigurations, exposed admin interfaces, or vulnerabilities.`,
        payload: "",
        evidence: "",
        status: "new",
      },
    });
  }

  return (
    <div className="space-y-7">
      {!hideHeader && (
        <SectionHeader title="Services" description="Open ports and services discovered by nmap." />
      )}

      <Panel title={`Services (${services.length})`}>
        {loading && (
          <p className="py-6 text-center text-sm text-[#52525b]">Loading…</p>
        )}

        {!loading && services.length === 0 && (
          <div className="py-10 text-center">
            <p className="text-sm text-[#52525b]">No services discovered yet.</p>
            <p className="mt-1 text-xs text-[#3a3a3a]">Run an nmap job from the Dashboard to populate this list.</p>
          </div>
        )}

        {!loading && services.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#2e2e2e]">
                  {["Host", "Port", "Proto", "Service", "Product / Version", "State", "Last Scanned", ""].map((h) => (
                    <th key={h} className="pb-2 pr-4 font-semibold uppercase tracking-widest text-[#52525b]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {services.map((svc) => (
                  <tr key={svc.id} className="border-b border-[#1e1e1e] hover:bg-[#161616]">
                    <td className="py-2 pr-4 font-mono text-[#94a3b8]">{svc.host}</td>
                    <td className="py-2 pr-4 font-mono text-[#f59e0b]">{svc.port}</td>
                    <td className="py-2 pr-4 text-[#52525b]">{svc.protocol}</td>
                    <td className="py-2 pr-4 text-[#f1f5f9]">{svc.service_name || "—"}</td>
                    <td className="py-2 pr-4 text-[#94a3b8]">
                      {[svc.product, svc.version].filter(Boolean).join(" ") || "—"}
                    </td>
                    <td className="py-2 pr-4">
                      <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                        style={svc.state === "open" ? { background: "#14532d", color: "#4ade80" } : { background: "#2e2e2e", color: "#94a3b8" }}>
                        {svc.state}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-[#3a3a3a]">
                      {svc.last_scanned_at
                        ? new Date(svc.last_scanned_at).toLocaleDateString()
                        : "—"}
                    </td>
                    <td className="py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleInvestigate(svc)}
                          className="rounded px-2 py-0.5 text-[10px] text-[#52525b] transition hover:bg-[#2e2e2e] hover:text-[#89b4fa]">
                          Investigate
                        </button>
                        <button
                          onClick={() => handleDelete(svc.id)}
                          disabled={deleting === svc.id}
                          className="rounded px-2 py-0.5 text-[10px] text-[#52525b] transition hover:bg-[#2e2e2e] hover:text-red-400 disabled:opacity-40">
                          {deleting === svc.id ? "…" : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
