"use client";

import { useState } from "react";
import { Program } from "../types";
import ReconSection from "./ReconSection";
import ScanningSection from "./ScanningSection";
import ManualSection from "./ManualSection";

type ReviewTab = "recon" | "scans" | "manual";

const TABS: { id: ReviewTab; label: string }[] = [
  { id: "recon",  label: "Recon"  },
  { id: "scans",  label: "Scans"  },
  { id: "manual", label: "Manual" },
];

export default function ReviewSection({ program }: { program: Program }) {
  const [activeTab, setActiveTab] = useState<ReviewTab>("recon");

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2e2e2e] pb-5">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">Review</h2>
          <p className="mt-1.5 text-sm text-[#52525b]">
            Explore recon data, scan results, and manual test notes.
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

      {activeTab === "recon"  && <ReconSection    programId={program.id} hideHeader />}
      {activeTab === "scans"  && <ScanningSection programId={program.id} hideHeader />}
      {activeTab === "manual" && <ManualSection   program={program}      hideHeader />}
    </div>
  );
}
