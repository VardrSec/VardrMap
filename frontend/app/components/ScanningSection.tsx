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
  const [selected,     setSelected]     = useState<Set<string>>(new Set());

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
  useEffect(() => { setSelected(new Set()); }, [statusFilter]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected(selected.size === items.length && items.length > 0
      ? new Set()
      : new Set(items.map((s) => s.id)));
  }

  async function updateStatus(scan: ScanItem, status: string) {
    try {
      await authFetch(`/programs/${programId}/scans/${scan.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setItems((prev) => prev.map((s) => s.id === scan.id ? { ...s, status } : s));
    } catch { setMessage("Failed to update scan."); }
  }

  async function bulkUpdateStatus(status: string) {
    const ids = [...selected];
    const count = ids.length;
    try {
      const res = await authFetch(`/programs/${programId}/scans/bulk-status`, {
        method: "POST",
        body: JSON.stringify({ ids, status }),
      });
      if (!res.ok) throw new Error();
      setSelected(new Set());
      await load(0, true, statusFilter);
      setMessage(`${count} scan${count !== 1 ? "s" : ""} marked as ${status.replace(/_/g, " ")}.`);
    } catch { setMessage("Bulk update failed."); }
  }

  async function promote(scan: ScanItem) {
    await updateStatus(scan, "promoted");
    onPromote(scan);
  }

  const allSelected = items.length > 0 && selected.size === items.length;

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

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#f59e0b]/20 bg-[#f59e0b]/5 px-4 py-2.5">
          <span className="text-xs font-semibold text-[#f59e0b]">{selected.size} selected</span>
          <span className="select-none text-[#3a3a3a]">·</span>
          <span className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">Mark as:</span>
          <button onClick={() => bulkUpdateStatus("reviewed")}
            className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
            Reviewed
          </button>
          <button onClick={() => bulkUpdateStatus("false_positive")}
            className="rounded-md border border-red-900/40 px-2.5 py-1 text-xs text-red-400 transition hover:bg-red-950/20">
            False Positive
          </button>
          <button onClick={() => bulkUpdateStatus("promoted")}
            className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs font-semibold text-[#f59e0b] transition hover:border-[#f59e0b]/30">
            Promote
          </button>
          <button onClick={() => setSelected(new Set())}
            className="ml-auto rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:text-[#94a3b8]">
            Clear
          </button>
        </div>
      )}

      <Panel title={`Scan Results (${total})`}>
        {items.length === 0 && !loading ? (
          <p className="text-sm text-[#3a3a3a]">
            {statusFilter === "all" ? "No scan results imported yet." : `No ${statusFilter.replace(/_/g, " ")} results.`}
          </p>
        ) : (
          <div className="space-y-3">
            {items.length > 0 && (
              <div className="flex items-center gap-2 border-b border-[#2e2e2e] pb-2">
                <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                  className="h-3.5 w-3.5 cursor-pointer accent-[#f59e0b]" />
                <span className="select-none text-[10px] text-[#52525b]">
                  {allSelected ? "Deselect all" : "Select all on page"}
                </span>
              </div>
            )}
            {items.map((scan) => (
              <div key={scan.id}
                className={`flex gap-3 rounded-xl border p-4 transition ${selected.has(scan.id) ? "border-[#f59e0b]/25 bg-[#f59e0b]/[0.04]" : "border-[#2e2e2e] bg-[#161616]"}`}>
                <input type="checkbox"
                  checked={selected.has(scan.id)}
                  onChange={() => toggleSelect(scan.id)}
                  className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 cursor-pointer accent-[#f59e0b]"
                />
                <div className="min-w-0 flex-1">
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
