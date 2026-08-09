"use client";

import { useEffect, useState } from "react";
import type { Finding, ReconItem, ScanItem, Service } from "../types";
import { useAppContext } from "../context/AppContext";

type Props = {
  engagementId: string;
  item: ReconItem;
  onClose: () => void;
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{title}</p>
      {children}
    </div>
  );
}

function Empty() {
  return <p className="text-xs text-[#3a3a3a]">None found.</p>;
}

export default function HostDetailPanel({ engagementId, item, onClose }: Props) {
  const { authFetch, navigate } = useAppContext();
  const [services,  setServices]  = useState<Service[]>([]);
  const [scans,     setScans]     = useState<ScanItem[]>([]);
  const [findings,  setFindings]  = useState<Finding[]>([]);
  const [loading,   setLoading]   = useState(true);

  // The host key used to filter across data sources
  const host = item.host || (item.url ? new URL(item.url.startsWith("http") ? item.url : `https://${item.url}`).hostname : "");

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      authFetch(`/engagements/${engagementId}/services`),
      authFetch(`/engagements/${engagementId}/scans?limit=500&offset=0`),
      authFetch(`/engagements/${engagementId}/findings?limit=500&offset=0`),
    ]).then(async ([svcRes, scanRes, findRes]) => {
      if (cancelled) return;
      const svcData  = svcRes.ok  ? await svcRes.json()  : null;
      const scanData = scanRes.ok ? await scanRes.json() : null;
      const findData = findRes.ok ? await findRes.json() : null;

      const matchHost = (h: string) =>
        host ? h === host || h.endsWith(`.${host}`) || host.endsWith(`.${h}`) : false;

      setServices((svcData?.services  ?? []).filter((s: Service)  => matchHost(s.host)));
      setScans(   (scanData?.scans    ?? []).filter((s: ScanItem) => matchHost(s.asset)));
      setFindings((findData?.findings ?? []).filter((f: Finding)  => matchHost(f.asset)));
      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [engagementId, host, authFetch]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const SEV_COLOR: Record<string, string> = {
    critical: "text-[#f38ba8]", high: "text-[#fab387]",
    medium: "text-[#f9e2af]",   low: "text-[#89b4fa]", info: "text-[#74c7ec]",
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="relative flex h-full w-full max-w-[480px] flex-col overflow-y-auto border-l border-[#2e2e2e] bg-[#111] shadow-2xl"
        onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-[#2e2e2e] bg-[#111] px-5 py-4">
          <div className="min-w-0">
            <p className="break-all font-mono text-sm font-semibold text-[#f1f5f9]">
              {item.url || item.host || "Unknown"}
            </p>
            <p className="mt-0.5 font-mono text-[10px] text-[#52525b]">host detail</p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 rounded-md border border-[#2e2e2e] px-2.5 py-1 font-mono text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
            ✕
          </button>
        </div>

        <div className="space-y-6 px-5 py-5">
          {/* Recon details */}
          <Section title="Recon">
            <div className="rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3 space-y-1.5">
              {item.status_code && (
                <div className="flex gap-3 text-xs">
                  <span className="text-[#52525b]">Status</span>
                  <span className="font-mono text-[#f1f5f9]">{item.status_code}</span>
                </div>
              )}
              {item.title && (
                <div className="flex gap-3 text-xs">
                  <span className="text-[#52525b]">Title</span>
                  <span className="text-[#94a3b8]">{item.title}</span>
                </div>
              )}
              {item.webserver && (
                <div className="flex gap-3 text-xs">
                  <span className="text-[#52525b]">Server</span>
                  <span className="font-mono text-[#6b7280]">{item.webserver}</span>
                </div>
              )}
              {item.tech && (
                <div className="flex gap-3 text-xs">
                  <span className="text-[#52525b]">Tech</span>
                  <span className="text-[#6b7280]">
                    {Array.isArray(item.tech) ? item.tech.join(", ") : item.tech}
                  </span>
                </div>
              )}
              {item.content_type && (
                <div className="flex gap-3 text-xs">
                  <span className="text-[#52525b]">Content-Type</span>
                  <span className="font-mono text-[#6b7280]">{item.content_type}</span>
                </div>
              )}
              <div className="flex gap-3 text-xs">
                <span className="text-[#52525b]">Source</span>
                <span className="font-mono text-[#3a3a3a]">{item.source}</span>
              </div>
            </div>
          </Section>

          {/* Services */}
          <Section title={`Services${services.length ? ` (${services.length})` : ""}`}>
            {loading ? <p className="text-xs text-[#52525b]">Loading…</p> :
              services.length === 0 ? <Empty /> : (
                <div className="space-y-1.5">
                  {services.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 rounded-lg border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-xs">
                      <span className="font-mono text-[#f59e0b]">{s.port}/{s.protocol}</span>
                      <span className="text-[#94a3b8]">{s.service_name || "—"}</span>
                      {s.product && <span className="text-[#52525b]">{s.product}{s.version ? ` ${s.version}` : ""}</span>}
                      <span className={`ml-auto font-mono text-[10px] ${s.state === "open" ? "text-[#a6e3a1]" : "text-[#52525b]"}`}>
                        {s.state}
                      </span>
                    </div>
                  ))}
                </div>
              )}
          </Section>

          {/* Scans */}
          <Section title={`Vulnerabilities${scans.length ? ` (${scans.length})` : ""}`}>
            {loading ? <p className="text-xs text-[#52525b]">Loading…</p> :
              scans.length === 0 ? <Empty /> : (
                <div className="space-y-1.5">
                  {scans.map((s) => (
                    <div key={s.id} className="rounded-lg border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-xs space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className={`font-mono ${SEV_COLOR[s.severity] || "text-[#52525b]"}`}>{s.severity}</span>
                        <span className="truncate text-[#f1f5f9]">{s.title}</span>
                      </div>
                      <div className="font-mono text-[#3a3a3a]">{s.template_id}</div>
                    </div>
                  ))}
                </div>
              )}
          </Section>

          {/* Findings */}
          <Section title={`Findings${findings.length ? ` (${findings.length})` : ""}`}>
            {loading ? <p className="text-xs text-[#52525b]">Loading…</p> :
              findings.length === 0 ? <Empty /> : (
                <div className="space-y-1.5">
                  {findings.map((f) => (
                    <div key={f.id} className="rounded-lg border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-xs space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className={`font-mono ${SEV_COLOR[f.severity] || "text-[#52525b]"}`}>{f.severity}</span>
                        <span className="truncate text-[#f1f5f9]">{f.title}</span>
                      </div>
                      <div className="font-mono text-[10px] text-[#52525b]">{f.status}</div>
                    </div>
                  ))}
                  <button
                    onClick={() => { onClose(); navigate("findings"); }}
                    className="mt-1 w-full rounded-md border border-[#2e2e2e] py-1.5 font-mono text-[11px] text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                    Open Findings →
                  </button>
                </div>
              )}
          </Section>
        </div>
      </div>
    </div>
  );
}
