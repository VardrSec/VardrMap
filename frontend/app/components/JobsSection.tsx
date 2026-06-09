"use client";

import { useCallback, useEffect, useState } from "react";
import { ScanJob } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, SelectField, PrimaryButton, SectionHeader } from "./ui";

type JobForm = {
  tool_type: string;
  target_source: string;
  config: {
    status_code: string;
    limit: string;
    severity: string;
    templates: string;
  };
};

const EMPTY_FORM: JobForm = {
  tool_type: "httpx",
  target_source: "scope",
  config: { status_code: "", limit: "", severity: "", templates: "" },
};

const STATUS_COLORS: Record<string, string> = {
  pending:  "text-[#94a3b8] border-[#3a3a3a]",
  running:  "text-[#f59e0b] border-[#f59e0b]/40",
  done:     "text-[#a6e3a1] border-[#a6e3a1]/30",
  failed:   "text-[#f87171] border-[#f87171]/30",
};

function JobStatusChip({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "text-[#52525b] border-[#2e2e2e]";
  return (
    <span className={`rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest ${cls}`}>
      {status}
    </span>
  );
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

export default function JobsSection({ programId }: { programId: string }) {
  const { authFetch, setMessage } = useAppContext();
  const [jobs,    setJobs]    = useState<ScanJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [form,    setForm]    = useState<JobForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch(`/programs/${programId}/jobs`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setJobs(Array.isArray(data?.jobs) ? data.jobs : []);
    } catch { setMessage("Failed to load jobs."); } finally { setLoading(false); }
  }, [programId, authFetch, setMessage]);

  useEffect(() => { void loadJobs(); }, [loadJobs]);

  async function createJob() {
    setSubmitting(true);
    try {
      const config: Record<string, unknown> = {};
      if (form.config.status_code) config.status_code = Number(form.config.status_code);
      if (form.config.limit)       config.limit       = Number(form.config.limit);
      if (form.config.severity)    config.severity    = form.config.severity;
      if (form.config.templates)   config.templates   = form.config.templates.split(",").map((s) => s.trim()).filter(Boolean);

      const res = await authFetch(`/programs/${programId}/jobs`, {
        method: "POST",
        body: JSON.stringify({
          tool_type:     form.tool_type,
          target_source: form.target_source,
          config,
        }),
      });
      if (!res.ok) throw new Error();
      setForm(EMPTY_FORM);
      await loadJobs();
      setMessage("Job queued. Run `vardrrunner jobs run` to execute.");
    } catch { setMessage("Failed to queue job."); } finally { setSubmitting(false); }
  }

  const pendingCount = jobs.filter((j) => j.status === "pending").length;
  const runningCount = jobs.filter((j) => j.status === "running").length;

  return (
    <div className="space-y-7">
      <SectionHeader
        title="Scan Jobs"
        description="Queue scan jobs for VardrRunner to execute on your machine."
      />

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="New Scan Job">
          <div className="grid gap-3">
            <SelectField
              label="Tool"
              value={form.tool_type}
              onChange={(v) => setForm({ ...form, tool_type: v })}
              options={["httpx", "nuclei"]}
            />
            <SelectField
              label="Target Source"
              value={form.target_source}
              onChange={(v) => setForm({ ...form, target_source: v })}
              options={["scope", "recon"]}
            />

            {form.tool_type === "httpx" && (
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
                    Status Code Filter
                  </label>
                  <input
                    type="number"
                    placeholder="e.g. 200"
                    value={form.config.status_code}
                    onChange={(e) => setForm({ ...form, config: { ...form.config, status_code: e.target.value } })}
                    className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
                    Limit
                  </label>
                  <input
                    type="number"
                    placeholder="e.g. 500"
                    value={form.config.limit}
                    onChange={(e) => setForm({ ...form, config: { ...form.config, limit: e.target.value } })}
                    className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                  />
                </div>
              </div>
            )}

            {form.tool_type === "nuclei" && (
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
                    Severity Filter
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. high,critical"
                    value={form.config.severity}
                    onChange={(e) => setForm({ ...form, config: { ...form.config, severity: e.target.value } })}
                    className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">
                    Templates (comma-sep)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. cves,exposures"
                    value={form.config.templates}
                    onChange={(e) => setForm({ ...form, config: { ...form.config, templates: e.target.value } })}
                    className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-2.5 py-2 text-sm text-[#f1f5f9] transition focus:border-[#f59e0b] focus:outline-none"
                  />
                </div>
              </div>
            )}

            <div className="rounded-lg border border-[#2e2e2e] bg-[#0d0d0d] px-3 py-2.5 text-xs text-[#52525b]">
              Run <span className="font-mono text-[#94a3b8]">vardrrunner jobs run</span> to pick up pending jobs.
            </div>

            <PrimaryButton onClick={createJob} label={submitting ? "Queuing…" : "Queue Job"} />
          </div>
        </Panel>

        <Panel title={`Job Queue${jobs.length > 0 ? ` (${jobs.length})` : ""}`}>
          {pendingCount > 0 && (
            <p className="mb-3 text-xs text-[#f59e0b]">
              {pendingCount} pending — run <span className="font-mono">vardrrunner jobs run</span> to execute
              {runningCount > 0 && `, ${runningCount} running`}
            </p>
          )}

          {loading ? (
            <p className="text-sm text-[#3a3a3a]">Loading…</p>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">No jobs yet.</p>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <div key={job.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-[#f1f5f9]">
                          {job.tool_type}
                        </span>
                        <span className="text-[#3a3a3a]">·</span>
                        <span className="text-xs text-[#52525b]">{job.target_source}</span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <JobStatusChip status={job.status} />
                        <span className="font-mono text-[10px] text-[#3a3a3a]">{fmtDate(job.created_at)}</span>
                        {job.status === "done" && job.completed_at && (
                          <span className="font-mono text-[10px] text-[#a6e3a1]">done {fmtDate(job.completed_at)}</span>
                        )}
                      </div>
                      {job.error_message && (
                        <p className="mt-1.5 font-mono text-xs text-[#f87171]">{job.error_message}</p>
                      )}
                      {Object.keys(job.config).length > 0 && (
                        <p className="mt-1 font-mono text-[10px] text-[#3a3a3a]">
                          {Object.entries(job.config).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : v}`).join("  ")}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              <button
                onClick={loadJobs}
                className="w-full rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]"
              >
                Refresh
              </button>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
