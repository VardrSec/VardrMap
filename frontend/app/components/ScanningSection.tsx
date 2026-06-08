"use client";

import { useCallback, useEffect, useState } from "react";
import { ScanItem, AuthFetch } from "../types";
import { Panel, SeverityBadge, StatusBadge, SectionHeader } from "./ui";

const PAGE_SIZE = 100;
const STATUS_FILTERS = ["new", "reviewed", "false_positive", "promoted", "all"] as const;
type StatusFilter = typeof STATUS_FILTERS[number];

export default function ScanningSection({ programId, authFetch, setMessage, onPromote }: {
  programId: string;
  authFetch: AuthFetch;
  setMessage: (m: string) => void;
  onPromote: (scan: ScanItem) => void;
}) {
  const [items,        setItems]        = useState<ScanItem[]>([]);
  const [total,        setTotal]        = useState(0);
  const [offset,       setOffset]       = useState(0);
  const [loading,      setLoading]      = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("new");

  const load = useCallback(async (off: number, replace: boolean, filter: StatusFilter) => {
    setLoading(true);
    try {
      const params = `limit=${PAGE_SIZE}&offset=${off}${filter !== "all" ? `&status=${filter}` : ""}`;
      const res = await authFetch(`/programs/${programId}/scans?${params}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTotal(data.total ?? 0);
      setItems((prev) => replace ? data.scans : [...prev, ...data.scans]);
      setOffset(off);
    } catch { setMessage("Failed to load scans."); } finally { setLoading(false); }
  }, [programId, authFetch, setMessage]);

  useEffect(() => { void load(0, true, statusFilter); }, [load, statusFilter]);

  async function updateStatus(scan: ScanItem, status: string) {
    try {
      await authFetch(`/programs/${programId}/scans/${scan.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setItems((prev) => prev.map((s) => s.id === scan.id ? { ...s, status } : s));
    } catch { setMessage("Failed to update scan."); }
  }

  async function promote(scan: ScanItem) {
    await updateStatus(scan, "promoted");
    onPromote(scan);
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Scanning" description="Review candidate vulnerabilities from imported scan results." />

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <button key={f} onClick={() => setStatusFilter(f)}
            className={`rounded-md border px-3 py-1.5 text-xs font-semibold transition ${statusFilter === f ? "border-[#f59e0b]/40 bg-[#f59e0b]/10 text-[#f59e0b]" : "border-[#2e2e2e] text-[#52525b] hover:text-[#94a3b8]"}`}>
            {f === "all" ? "All" : f.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      <Panel title={`Scan Results (${total})`}>
        {items.length === 0 && !loading ? (
          <p className="text-sm text-[#3a3a3a]">
            {statusFilter === "all" ? "No scan results imported yet." : `No ${statusFilter.replace(/_/g, " ")} results.`}
          </p>
        ) : (
          <div className="space-y-3">
            {items.map((scan) => (
              <div key={scan.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-[#f1f5f9]">{scan.title}</div>
                    <div className="mt-1 font-mono text-xs text-[#52525b]">{scan.asset || "Unknown"} · {scan.template_id}</div>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      <SeverityBadge severity={scan.severity} />
                      <StatusBadge   status={scan.status} />
                    </div>
                  </div>
                  <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
                    {scan.status === "new" && (
                      <button onClick={() => updateStatus(scan, "reviewed")}
                        className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                        Review
                      </button>
                    )}
                    {scan.status !== "false_positive" && scan.status !== "promoted" && (
                      <button onClick={() => updateStatus(scan, "false_positive")}
                        className="rounded-md border border-red-900/40 bg-red-950/20 px-2.5 py-1 text-xs text-red-400 transition hover:bg-red-950/40">
                        False Positive
                      </button>
                    )}
                    {scan.status !== "promoted" && (
                      <button onClick={() => promote(scan)}
                        className="rounded-md border border-[#2e2e2e] bg-[#242424] px-3 py-1.5 text-xs font-semibold text-[#f59e0b] transition hover:border-[#f59e0b]/30 hover:bg-[#2e2e2e]">
                        Promote →
                      </button>
                    )}
                  </div>
                </div>
                {scan.description && <p className="mt-3 text-sm text-[#6b7280]">{scan.description}</p>}
              </div>
            ))}
            {items.length < total && (
              <button onClick={() => load(offset + PAGE_SIZE, false, statusFilter)} disabled={loading}
                className="w-full rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8] disabled:opacity-50">
                {loading ? "Loading…" : `Load more (${total - items.length} remaining)`}
              </button>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
