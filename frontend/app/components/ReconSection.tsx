"use client";

import { useCallback, useEffect, useState } from "react";
import { ReconItem } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, SectionHeader } from "./ui";

const PAGE_SIZE = 100;

// Recon and scans are fetched independently (not embedded in the program object)
// because a real ffuf/httpx run can return thousands of rows — we don't want
// all of that coming down on every program refresh.
export default function ReconSection({ programId, hideHeader }: { programId: string; hideHeader?: boolean }) {
  const { authFetch, setMessage } = useAppContext();
  const [items,        setItems]        = useState<ReconItem[]>([]);
  const [total,        setTotal]        = useState(0);
  const [offset,       setOffset]       = useState(0);
  const [loading,      setLoading]      = useState(false);
  const [search,       setSearch]       = useState("");
  const [searchInput,  setSearchInput]  = useState("");

  // replace=true on initial load or program/search change; false for "Load more"
  const load = useCallback(async (off: number, replace: boolean, q: string) => {
    setLoading(true);
    try {
      const params = `limit=${PAGE_SIZE}&offset=${off}${q ? `&search=${encodeURIComponent(q)}` : ""}`;
      const res = await authFetch(`/programs/${programId}/recon?${params}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTotal(data.total ?? 0);
      setItems((prev) => replace ? data.recon : [...prev, ...data.recon]);
      setOffset(off);
    } catch { setMessage("Failed to load recon."); } finally { setLoading(false); }
  }, [programId, authFetch, setMessage]);

  useEffect(() => { void load(0, true, search); }, [load, search]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(searchInput);
  }

  function clearSearch() {
    setSearch("");
    setSearchInput("");
  }

  return (
    <div className="space-y-7">
      {!hideHeader && <SectionHeader title="Recon" description="Review discovered subdomains, endpoints, paths, and technologies." />}

      <form onSubmit={handleSearch} className="flex gap-2">
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

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title={`Discovered Assets (${total})`}>
          {items.length === 0 && !loading ? (
            <p className="text-sm text-[#3a3a3a]">{search ? "No results for that search." : "No recon data imported yet."}</p>
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
                    {items.map((item, i) => (
                      <tr key={item.id} className={`border-b border-[#161616] ${i % 2 === 0 ? "" : "bg-[#1a1a1a]/40"}`}>
                        <td className="py-2.5 pr-4 font-mono text-[#52525b]">{item.source}</td>
                        <td className="py-2.5 pr-4 max-w-[180px] truncate text-[#f1f5f9]">{item.url || item.host || "—"}</td>
                        <td className="py-2.5 pr-4 max-w-[160px] truncate text-[#6b7280]">{item.path || item.title || "—"}</td>
                        <td className="py-2.5 font-mono text-[#52525b]">{item.status_code || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {items.length < total && (
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
                    <span>Tech: <span className="text-[#6b7280]">{Array.isArray(item.tech) ? item.tech.join(", ") || "—" : "—"}</span></span>
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
