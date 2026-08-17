"use client";

import { useState } from "react";
import { PIPELINES, TOOLS } from "./mockData";
import type { JobPreview, PipelineStage, ScanProfile, ToolDef } from "../../types";

type QueueSpec = {
  tool: string;
  source: string;
  config: Record<string, unknown>;
  targets: number;
  yieldKind: string;
  interval?: string; // "hourly" | "daily" | "weekly" — undefined = run once
};

const RECURRENCE = ["once", "hourly", "daily", "weekly"] as const;

type ComposerProps = {
  accent: string;
  onQueue: (spec: QueueSpec) => void;
  onPipeline: (stages: PipelineStage[]) => void;
  onPreview: (spec: { tool: string; source: string; config: Record<string, unknown> }) => Promise<JobPreview | null>;
  profiles: ScanProfile[];
  onSaveProfile: (spec: { tool: string; source: string; config: Record<string, unknown> }, name: string) => void;
  onDeleteProfile: (id: string) => void;
  runnerOnline: boolean;
  scopeCount: number;
  reconCount: number;
  programName: string;
};

function ToolPick({ tool, selected, accent, onClick }: {
  tool: ToolDef; selected: boolean; accent: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick}
      aria-pressed={selected}
      aria-label={`Select ${tool.label}`}
      className="flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition"
      style={{
        borderColor: selected ? `${accent}80` : "#2e2e2e",
        backgroundColor: selected ? `${accent}12` : "#161616",
      }}>
      <span className="mt-0.5 font-mono text-base leading-none" style={{ color: selected ? accent : "#52525b" }}>{tool.glyph}</span>
      <span className="min-w-0">
        <span className="block font-mono text-[13px] font-semibold" style={{ color: selected ? "#f1f5f9" : "#cbd5e1" }}>{tool.label}</span>
        <span className="mt-0.5 block text-[10px] leading-tight text-[#52525b]">{tool.blurb}</span>
      </span>
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</label>
      {children}
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] transition focus:outline-none";

type ComposerPropsWithTool = ComposerProps & { initialTool?: string };

export default function Composer({ accent, onQueue, onPipeline, onPreview, profiles, onSaveProfile, onDeleteProfile, runnerOnline, scopeCount, reconCount, programName, initialTool }: ComposerPropsWithTool) {
  // Pipelines and tools share one mutually-exclusive selection — picking either
  // clears the other. `toolId` is kept across the toggle so returning to a tool
  // restores the config that was already typed into it.
  // null = a tool is selected. Otherwise the id of the chosen pipeline.
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  // Stage inclusion, keyed pipeline → tool_type. Scoped per pipeline because
  // httpx appears in more than one — excluding it from one must not touch the other.
  const [stageOn, setStageOn] = useState<Record<string, Record<string, boolean>>>(
    () => Object.fromEntries(
      PIPELINES.map((p) => [p.id, Object.fromEntries(p.stages.map((s) => [s.tool_type, true]))]),
    ),
  );
  const [toolId, setToolId] = useState(initialTool && initialTool in TOOLS ? initialTool : "nuclei");
  const [source, setSource] = useState(() => {
    const t = TOOLS[initialTool && initialTool in TOOLS ? initialTool : "nuclei"];
    return t.sources[0];
  });
  const [cfg, setCfg] = useState<Record<string, unknown>>({ severity: "high,critical", templates: "cves,exposures" });
  const [recurrence, setRecurrence] = useState<(typeof RECURRENCE)[number]>("once");
  const [preview, setPreview] = useState<JobPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileName, setProfileName] = useState("");

  const tool = TOOLS[toolId];

  function pick(id: string) {
    setPipelineId(null);
    setToolId(id);
    const t = TOOLS[id];
    setSource(t.sources[0]);
    const init: Record<string, unknown> = {};
    t.config.forEach((c) => { if (c.type === "toggle") init[c.key] = c.default ?? false; });
    setCfg(init);
    setPreview(null);
  }

  function pickPipeline(id: string) {
    setPipelineId(id);
    // Stages carry their own source and config, and /schedules is single-tool
    // only, so a pipeline can only run once. Reset it rather than showing a
    // recurrence that would be silently dropped.
    setRecurrence("once");
    setPreview(null);
  }

  const sourceCount = source === "scope" ? scopeCount : reconCount;

  const pipeline = pipelineId ? PIPELINES.find((p) => p.id === pipelineId) ?? null : null;

  // Order is preserved from the pipeline definition; the backend relinks
  // depends_on sequentially over whatever it receives, so dropping a middle
  // stage chains the survivors rather than leaving a dangling wait.
  const activeStages = pipeline
    ? pipeline.stages.filter((s) => stageOn[pipeline.id]?.[s.tool_type])
    : [];

  function toggleStage(toolType: string) {
    if (!pipeline) return;
    setStageOn((prev) => ({
      ...prev,
      [pipeline.id]: { ...prev[pipeline.id], [toolType]: !prev[pipeline.id]?.[toolType] },
    }));
  }

  function submit() {
    if (pipeline) {
      if (activeStages.length === 0) return;
      const list = activeStages.map((s) => `  ${s.tool_type} (${s.target_source})`).join("\n");
      const tail = activeStages.length > 1 ? ", each waiting on the one before it" : "";
      if (!confirm(`Queue ${pipeline.label}?\n\n${list}\n\n${activeStages.length} job${activeStages.length === 1 ? "" : "s"} will be queued${tail}.`)) return;
      onPipeline(activeStages);
      return;
    }
    onQueue({
      tool: toolId, source, config: { ...cfg }, targets: sourceCount, yieldKind: tool.yields,
      interval: recurrence === "once" ? undefined : recurrence,
    });
  }

  async function runPreview() {
    setPreviewing(true);
    try {
      const result = await onPreview({ tool: toolId, source, config: { ...cfg } });
      setPreview(result);
    } finally {
      setPreviewing(false);
    }
  }

  function loadProfile(p: ScanProfile) {
    if (p.tool_type in TOOLS) {
      setPipelineId(null);
      setToolId(p.tool_type);
      setSource(p.target_source);
      setCfg({ ...p.config });
      setPreview(null);
    }
  }

  function saveProfile() {
    const name = profileName.trim();
    if (!name) return;
    onSaveProfile({ tool: toolId, source, config: { ...cfg } }, name);
    setProfileName("");
    setSavingProfile(false);
  }

  const toolProfiles = profiles.filter((p) => p.tool_type === toolId);

  return (
    <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Queue a Job</h3>
        <span className="font-mono text-[10px] text-[#52525b]">{programName}</span>
      </div>

      {/* Pipelines are selections like any tool, not actions. Selecting one
          clears the tool highlight so only one thing is ever chosen. */}
      <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Pipelines</label>
      <div className="mb-3 grid gap-2">
        {PIPELINES.map((p) => {
          const on = pipelineId === p.id;
          // The selected card's subtitle reflects the current stage selection so
          // it never advertises a chain the operator has edited away.
          const chain = on
            ? (activeStages.length === 0
                ? "no stages selected"
                : activeStages.map((s) => s.tool_type).join(" → "))
            : p.stages.map((s) => s.tool_type).join(" → ");
          return (
            <button
              key={p.id}
              onClick={() => pickPipeline(p.id)}
              aria-pressed={on}
              aria-label={`Select ${p.label}`}
              className="flex w-full items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition"
              style={{
                borderColor: on ? `${accent}80` : "#2e2e2e",
                backgroundColor: on ? `${accent}12` : "#161616",
              }}>
              <span className="mt-0.5 font-mono text-base leading-none" style={{ color: on ? accent : "#52525b" }}>⚡</span>
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[13px] font-semibold" style={{ color: on ? "#f1f5f9" : "#cbd5e1" }}>{p.label}</span>
                <span className="mt-0.5 block text-[10px] leading-tight text-[#52525b]">{chain}</span>
                {!on && <span className="mt-0.5 block text-[10px] leading-tight text-[#3a3a3a]">{p.blurb}</span>}
              </span>
              <span className="mt-0.5 font-mono text-[10px] leading-none" style={{ color: on ? accent : "#52525b" }}>
                {on ? "▾" : "▸"}
              </span>
            </button>
          );
        })}
      </div>

      <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Tools</label>
      <div className="grid gap-2">
        {Object.values(TOOLS).map((t) => (
          <ToolPick key={t.id} tool={t} selected={!pipeline && toolId === t.id} accent={accent} onClick={() => pick(t.id)} />
        ))}
      </div>

      <div className="mt-4 space-y-3">
        {pipeline ? (
          /* Include/exclude stages. Each carries its own source and config, so
             there is nothing else to configure here. */
          <Field label="Stages">
            <ol className="space-y-1.5">
              {pipeline.stages.map((s) => {
                const on = !!stageOn[pipeline.id]?.[s.tool_type];
                // "waits on" names the previous *included* stage — dropping a
                // middle stage relinks the chain rather than dangling.
                const idx = activeStages.findIndex((a) => a.tool_type === s.tool_type);
                const waitsOn = idx > 0 ? activeStages[idx - 1].tool_type : null;
                return (
                  <li key={s.tool_type}>
                    <button
                      onClick={() => toggleStage(s.tool_type)}
                      aria-pressed={on}
                      aria-label={`${on ? "Exclude" : "Include"} ${s.tool_type}`}
                      className="flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left transition"
                      style={{
                        borderColor: on ? `${accent}80` : "#2e2e2e",
                        backgroundColor: on ? `${accent}12` : "#161616",
                        opacity: on ? 1 : 0.55,
                      }}>
                      <span className="font-mono text-[10px] leading-none" style={{ color: on ? accent : "#52525b" }}>
                        {on ? "✓" : "○"}
                      </span>
                      <span className="font-mono text-base leading-none" style={{ color: on ? accent : "#52525b" }}>{TOOLS[s.tool_type]?.glyph}</span>
                      <span className="font-mono text-[11px]" style={{ color: on ? "#cbd5e1" : "#52525b" }}>{s.tool_type}</span>
                      <span className="font-mono text-[10px] text-[#52525b]">
                        {s.target_source} · {s.target_source === "scope" ? scopeCount : reconCount}
                      </span>
                      {waitsOn && <span className="ml-auto font-mono text-[10px] text-[#52525b]">waits on {waitsOn}</span>}
                    </button>
                  </li>
                );
              })}
            </ol>
            {activeStages.length === 0 && (
              <p className="mt-1.5 font-mono text-[10px] text-[#f59e0b]">include at least one stage to queue</p>
            )}
          </Field>
        ) : (
        <Field label="Target Source">
          <div className="flex gap-1.5">
            {tool.sources.map((s) => (
              <button key={s} onClick={() => setSource(s)}
                className="flex-1 rounded-md border px-2 py-1.5 font-mono text-[11px] transition"
                style={{
                  borderColor: source === s ? `${accent}80` : "#2e2e2e",
                  color: source === s ? accent : "#94a3b8",
                  backgroundColor: source === s ? `${accent}12` : "#161616",
                }}>
                {s} · {s === "scope" ? scopeCount : reconCount}
              </button>
            ))}
          </div>
        </Field>
        )}

        {!pipeline && (
        <div className="grid grid-cols-2 gap-3">
          {tool.config.map((c) =>
            c.type === "toggle" ? (
              <Field key={c.key} label={c.label}>
                <button
                  onClick={() => setCfg({ ...cfg, [c.key]: !cfg[c.key] })}
                  className="flex w-full items-center justify-between rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2">
                  <span className="font-mono text-xs text-[#94a3b8]">{cfg[c.key] ? "enabled" : "disabled"}</span>
                  <span className="relative h-4 w-7 rounded-full transition" style={{ backgroundColor: cfg[c.key] ? accent : "#2e2e2e" }}>
                    <span className="absolute top-0.5 h-3 w-3 rounded-full bg-[#0d0d0d] transition-all"
                      style={{ left: cfg[c.key] ? "14px" : "2px" }} />
                  </span>
                </button>
              </Field>
            ) : (
              <Field key={c.key} label={c.label}>
                <input
                  className={inputCls}
                  placeholder={c.placeholder}
                  type={c.type === "number" ? "number" : "text"}
                  value={(cfg[c.key] as string) ?? ""}
                  onChange={(e) => setCfg({ ...cfg, [c.key]: e.target.value })}
                  onFocus={(e) => { e.target.style.borderColor = accent; }}
                  onBlur={(e) => { e.target.style.borderColor = "#2e2e2e"; }}
                />
              </Field>
            )
          )}
        </div>
        )}

        {/* Recurrence is single-tool only — /schedules stores one tool_type, so a
            recurring pipeline would silently drop its later stages. */}
        {!pipeline && (
        <Field label="Recurrence">
          <div className="flex gap-1.5">
            {RECURRENCE.map((r) => (
              <button key={r} onClick={() => setRecurrence(r)}
                className="flex-1 rounded-md border px-2 py-1.5 font-mono text-[11px] transition"
                style={{
                  borderColor: recurrence === r ? `${accent}80` : "#2e2e2e",
                  color: recurrence === r ? accent : "#94a3b8",
                  backgroundColor: recurrence === r ? `${accent}12` : "#161616",
                }}>
                {r}
              </button>
            ))}
          </div>
        </Field>
        )}

        {/* Saved profiles: load config in one click, or save the current config.
            Profiles are per-tool, so they don't apply to a pipeline. */}
        {!pipeline && (
        <Field label="Saved Profiles">
          <div className="space-y-1.5">
            {toolProfiles.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {toolProfiles.map((p) => (
                  <span key={p.id}
                    className="group flex items-center gap-1 rounded-md border border-[#2e2e2e] bg-[#161616] px-2 py-1 font-mono text-[11px] text-[#94a3b8]">
                    <button onClick={() => loadProfile(p)} className="hover:text-[#f1f5f9]" title="Load this profile">{p.name}</button>
                    <button onClick={() => onDeleteProfile(p.id)} className="text-[#52525b] hover:text-[#f87171]" title="Delete profile">×</button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="font-mono text-[10px] text-[#3a3a3a]">no saved {tool.label} profiles yet</p>
            )}
            {savingProfile ? (
              <div className="flex gap-1.5">
                <input autoFocus className={inputCls} placeholder="profile name"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveProfile(); if (e.key === "Escape") setSavingProfile(false); }} />
                <button onClick={saveProfile}
                  className="rounded-md px-3 py-1.5 font-mono text-[11px] font-semibold text-[#161616]"
                  style={{ backgroundColor: accent }}>save</button>
              </div>
            ) : (
              <button onClick={() => setSavingProfile(true)}
                className="font-mono text-[10px] text-[#52525b] transition hover:text-[#94a3b8]">
                + save current config as profile
              </button>
            )}
          </div>
        </Field>
        )}

        <div className="flex items-center gap-2 rounded-lg border border-[#2e2e2e] bg-[#0d0d0d] px-3 py-2">
          <span className="font-mono text-base leading-none" style={{ color: accent }}>{pipeline ? "⚡" : tool.glyph}</span>
          {pipeline ? (
            activeStages.length === 0 ? (
              <p className="font-mono text-[11px] leading-tight text-[#52525b]">no stages selected</p>
            ) : (
              <p className="font-mono text-[11px] leading-tight text-[#52525b]">
                <span className="text-[#94a3b8]">
                  {activeStages.length} {activeStages.length === 1 ? "job" : "chained jobs"}
                </span>
                {" starting from "}
                <span className="text-[#94a3b8]">
                  {activeStages[0].target_source === "scope" ? scopeCount : reconCount}
                </span>
                {` ${activeStages[0].target_source} targets → yields `}
                <span style={{ color: accent }}>{TOOLS[activeStages[activeStages.length - 1].tool_type]?.yields}</span>
              </p>
            )
          ) : (
            <p className="font-mono text-[11px] leading-tight text-[#52525b]">
              <span className="text-[#94a3b8]">{tool.label}</span>{" on "}
              <span className="text-[#94a3b8]">{sourceCount}</span>{" "}{source} targets → yields{" "}
              <span style={{ color: accent }}>{tool.yields}</span>
              {recurrence !== "once" && <>{" · repeats "}<span style={{ color: accent }}>{recurrence}</span></>}
            </p>
          )}
        </div>

        {/* Dry-run preview of resolved targets */}
        {preview && (
          <div className="rounded-lg border border-[#2e2e2e] bg-[#0d0d0d] px-3 py-2">
            <p className="font-mono text-[11px] text-[#94a3b8]">
              <span style={{ color: accent }}>{preview.count}</span> target{preview.count === 1 ? "" : "s"} resolved from {preview.target_source}
            </p>
            {preview.sample.length > 0 && (
              <p className="mt-1 break-all font-mono text-[10px] leading-relaxed text-[#52525b]">
                {preview.sample.join("  ·  ")}{preview.truncated && " …"}
              </p>
            )}
          </div>
        )}

        <div className="flex gap-2">
          {/* Preview resolves one tool against one source; a pipeline's later
              stages consume targets that don't exist until earlier ones run. */}
          <button onClick={runPreview} disabled={previewing || !!pipeline}
            title={pipeline ? "Preview applies to a single tool, not a chain" : undefined}
            className="rounded-md border px-4 py-2.5 text-sm font-semibold transition active:scale-[0.98] disabled:opacity-50"
            style={{ borderColor: "#2e2e2e", color: "#94a3b8" }}>
            {previewing ? "…" : "Preview"}
          </button>
          <button onClick={submit}
            disabled={!!pipeline && activeStages.length === 0}
            className="flex-1 rounded-md px-4 py-2.5 text-sm font-semibold text-[#161616] transition active:scale-[0.98] disabled:opacity-50"
            style={{ backgroundColor: accent }}>
            {pipeline ? "Queue Pipeline" : recurrence === "once" ? "Queue Job" : `Schedule ${recurrence}`}
          </button>
        </div>

        {!runnerOnline && (
          <p className="text-center font-mono text-[10px] text-[#f59e0b]">
            runner offline — job will hold in queue until reconnect
          </p>
        )}
      </div>
    </div>
  );
}
