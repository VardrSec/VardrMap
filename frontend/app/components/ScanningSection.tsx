"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ScanItem, ScanTriageResult, ScopeItem } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, SeverityBadge, StatusBadge, SectionHeader } from "./ui";

const PRIORITY_STYLE: Record<string, { color: string; bg: string }> = {
  high:   { color: "#f87171", bg: "rgba(127,29,29,0.25)" },
  medium: { color: "#fbbf24", bg: "rgba(120,53,15,0.25)" },
  low:    { color: "#94a3b8", bg: "rgba(30,41,59,0.4)" },
  noise:  { color: "#52525b", bg: "rgba(30,30,30,0.6)" },
};

const PAGE_SIZE = 100;
const STATUS_FILTERS = ["new", "reviewed", "false_positive", "promoted", "all"] as const;
type StatusFilter = typeof STATUS_FILTERS[number];

function assetMatchesScope(asset: string, scopeItems: ScopeItem[]): boolean {
  const host = asset.toLowerCase().split("/")[0].split(":")[0];
  return scopeItems.some((s) => {
    const val = s.value.toLowerCase().replace(/^\*\./, "");
    return host === val || host.endsWith(`.${val}`);
  });
}

export default function ScanningSection({
  programId, hideHeader, scopeItems, jobFilter, onClearJobFilter,
}: {
  programId: string; hideHeader?: boolean; scopeItems?: ScopeItem[];
  jobFilter?: string | null; onClearJobFilter?: () => void;
}) {
  const { authFetch, setMessage, promoteScanToFinding } = useAppContext();
  const [items,        setItems]        = useState<ScanItem[]>([]);
  const [total,        setTotal]        = useState(0);
  const [offset,       setOffset]       = useState(0);
  const [loading,      setLoading]      = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("new");
  const [selected,     setSelected]     = useState<Set<string>>(new Set());
  const [scopeOnly,    setScopeOnly]    = useState(false);
  const [triage,       setTriage]       = useState<Record<string, ScanTriageResult>>({});
  const [triaging,     setTriaging]     = useState(false);

  const load = useCallback(async (off: number, replace: boolean, filter: StatusFilter) => {
    setLoading(true);
    try {
      const params = `limit=${PAGE_SIZE}&offset=${off}${filter !== "all" ? `&status=${filter}` : ""}${jobFilter ? `&job_id=${encodeURIComponent(jobFilter)}` : ""}`;
      const res = await authFetch(`/programs/${programId}/scans?${params}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTotal(data.total ?? 0);
      setItems((prev) => replace ? data.scans : [...prev, ...data.scans]);
      setOffset(off);
    } catch { setMessage("Failed to load scans."); } finally { setLoading(false); }
  }, [programId, authFetch, setMessage, jobFilter]);

  // When arriving from a job provenance link, default to "all" so results in any
  // status are visible — a job's output isn't only "new" after prior review.
  useEffect(() => { if (jobFilter) setStatusFilter("all"); }, [jobFilter]);
  useEffect(() => { void load(0, true, statusFilter); }, [load, statusFilter]);
  useEffect(() => { setSelected(new Set()); }, [statusFilter]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
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
    promoteScanToFinding(scan);
  }

  // AI triage over the currently-loaded items — ranks priority + flags false positives.
  async function runTriage() {
    const ids = visibleItems.map((s) => s.id);
    if (ids.length === 0) { setMessage("No scan results to triage."); return; }
    setTriaging(true);
    try {
      const res = await authFetch(`/programs/${programId}/scans/triage`, {
        method: "POST",
        body: JSON.stringify({ ids }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null) as { detail?: string } | null;
        setMessage(err?.detail || "AI triage failed.");
        return;
      }
      const data = await res.json() as { triage: ScanTriageResult[] };
      const map: Record<string, ScanTriageResult> = {};
      for (const t of data.triage) map[t.id] = t;
      setTriage((prev) => ({ ...prev, ...map }));
      setMessage(`Triaged ${data.triage.length} result${data.triage.length === 1 ? "" : "s"}.`);
    } catch { setMessage("AI triage failed."); } finally { setTriaging(false); }
  }

  const visibleItems = useMemo(() => {
    if (!scopeOnly || !scopeItems?.length) return items;
    return items.filter((s) => assetMatchesScope(s.asset || "", scopeItems));
  }, [items, scopeOnly, scopeItems]);

  const allSelected = visibleItems.length > 0 && visibleItems.every((i) => selected.has(i.id));

  return (
    <div className="space-y-7">
      {!hideHeader && <SectionHeader title="Scanning" description="Review candidate vulnerabilities from imported scan results." />}

      {jobFilter && (
        <div className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"
          style={{ borderColor: "#f59e0b33", backgroundColor: "#f59e0b0d", color: "#f59e0b" }}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#f59e0b" }} />
          Showing results produced by one scan job
          <button onClick={onClearJobFilter}
            className="ml-auto rounded border border-[#f59e0b33] px-2 py-0.5 font-mono text-[10px] transition hover:bg-[#f59e0b1a]">
            clear filter
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((f) => (
          <button key={f} onClick={() => setStatusFilter(f)}
            className={`rounded-md border px-3 py-1.5 text-xs font-semibold transition ${statusFilter === f ? "border-[#f59e0b]/40 bg-[#f59e0b]/10 text-[#f59e0b]" : "border-[#2e2e2e] text-[#52525b] hover:text-[#94a3b8]"}`}>
            {f === "all" ? "All" : f.replace(/_/g, " ")}
          </button>
        ))}
        {scopeItems && scopeItems.length > 0 && (
          <button
            onClick={() => setScopeOnly((v) => !v)}
            className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition"
            style={scopeOnly
              ? { borderColor: "#f59e0b55", color: "#f59e0b", backgroundColor: "#f59e0b0d" }
              : { borderColor: "#2e2e2e", color: "#52525b" }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: scopeOnly ? "#f59e0b" : "#3a3a3a" }} />
            In scope only
          </button>
        )}
        <button
          onClick={runTriage}
          disabled={triaging || visibleItems.length === 0}
          className="ml-auto flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50"
          style={{ borderColor: "#f59e0b55", color: "#f59e0b", backgroundColor: "#f59e0b0d" }}
          title="Rank the loaded results by priority and flag likely false positives">
          <span className="font-mono leading-none">✦</span>
          {triaging ? "Triaging…" : "Triage with AI"}
        </button>
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
            Mark Promoted
          </button>
          <button onClick={() => setSelected(new Set())}
            className="ml-auto rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:text-[#94a3b8]">
            Clear
          </button>
        </div>
      )}

      <Panel title={`Scan Results (${scopeOnly ? visibleItems.length : total}${scopeOnly ? " in scope" : ""})`}>
        {visibleItems.length === 0 && !loading ? (
          <p className="text-sm text-[#3a3a3a]">
            {scopeOnly ? "No in-scope scan results." : statusFilter === "all" ? "No scan results imported yet." : `No ${statusFilter.replace(/_/g, " ")} results.`}
          </p>
        ) : (
          <div className="space-y-3">
            {visibleItems.length > 0 && (
              <div className="flex items-center gap-2 border-b border-[#2e2e2e] pb-2">
                <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                  className="h-3.5 w-3.5 cursor-pointer accent-[#f59e0b]" />
                <span className="select-none text-[10px] text-[#52525b]">
                  {allSelected ? "Deselect all" : "Select all on page"}
                </span>
              </div>
            )}
            {visibleItems.map((scan) => (
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
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <SeverityBadge severity={scan.severity} />
                        <StatusBadge   status={scan.status} />
                        {triage[scan.id] && (
                          <span className="flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide"
                            style={{
                              color: (PRIORITY_STYLE[triage[scan.id].priority] ?? PRIORITY_STYLE.low).color,
                              backgroundColor: (PRIORITY_STYLE[triage[scan.id].priority] ?? PRIORITY_STYLE.low).bg,
                              borderColor: "transparent",
                            }}>
                            ✦ {triage[scan.id].priority}
                            {triage[scan.id].false_positive && <span className="opacity-70">· likely FP</span>}
                          </span>
                        )}
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
                  {triage[scan.id]?.rationale && (
                    <p className="mt-2 font-mono text-[11px] leading-relaxed" style={{ color: "#94a3b8" }}>
                      <span style={{ color: "#f59e0b" }}>✦ AI:</span> {triage[scan.id].rationale}
                    </p>
                  )}
                  {scan.description && <p className="mt-3 text-sm text-[#6b7280]">{scan.description}</p>}
                </div>
              </div>
            ))}
            {!scopeOnly && items.length < total && (
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
