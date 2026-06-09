"use client";

import { RUNNER, fmtAgo } from "./mockData";

type RunnerTool = { id: string; version: string; ok: boolean };

function ToolChip({ tool }: { tool: RunnerTool }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-[#2e2e2e] bg-[#161616] px-2 py-1">
      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full"
        style={{ backgroundColor: tool.ok ? "#a6e3a1" : "#f87171" }} />
      <span className="font-mono text-[11px] text-[#cbd5e1]">{tool.id}</span>
      <span className="font-mono text-[10px] text-[#52525b]">{tool.version}</span>
    </div>
  );
}

function LinkWire({ online, accent, busy, pulseKey }: {
  online: boolean; accent: string; busy: boolean; pulseKey: number;
}) {
  return (
    <div className="relative flex h-full min-h-[96px] flex-col items-center justify-center px-2">
      <div className="relative h-[2px] w-full overflow-hidden rounded-full" style={{ backgroundColor: "#242424" }}>
        {online && (
          <div
            className="wire-flow-anim absolute inset-y-0 left-0 w-full"
            style={{
              backgroundImage: `repeating-linear-gradient(90deg, ${accent} 0, ${accent} 6px, transparent 6px, transparent 14px)`,
              opacity: busy ? 0.95 : 0.5,
              animation: `wireFlow ${busy ? "0.6s" : "1.4s"} linear infinite`,
            }}
          />
        )}
      </div>
      {online && (
        <div
          key={pulseKey}
          className="packet-run-anim absolute top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full"
          style={{
            backgroundColor: accent,
            boxShadow: `0 0 10px 2px ${accent}`,
            animation: "packetRun 1.1s ease-in-out",
          }}
        />
      )}
      <div className="absolute -bottom-1 flex items-center gap-1.5">
        <span className="h-1 w-1 rounded-full" style={{ backgroundColor: online ? accent : "#3a3a3a" }} />
        <span className="font-mono text-[9px] uppercase tracking-widest"
          style={{ color: online ? accent : "#52525b" }}>
          {online ? (busy ? "streaming" : "linked") : "offline"}
        </span>
      </div>
    </div>
  );
}

function Node({ label, sub, glyph, glyphColor, active, children }: {
  label: string; sub: string; glyph: string; glyphColor: string;
  active: boolean; children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] font-mono text-base"
          style={{ color: glyphColor }}>{glyph}</div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-[#f1f5f9]">{label}</div>
          <div className="truncate font-mono text-[10px] text-[#52525b]">{sub}</div>
        </div>
        <span className="ml-auto h-1.5 w-1.5 flex-shrink-0 rounded-full"
          style={{ backgroundColor: active ? "#a6e3a1" : "#52525b", boxShadow: active ? "0 0 6px #a6e3a1" : "none" }} />
      </div>
      {children}
    </div>
  );
}

function BridgeStrip({ accent, runnerOnline, autoRun, queueDepth, runningCount, busy, onExpand }: {
  accent: string; runnerOnline: boolean; autoRun: boolean; queueDepth: number;
  runningCount: number; busy: boolean; onExpand: () => void;
}) {
  const linkColor = runnerOnline ? (busy ? accent : "#a6e3a1") : "#52525b";
  return (
    <button onClick={onExpand}
      className="group flex w-full items-center gap-3 rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] px-4 py-2.5 text-left transition hover:border-[#3a3a3a]">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Execution Link</span>
      <span className="flex items-center gap-1.5">
        <span className="font-mono text-xs" style={{ color: accent }}>⬡</span>
        <span className="hidden font-mono text-[11px] text-[#94a3b8] sm:inline">VardrMap</span>
      </span>
      <span className="flex items-center gap-1">
        <span className="h-[2px] w-5 rounded-full" style={{ backgroundColor: linkColor, opacity: 0.6 }} />
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: linkColor, boxShadow: runnerOnline ? `0 0 6px ${linkColor}` : "none" }} />
        <span className="h-[2px] w-5 rounded-full" style={{ backgroundColor: linkColor, opacity: 0.6 }} />
      </span>
      <span className="flex items-center gap-1.5">
        <span className="font-mono text-xs" style={{ color: runnerOnline ? "#a6e3a1" : "#52525b" }}>▣</span>
        <span className="hidden font-mono text-[11px] text-[#94a3b8] sm:inline">{RUNNER.user}@{RUNNER.host}</span>
      </span>
      <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color: linkColor }}>
        {runnerOnline ? (busy ? "streaming" : "linked") : "offline"}
      </span>
      <span className="ml-auto flex items-center gap-3">
        <span className="hidden font-mono text-[10px] text-[#52525b] md:inline">{queueDepth} queued · {runningCount} running</span>
        {autoRun && (
          <span className="hidden items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider lg:flex" style={{ color: accent }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: accent }} />auto-run
          </span>
        )}
        <span className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-[#52525b] transition group-hover:text-[#94a3b8]">
          expand
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </span>
      </span>
    </button>
  );
}

export type BridgeProps = {
  accent: string;
  runnerOnline: boolean;
  autoRun: boolean;
  lastPoll: string;
  queueDepth: number;
  runningCount: number;
  busy: boolean;
  pulseKey: number;
  collapsed: boolean;
  onToggleRunner: () => void;
  onToggleAuto: () => void;
  onToggleCollapse: () => void;
};

export default function Bridge({
  accent, runnerOnline, autoRun, lastPoll, queueDepth, runningCount,
  busy, pulseKey, collapsed, onToggleRunner, onToggleAuto, onToggleCollapse,
}: BridgeProps) {
  if (collapsed) {
    return (
      <BridgeStrip
        accent={accent} runnerOnline={runnerOnline} autoRun={autoRun}
        queueDepth={queueDepth} runningCount={runningCount} busy={busy}
        onExpand={onToggleCollapse}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
      <div className="mb-4 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Execution Link</span>
        <div className="flex items-center gap-2">
          <button onClick={onToggleAuto}
            className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition"
            style={{
              borderColor: autoRun ? `${accent}66` : "#2e2e2e",
              color: autoRun ? accent : "#52525b",
              backgroundColor: autoRun ? `${accent}14` : "transparent",
            }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: autoRun ? accent : "#3a3a3a" }} />
            auto-run {autoRun ? "on" : "off"}
          </button>
          <button onClick={onToggleRunner}
            className="rounded-md border border-[#2e2e2e] px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-[#94a3b8] transition hover:border-[#3a3a3a] hover:text-[#f1f5f9]">
            {runnerOnline ? "disconnect" : "connect"}
          </button>
          <button onClick={onToggleCollapse}
            className="flex items-center gap-1 rounded-md border border-[#2e2e2e] px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
            hide
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="18 15 12 9 6 15" />
            </svg>
          </button>
        </div>
      </div>

      <div className="grid items-stretch gap-3 lg:grid-cols-[1fr_minmax(120px,0.7fr)_1.25fr]">
        {/* Cloud node */}
        <Node label="VardrMap" sub="cloud · command center" glyph="⬡" glyphColor={accent} active={true}>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] px-2.5 py-1.5">
              <div className="font-mono text-lg font-bold leading-none" style={{ color: accent }}>{queueDepth}</div>
              <div className="mt-1 text-[9px] uppercase tracking-widest text-[#52525b]">queued</div>
            </div>
            <div className="rounded-lg border border-[#2e2e2e] bg-[#1a1a1a] px-2.5 py-1.5">
              <div className="font-mono text-lg font-bold leading-none text-[#f1f5f9]">{runningCount}</div>
              <div className="mt-1 text-[9px] uppercase tracking-widest text-[#52525b]">dispatched</div>
            </div>
          </div>
        </Node>

        {/* Link wire */}
        <LinkWire online={runnerOnline} accent={accent} busy={busy} pulseKey={pulseKey} />

        {/* Runner node */}
        <Node
          label="VardrRunner"
          sub={`${RUNNER.user}@${RUNNER.host} · ${RUNNER.version}`}
          glyph="▣"
          glyphColor={runnerOnline ? "#a6e3a1" : "#52525b"}
          active={runnerOnline}
        >
          {runnerOnline ? (
            <>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {RUNNER.tools.map((t) => <ToolChip key={t.id} tool={t} />)}
              </div>
              <div className="mt-2.5 flex items-center justify-between font-mono text-[10px] text-[#52525b]">
                <span>{RUNNER.os}</span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1 w-1 animate-pulse rounded-full bg-[#a6e3a1]" />
                  poll {fmtAgo(lastPoll)}
                </span>
              </div>
            </>
          ) : (
            <div className="mt-3 rounded-lg border border-dashed border-[#2e2e2e] bg-[#1a1a1a] px-3 py-3 text-center">
              <p className="font-mono text-[11px] text-[#52525b]">runner offline</p>
              <p className="mt-1 font-mono text-[10px] text-[#3a3a3a]">$ vardrrunner login vardrmap</p>
            </div>
          )}
        </Node>
      </div>
    </div>
  );
}
