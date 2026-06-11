"use client";

import { useEffect, useRef, useState } from "react";
import { Program } from "../types";
import { ManualTestFormState } from "../types";
import { ReviewTab } from "../context/appReducer";
import { useAppContext } from "../context/AppContext";
import ReconSection from "./ReconSection";
import ScanningSection from "./ScanningSection";
import ManualSection from "./ManualSection";
import ServicesSection from "./ServicesSection";

const TABS: { id: ReviewTab; label: string }[] = [
  { id: "recon",    label: "Recon"    },
  { id: "scans",    label: "Scans"    },
  { id: "manual",   label: "Manual"   },
  { id: "services", label: "Services" },
];

export default function ReviewSection({ program }: { program: Program }) {
  const { state: { reviewPrefill }, dispatch } = useAppContext();
  const [activeTab, setActiveTab] = useState<ReviewTab>("recon");
  const [manualPrefill, setManualPrefill] = useState<{ data: ManualTestFormState; epoch: number } | null>(null);
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
    dispatch({ type: "REVIEW_PREFILL_CONSUMED" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewPrefill]);

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
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className="rounded-md px-5 py-1.5 font-mono text-[11px] uppercase tracking-wider transition"
              style={activeTab === t.id ? { backgroundColor: "#2e2e2e", color: "#f1f5f9" } : { color: "#52525b" }}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "recon"    && <ReconSection    programId={program.id} hideHeader />}
      {activeTab === "scans"    && <ScanningSection programId={program.id} hideHeader />}
      {activeTab === "manual"   && (
        <ManualSection
          program={program}
          hideHeader
          prefill={manualPrefill ?? undefined}
        />
      )}
      {activeTab === "services" && <ServicesSection programId={program.id} hideHeader />}
    </div>
  );
}
