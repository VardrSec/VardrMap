"use client";

import { useEffect, useRef, useState } from "react";
import { Engagement } from "../types";
import { ManualTestFormState } from "../types";
import { ReviewTab } from "../context/appReducer";
import { useAppContext } from "../context/AppContext";
import ReconSection from "./ReconSection";
import ScanningSection from "./ScanningSection";
import ManualSection from "./ManualSection";
import ServicesSection from "./ServicesSection";

const TABS: { id: ReviewTab; label: string; countKey: keyof import("../types").Engagement }[] = [
  { id: "recon",    label: "Recon",    countKey: "recon_count"        },
  { id: "scans",    label: "Scans",    countKey: "scans_count"        },
  { id: "manual",   label: "Manual",   countKey: "manual_tests_count" },
  { id: "services", label: "Services", countKey: "services_count"     },
];

export default function ReviewSection({ engagement }: { engagement: Engagement }) {
  const { state: { reviewPrefill }, dispatch } = useAppContext();
  const [activeTab, setActiveTab] = useState<ReviewTab>("recon");
  const [manualPrefill, setManualPrefill] = useState<{ data: ManualTestFormState; epoch: number } | null>(null);
  // Provenance filter: when set, the recon/scans tab shows only rows produced by this job.
  const [jobFilter, setJobFilter] = useState<string | null>(null);
  const lastPrefillEpoch = useRef<number | null>(null);

  useEffect(() => {
    if (!reviewPrefill) return;
    const epoch = reviewPrefill.prefillEpoch ?? 0;
    if (lastPrefillEpoch.current === epoch) return;
    lastPrefillEpoch.current = epoch;
    if (reviewPrefill.tab) {
      setActiveTab(reviewPrefill.tab);
    }
    if (reviewPrefill.manualTest) {
      setManualPrefill({ data: reviewPrefill.manualTest, epoch });
    }
    setJobFilter(reviewPrefill.jobId ?? null);
    dispatch({ type: "REVIEW_PREFILL_CONSUMED" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewPrefill]);

  function selectTab(id: ReviewTab) {
    setActiveTab(id);
    setJobFilter(null);  // manual tab change clears any provenance filter
  }

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2e2e2e] pb-5">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">Review</h2>
          <p className="mt-1.5 text-sm text-[#52525b]">
            Explore recon data, scan results, manual test notes, and discovered services.
          </p>
        </div>
        <div className="flex rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] p-0.5">
          {TABS.map((t) => {
            const count = engagement[t.countKey] as number;
            return (
              <button key={t.id} onClick={() => selectTab(t.id)}
                className="flex items-center gap-1.5 rounded-md px-4 py-1.5 font-mono text-[11px] uppercase tracking-wider transition"
                style={activeTab === t.id ? { backgroundColor: "#2e2e2e", color: "#f1f5f9" } : { color: "#52525b" }}>
                {t.label}
                {count > 0 && (
                  <span className="rounded bg-[#2e2e2e] px-1 py-0.5 font-mono text-[9px] leading-none"
                    style={{ color: activeTab === t.id ? "#f1f5f9" : "#52525b", backgroundColor: activeTab === t.id ? "#3a3a3a" : "#242424" }}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {activeTab === "recon"    && <ReconSection    engagementId={engagement.id} hideHeader scopeItems={engagement.scope.in} jobFilter={jobFilter} onClearJobFilter={() => setJobFilter(null)} />}
      {activeTab === "scans"    && <ScanningSection engagementId={engagement.id} hideHeader scopeItems={engagement.scope.in} jobFilter={jobFilter} onClearJobFilter={() => setJobFilter(null)} />}
      {activeTab === "manual"   && (
        <ManualSection
          engagement={engagement}
          hideHeader
          prefill={manualPrefill ?? undefined}
        />
      )}
      {activeTab === "services" && <ServicesSection engagementId={engagement.id} hideHeader />}
    </div>
  );
}
