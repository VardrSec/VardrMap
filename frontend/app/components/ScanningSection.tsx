"use client";

import { useCallback, useEffect, useState } from "react";
import { ScanItem, AuthFetch } from "../types";
import { Panel, SeverityBadge, SectionHeader } from "./ui";

const PAGE_SIZE = 100;

export default function ScanningSection({ programId, authFetch, setMessage, onPromote }: {
  programId: string;
  authFetch: AuthFetch;
  setMessage: (m: string) => void;
  onPromote: (scan: ScanItem) => void;
}) {
  const [items,   setItems]   = useState<ScanItem[]>([]);
  const [total,   setTotal]   = useState(0);
  const [offset,  setOffset]  = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (off: number, replace: boolean) => {
    setLoading(true);
    try {
      const res = await authFetch(`/programs/${programId}/scans?limit=${PAGE_SIZE}&offset=${off}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTotal(data.total ?? 0);
      setItems((prev) => replace ? data.scans : [...prev, ...data.scans]);
      setOffset(off);
    } catch { setMessage("Failed to load scans."); } finally { setLoading(false); }
  }, [programId, authFetch, setMessage]);

  useEffect(() => { void load(0, true); }, [load]);

  return (
    <div className="space-y-7">
      <SectionHeader title="Scanning" description="Review candidate vulnerabilities from imported scan results." />
      <Panel title={`Nuclei Candidates (${total})`}>
        {items.length === 0 && !loading ? (
          <p className="text-sm text-[#3a3a3a]">No scan results imported yet.</p>
        ) : (
          <div className="space-y-3">
            {items.map((scan) => (
              <div key={scan.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-[#f1f5f9]">{scan.title}</div>
                    <div className="mt-1 font-mono text-xs text-[#52525b]">{scan.asset || "Unknown"} · {scan.template_id}</div>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    <SeverityBadge severity={scan.severity} />
                    <button onClick={() => onPromote(scan)} className="rounded-md border border-[#2e2e2e] bg-[#242424] px-3 py-1.5 text-xs font-semibold text-[#f59e0b] transition hover:border-[#f59e0b]/30 hover:bg-[#2e2e2e]">
                      Promote →
                    </button>
                  </div>
                </div>
                {scan.description && <p className="mt-3 text-sm text-[#6b7280]">{scan.description}</p>}
              </div>
            ))}
            {items.length < total && (
              <button onClick={() => load(offset + PAGE_SIZE, false)} disabled={loading}
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
