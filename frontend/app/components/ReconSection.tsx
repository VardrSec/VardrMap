"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ReconItem, ScopeItem } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, SectionHeader } from "./ui";
import HostDetailPanel from "./HostDetailPanel";

const PAGE_SIZE = 100;

function hostOf(value: string | undefined): string {
  let s = (value || "").trim().toLowerCase();
  if (!s) return "";
  if (s.includes("://")) s = s.split("://")[1];
  s = s.split("/")[0].split("@").pop()!;
  if (s.startsWith("[")) return s.split("]")[0] + "]";
  return s.split(":")[0];
}

function isInScope(item: ReconItem, scopeItems: ScopeItem[]): boolean {
  const host = hostOf(item.host || item.url);
  if (!host) return false;
  return scopeItems.some((s) => {
    const val = s.value.toLowerCase().replace(/^\*\./, "");
    return host === val || host.endsWith(`.${val}`);
  });
}

// Recon and scans are fetched independently (not embedded in the engagement object)
// because a real ffuf/httpx run can return thousands of rows — we don't want
// all of that coming down on every engagement refresh.
export default function ReconSection({
  engagementId, hideHeader, scopeItems, jobFilter, onClearJobFilter,
}: {
  engagementId: string; hideHeader?: boolean; scopeItems?: ScopeItem[];
  jobFilter?: string | null; onClearJobFilter?: () => void;
}) {
  const { authFetch, setMessage } = useAppContext();
  const [items,        setItems]        = useState<ReconItem[]>([]);
  const [total,        setTotal]        = useState(0);
  const [offset,       setOffset]       = useState(0);
  const [loading,      setLoading]      = useState(false);
  const [search,       setSearch]       = useState("");
  const [searchInput,  setSearchInput]  = useState("");
  const [scopeOnly,    setScopeOnly]    = useState(false);
  const [detailItem,   setDetailItem]   = useState<ReconItem | null>(null);

  // replace=true on initial load or engagement/search change; false for "Load more"
  const load = useCallback(async (off: number, replace: boolean, q: string, signal?: AbortSignal) => {
    setLoading(true);
    try {
      const params = `limit=${PAGE_SIZE}&offset=${off}${q ? `&search=${encodeURIComponent(q)}` : ""}${jobFilter ? `&job_id=${encodeURIComponent(jobFilter)}` : ""}`;
      const res = await authFetch(`/engagements/${engagementId}/recon?${params}`, { signal });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTotal(data.total ?? 0);
      setItems((prev) => replace ? data.recon : [...prev, ...data.recon]);
      setOffset(off);
    } catch (e) {
      if ((e as { name?: string }).name !== "AbortError") setMessage("Failed to load recon.");
    } finally { setLoading(false); }
  }, [engagementId, authFetch, setMessage, jobFilter]);

  useEffect(() => {
    const ctrl = new AbortController();
    void load(0, true, search, ctrl.signal);
    return () => ctrl.abort();
  }, [load, search]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(searchInput);
  }

  function clearSearch() {
    setSearch("");
    setSearchInput("");
  }

  const visibleItems = useMemo(() => {
    if (!scopeOnly || !scopeItems?.length) return items;
    return items.filter((item) => isInScope(item, scopeItems));
  }, [items, scopeOnly, scopeItems]);

  return (
    <div className="space-y-7">
      {detailItem && (
        <HostDetailPanel
          key={detailItem.id}
          engagementId={engagementId}
          item={detailItem}
          onClose={() => setDetailItem(null)}
        />
      )}
      {!hideHeader && <SectionHeader title="Recon" description="Review discovered subdomains, endpoints, paths, and technologies." />}

      {jobFilter && (
        <div className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"
          style={{ borderColor: "#f59e0b33", backgroundColor: "#f59e0b0d", color: "#f59e0b" }}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#f59e0b" }} />
          Showing recon produced by one scan job
          <button onClick={onClearJobFilter}
            className="ml-auto rounded border border-[#f59e0b33] px-2 py-0.5 font-mono text-[10px] transition hover:bg-[#f59e0b1a]">
            clear filter
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <form onSubmit={handleSearch} className="flex flex-1 gap-2">
          <input
            className="flex-1 rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none"
            placeholder="Search URLs, hosts, paths, titles…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button type="submit" className="rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
            Search
          </button>
          {search && (
            <button type="button" onClick={clearSearch}
              className="rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:text-[#94a3b8]">
              Clear
            </button>
          )}
        </form>
        {scopeItems && scopeItems.length > 0 && (
          <button
            type="button"
            onClick={() => setScopeOnly((v) => !v)}
            className="flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs transition"
            style={scopeOnly
              ? { borderColor: "#f59e0b55", color: "#f59e0b", backgroundColor: "#f59e0b0d" }
              : { borderColor: "#2e2e2e", color: "#52525b" }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: scopeOnly ? "#f59e0b" : "#3a3a3a" }} />
            In scope only
          </button>
        )}
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title={`Discovered Assets (${scopeOnly ? visibleItems.length : total}${scopeOnly ? " in scope" : ""})`}>
          {visibleItems.length === 0 && !loading ? (
            <p className="text-sm text-[#3a3a3a]">{search ? "No results for that search." : scopeOnly ? "No in-scope assets found." : "No recon data imported yet."}</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#2e2e2e]">
                      {["Source", "URL / Host", "Path / Title", "Status"].map((h) => (
                        <th key={h} className="pb-2.5 pr-4 text-left text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((item, i) => (
                      <tr
                        key={item.id}
                        onClick={() => setDetailItem(item)}
                        className={`cursor-pointer border-b border-[#161616] transition hover:bg-[#1f1f1f] ${i % 2 === 0 ? "" : "bg-[#1a1a1a]/40"}`}>
                        <td className="py-2.5 pr-4 font-mono text-[#52525b]">{item.source}</td>
                        <td className="py-2.5 pr-4 max-w-[180px] truncate text-[#f1f5f9]">{item.url || item.host || "—"}</td>
                        <td className="py-2.5 pr-4 max-w-[160px] truncate text-[#6b7280]">{item.path || item.title || "—"}</td>
                        <td className="py-2.5 font-mono text-[#52525b]">{item.status_code || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!scopeOnly && items.length < total && (
                <button onClick={() => load(offset + PAGE_SIZE, false, search)} disabled={loading}
                  className="mt-4 rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8] disabled:opacity-50">
                  {loading ? "Loading…" : `Load more (${total - items.length} remaining)`}
                </button>
              )}
            </>
          )}
        </Panel>
        <Panel title="Technology / Metadata">
          {items.length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">{search ? "No results for that search." : "No recon data imported yet."}</p>
          ) : (
            <div className="space-y-2">
              {items.map((item) => (
                <div key={item.id} className="rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                  <div className="text-sm font-medium text-[#f1f5f9]">{item.url || item.host || "Unknown"}</div>
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-[#52525b]">
                    <span>Server: <span className="text-[#6b7280]">{item.webserver || "—"}</span></span>
                    <span>Tech: <span className="text-[#6b7280]">{Array.isArray(item.tech) ? (item.tech.join(", ") || "—") : (item.tech || "—")}</span></span>
                    <span>L/W/Li: <span className="font-mono text-[#6b7280]">{item.length || 0}/{item.words || 0}/{item.lines || 0}</span></span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
