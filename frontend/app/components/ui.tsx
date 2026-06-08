"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SeverityBadge({ severity }: { severity: string }) {
  const s = severity?.toLowerCase();
  const color =
    s === "critical" ? "bg-red-950 text-red-400 border-red-800" :
    s === "high"     ? "bg-orange-950 text-orange-400 border-orange-800" :
    s === "medium"   ? "bg-yellow-950 text-yellow-400 border-yellow-800" :
    s === "low"      ? "bg-blue-950 text-blue-400 border-blue-800" :
                       "bg-[#161616] text-[#6e6a86] border-[#2a2a3e]";
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${color}`}>
      {severity || "info"}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const s = status?.toLowerCase();
  const color =
    s === "validated" || s === "accepted"   ? "bg-emerald-950 text-emerald-400 border-emerald-800" :
    s === "in_progress" || s === "triaged"  ? "bg-emerald-950 text-emerald-400 border-emerald-800" :
    s === "closed" || s === "resolved"      ? "bg-[#161616] text-[#6e6a86] border-[#2a2a3e]" :
                                              "bg-[#161616] text-[#6b7280] border-[#2a2a3e]";
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${color}`}>
      {status || "—"}
    </span>
  );
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
      <h3 className="mb-5 text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{title}</h3>
      {children}
    </div>
  );
}

export function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="border-b border-[#2e2e2e] pb-5">
      <h2 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">{title}</h2>
      <p className="mt-1.5 text-sm text-[#52525b]">{description}</p>
    </div>
  );
}

export function Input({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</label>
      <input
        className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function SelectField({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div>
      <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</label>
      <select
        className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

export function Textarea({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</label>
        <div className="flex rounded border border-[#2e2e2e] bg-[#161616] p-0.5">
          {(["edit", "preview"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={`rounded px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider transition ${mode === m ? "bg-[#2e2e2e] text-[#f1f5f9]" : "text-[#52525b] hover:text-[#6b7280]"}`}>
              {m}
            </button>
          ))}
        </div>
      </div>
      {mode === "edit" && (
        <textarea rows={4} placeholder="Supports markdown…"
          className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 font-mono text-sm text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:border-[#f59e0b] focus:outline-none"
          value={value} onChange={(e) => onChange(e.target.value)} />
      )}
      {mode === "preview" && (
        <div className="min-h-[104px] w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2">
          {value.trim() ? (
            <div className="text-sm text-[#6b7280] leading-relaxed space-y-2
              [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:text-[#f1f5f9]
              [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-[#f1f5f9]
              [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-[#94a3b8]
              [&_strong]:text-[#f1f5f9]
              [&_a]:text-[#89b4fa] [&_a]:no-underline hover:[&_a]:underline
              [&_code]:rounded [&_code]:bg-[#2e2e2e] [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:text-[#a6e3a1] [&_code]:font-mono
              [&_pre]:rounded-md [&_pre]:border [&_pre]:border-[#2e2e2e] [&_pre]:bg-[#161616] [&_pre]:p-3 [&_pre]:text-xs
              [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4
              [&_li]:text-[#6b7280]
              [&_blockquote]:border-l-2 [&_blockquote]:border-[#f59e0b]/30 [&_blockquote]:pl-3 [&_blockquote]:text-[#52525b]
              [&_hr]:border-[#2e2e2e]">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
            </div>
          ) : (
            <p className="text-xs text-[#3a3a3a] italic">Nothing to preview.</p>
          )}
        </div>
      )}
    </div>
  );
}

export function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-4 last:mb-0">
      <div className="text-[9px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</div>
      <div className="mt-1 text-sm text-[#94a3b8]">{value}</div>
    </div>
  );
}

export function ListCard({ title, subtitle, onDelete }: { title: string; subtitle: string; onDelete: () => void }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-[#2e2e2e] bg-[#161616] px-4 py-3">
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-[#f1f5f9]">{title}</div>
        <div className="mt-0.5 truncate text-xs text-[#52525b]">{subtitle}</div>
      </div>
      <DangerButton onClick={onDelete} label="Delete" small />
    </div>
  );
}

export function PrimaryButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} className="rounded-md bg-[#f59e0b] px-4 py-2 text-sm font-semibold text-[#161616] transition hover:bg-[#fbbf24] active:scale-[0.98]">
      {label}
    </button>
  );
}

export function DangerButton({ onClick, label, small }: { onClick: () => void; label: string; small?: boolean }) {
  return (
    <button onClick={onClick} className={`flex-shrink-0 rounded-md border border-red-900/50 bg-red-950/30 font-semibold text-red-400 transition hover:bg-red-950/60 hover:text-red-300 active:scale-[0.98] ${small ? "px-2.5 py-1 text-xs" : "px-4 py-2 text-sm"}`}>
      {label}
    </button>
  );
}
