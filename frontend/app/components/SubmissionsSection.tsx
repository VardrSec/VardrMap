"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { Finding, Engagement, Submission } from "../types";
import { useAppContext } from "../context/AppContext";

type SubmissionStatus = "submitted" | "triaged" | "accepted" | "duplicate" | "na" | "paid" | "rejected";

const STATUS_OPTIONS: SubmissionStatus[] = [
  "submitted", "triaged", "accepted", "duplicate", "na", "paid", "rejected",
];

const STATUS_COLOR: Record<string, string> = {
  submitted: "text-[#89b4fa] border-[#89b4fa]/30 bg-[#89b4fa]/8",
  triaged:   "text-[#f9e2af] border-[#f9e2af]/30 bg-[#f9e2af]/8",
  accepted:  "text-[#a6e3a1] border-[#a6e3a1]/30 bg-[#a6e3a1]/8",
  duplicate: "text-[#7f849c] border-[#7f849c]/30 bg-[#7f849c]/8",
  na:        "text-[#7f849c] border-[#7f849c]/30 bg-[#7f849c]/8",
  paid:      "text-[#a6e3a1] border-[#a6e3a1]/30 bg-[#a6e3a1]/8",
  rejected:  "text-[#f87171] border-[#f87171]/30 bg-[#f87171]/8",
};

const SEV_COLOR: Record<string, string> = {
  critical: "text-[#f38ba8]",
  high:     "text-[#fab387]",
  medium:   "text-[#f9e2af]",
  low:      "text-[#89b4fa]",
  info:     "text-[#74c7ec]",
};

const EMPTY_FORM = {
  title: "", platform: "", platform_reference: "", severity: "",
  status: "submitted" as SubmissionStatus, payout_usd: "", notes: "",
  report_id: "", finding_id: "",
};

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLOR[status] || "text-[#52525b] border-[#52525b]/30 bg-transparent";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest ${cls}`}>
      {status}
    </span>
  );
}

export default function SubmissionsSection({ engagement }: { engagement: Engagement }) {
  const { authFetch, setMessage, navigate, state: { submissionPrefill }, dispatch } = useAppContext();
  const [submissions,    setSubmissions]    = useState<Submission[]>([]);
  const [loading,        setLoading]        = useState(true);
  const [showForm,       setShowForm]       = useState(false);
  const [form,           setForm]           = useState(EMPTY_FORM);
  const [editingId,      setEditingId]      = useState<string | null>(null);
  const [editForm,       setEditForm]       = useState<Partial<typeof EMPTY_FORM & { payout_usd: string }>>({});
  const [saving,         setSaving]         = useState(false);
  const [findings,       setFindings]       = useState<Finding[]>([]);
  const [statusFilter,   setStatusFilter]   = useState("");
  const [platformFilter, setPlatformFilter] = useState("");

  const [platformInput,  setPlatformInput]  = useState("");

  const load = useCallback(async (status: string, platform: string, signal?: AbortSignal) => {
    try {
      const p = new URLSearchParams();
      if (status)   p.set("status",   status);
      if (platform) p.set("platform", platform);
      const qs = p.toString() ? `?${p.toString()}` : "";
      const res = await authFetch(`/engagements/${engagement.id}/submissions${qs}`, { signal });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setSubmissions(Array.isArray(data?.submissions) ? data.submissions : []);
    } catch (e) {
      if ((e as { name?: string }).name !== "AbortError") setMessage("Failed to load submissions.");
    } finally { setLoading(false); }
  }, [engagement.id, authFetch, setMessage]);

  useEffect(() => {
    const ctrl = new AbortController();
    void load(statusFilter, platformFilter, ctrl.signal);
    return () => ctrl.abort();
  }, [load, statusFilter, platformFilter]);

  // Debounce the platform text input — only commit to filter state after 400 ms idle.
  useEffect(() => {
    const t = setTimeout(() => setPlatformFilter(platformInput), 400);
    return () => clearTimeout(t);
  }, [platformInput]);

  useEffect(() => {
    if (submissionPrefill) {
      setForm({
        ...EMPTY_FORM,
        title: submissionPrefill.title,
        report_id: submissionPrefill.report_id,
        finding_id: submissionPrefill.finding_id,
      });
      setShowForm(true);
      dispatch({ type: "SUBMISSION_PREFILL_CONSUMED" });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submissionPrefill]);

  // Load findings lazily the first time the form opens so the picker is populated.
  useEffect(() => {
    if (!showForm || findings.length > 0) return;
    void authFetch(`/engagements/${engagement.id}/findings?limit=200&offset=0`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.findings) setFindings(d.findings as Finding[]); });
  }, [showForm, findings.length, authFetch, engagement.id]);

  async function create() {
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      const body = {
        title: form.title,
        platform: form.platform,
        platform_reference: form.platform_reference,
        severity: form.severity,
        status: form.status,
        payout_usd: form.payout_usd ? parseFloat(form.payout_usd) : null,
        notes: form.notes,
        report_id: form.report_id || "",
        finding_id: form.finding_id || "",
      };
      const res = await authFetch(`/engagements/${engagement.id}/submissions`, { method: "POST", body: JSON.stringify(body) });
      if (!res.ok) throw new Error();
      const created: Submission = await res.json();
      setSubmissions((p) => [created, ...p]);
      setForm(EMPTY_FORM);
      setShowForm(false);
      setMessage("Submission logged.");
    } catch { setMessage("Failed to log submission."); } finally { setSaving(false); }
  }

  async function save(id: string) {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {};
      if (editForm.status)             body.status = editForm.status;
      if (editForm.payout_usd !== undefined && editForm.payout_usd !== "")
        body.payout_usd = parseFloat(editForm.payout_usd as string);
      if (editForm.notes !== undefined) body.notes = editForm.notes;
      if (editForm.platform_reference !== undefined) body.platform_reference = editForm.platform_reference;
      const res = await authFetch(`/engagements/${engagement.id}/submissions/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      if (!res.ok) throw new Error();
      const updated: Submission = await res.json();
      setSubmissions((p) => p.map((s) => (s.id === id ? updated : s)));
      setEditingId(null);
      setMessage("Submission updated.");
    } catch { setMessage("Failed to update submission."); } finally { setSaving(false); }
  }

  async function remove(id: string) {
    if (!confirm("Delete this submission? This cannot be undone.")) return;
    try {
      const res = await authFetch(`/engagements/${engagement.id}/submissions/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setSubmissions((p) => p.filter((s) => s.id !== id));
      if (editingId === id) setEditingId(null);
      setMessage("Submission removed.");
    } catch { setMessage("Failed to delete submission."); }
  }

  // Stats
  const total       = submissions.length;
  const accepted    = submissions.filter((s) => s.status === "accepted" || s.status === "paid").length;
  const acceptRate  = total > 0 ? Math.round((accepted / total) * 100) : 0;
  const totalPayout = submissions.reduce((sum, s) => sum + (s.payout_usd ?? 0), 0);

  // Analytics: by-platform breakdown
  const byPlatform = submissions.reduce<Record<string, { total: number; accepted: number; payout: number }>>((acc, s) => {
    const p = s.platform || "Unknown";
    if (!acc[p]) acc[p] = { total: 0, accepted: 0, payout: 0 };
    acc[p].total++;
    if (s.status === "accepted" || s.status === "paid") acc[p].accepted++;
    acc[p].payout += s.payout_usd ?? 0;
    return acc;
  }, {});

  // Analytics: by-severity breakdown
  const SEV_ORDER = ["critical", "high", "medium", "low", "info"];
  const bySeverity = submissions.reduce<Record<string, number>>((acc, s) => {
    const sev = s.severity || "unknown";
    acc[sev] = (acc[sev] ?? 0) + 1;
    return acc;
  }, {});
  const maxSevCount = Math.max(...SEV_ORDER.map((s) => bySeverity[s] ?? 0), 1);

  // Analytics: avg time-to-resolution (accepted + paid with both dates set)
  const resolved = submissions.filter((s) =>
    (s.status === "accepted" || s.status === "paid") && s.submitted_at && s.resolved_at
  );
  const avgDays = resolved.length > 0
    ? Math.round(
        resolved.reduce((sum, s) => {
          const ms = new Date(s.resolved_at!).getTime() - new Date(s.submitted_at!).getTime();
          return sum + ms / 86400000;
        }, 0) / resolved.length
      )
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2e2e2e] pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-2xl font-bold tracking-tight text-[#f1f5f9]">Submissions</h2>
            <span className="rounded border border-[#2e2e2e] px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-[#52525b]">
              tracker
            </span>
          </div>
          <p className="mt-1.5 text-sm text-[#52525b]">
            Track reports sent to platforms — status, payout, and lifecycle.
          </p>
        </div>
        <button
          onClick={() => { setShowForm((v) => !v); setForm(EMPTY_FORM); }}
          className="rounded-lg bg-[#f59e0b] px-4 py-2 text-sm font-semibold text-[#161616] transition hover:bg-[#fbbf24] active:scale-[0.98]">
          {showForm ? "Cancel" : "+ New Submission"}
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Total submitted", value: total },
          { label: "Acceptance rate", value: `${acceptRate}%` },
          { label: "Total payout",    value: totalPayout > 0 ? `$${totalPayout.toLocaleString()}` : "—" },
          { label: "Avg time-to-resolve", value: avgDays != null ? `${avgDays}d` : "—" },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-[#2e2e2e] bg-[#1a1a1a] px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{label}</p>
            <p className="mt-1 text-xl font-bold text-[#f1f5f9]">{value}</p>
          </div>
        ))}
      </div>

      {/* Analytics — only shown when there is data */}
      {total > 0 && (
        <div className="grid gap-5 xl:grid-cols-2">
          {/* By-severity bars */}
          <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
            <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">By Severity</p>
            <div className="space-y-2.5">
              {SEV_ORDER.map((sev) => {
                const count = bySeverity[sev] ?? 0;
                const pct   = Math.round((count / maxSevCount) * 100);
                const color = { critical: "#f38ba8", high: "#fab387", medium: "#f9e2af", low: "#89b4fa", info: "#74c7ec" }[sev] ?? "#52525b";
                return (
                  <div key={sev} className="flex items-center gap-3">
                    <span className="w-14 flex-shrink-0 text-[11px] font-medium text-[#52525b]">{sev}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#2e2e2e]">
                      <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: color }} />
                    </div>
                    <span className="w-5 flex-shrink-0 text-right font-mono text-xs" style={{ color }}>{count}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* By-platform table */}
          <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5">
            <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">By Platform</p>
            {Object.keys(byPlatform).length === 0 ? (
              <p className="text-xs text-[#3a3a3a]">No platform data.</p>
            ) : (
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#2e2e2e]">
                    {["Platform", "Submitted", "Accepted", "Payout"].map((h) => (
                      <th key={h} className="pb-2 font-semibold uppercase tracking-widest text-[#52525b] text-[9px]">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#2e2e2e]">
                  {Object.entries(byPlatform)
                    .sort((a, b) => b[1].total - a[1].total)
                    .map(([platform, stat]) => (
                      <tr key={platform}>
                        <td className="py-2 font-medium text-[#f1f5f9]">{platform}</td>
                        <td className="py-2 font-mono text-[#94a3b8]">{stat.total}</td>
                        <td className="py-2 font-mono text-[#a6e3a1]">{stat.accepted}</td>
                        <td className="py-2 font-mono text-[#a6e3a1]">
                          {stat.payout > 0 ? `$${stat.payout.toLocaleString()}` : "—"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* New submission form */}
      {showForm && (
        <div className="rounded-2xl border border-[#2e2e2e] bg-[#1a1a1a] p-5 space-y-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-[#52525b]">Log new submission</p>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Title *</label>
              <input
                className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
                placeholder="Short report title"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Platform</label>
              <input
                className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
                placeholder="HackerOne, Bugcrowd, etc."
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Platform reference</label>
              <input
                className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
                placeholder="Report ID or URL"
                value={form.platform_reference}
                onChange={(e) => setForm({ ...form, platform_reference: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Severity</label>
              <select
                className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] focus:border-[#f59e0b] focus:outline-none"
                value={form.severity}
                onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                <option value="">— pick one —</option>
                {["critical", "high", "medium", "low", "info"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Linked Finding</label>
              <select
                className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] focus:border-[#f59e0b] focus:outline-none"
                value={form.finding_id}
                onChange={(e) => setForm({ ...form, finding_id: e.target.value })}>
                <option value="">— none —</option>
                {findings.map((f) => (
                  <option key={f.id} value={f.id}>{f.title} ({f.severity})</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Notes</label>
            <textarea
              rows={2}
              className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none resize-none"
              placeholder="Optional notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
          <div className="flex justify-end">
            <button onClick={create} disabled={saving || !form.title.trim()}
              className="rounded-lg bg-[#f59e0b] px-5 py-2 text-sm font-semibold text-[#161616] transition hover:bg-[#fbbf24] disabled:opacity-50">
              {saving ? "Saving…" : "Log Submission"}
            </button>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <select
          className="rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] focus:border-[#f59e0b] focus:outline-none"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {["submitted", "triaged", "accepted", "duplicate", "na", "paid", "rejected"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <input
          className="rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
          placeholder="Filter by platform…"
          value={platformInput}
          onChange={(e) => setPlatformInput(e.target.value)}
        />
        {(statusFilter || platformInput) && (
          <button
            onClick={() => { setStatusFilter(""); setPlatformInput(""); setPlatformFilter(""); }}
            className="rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:text-[#94a3b8]">
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-sm text-[#52525b]">Loading…</p>
      ) : submissions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[#2e2e2e] p-14 text-center">
          <p className="text-sm text-[#3a3a3a]">No submissions yet. Click &ldquo;+ New Submission&rdquo; to log your first report.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-[#2e2e2e]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-[#2e2e2e] bg-[#1a1a1a]">
                {["Title", "Platform", "Severity", "Status", "Payout", "Submitted", ""].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2e2e2e]">
              {submissions.map((s) => (
                <Fragment key={s.id}>
                  <tr className="bg-[#161616] transition hover:bg-[#1a1a1a]">
                    <td className="px-4 py-3 max-w-[200px]">
                      <div className="font-medium text-[#f1f5f9] truncate">{s.title || "—"}</div>
                      {s.finding_id && (
                        <button
                          onClick={() => navigate("findings")}
                          className="mt-0.5 font-mono text-[10px] text-[#f59e0b] hover:underline">
                          ↗ finding
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[#94a3b8] font-mono text-xs">{s.platform || "—"}</td>
                    <td className="px-4 py-3">
                      {s.severity
                        ? <span className={`font-mono text-xs ${SEV_COLOR[s.severity] || "text-[#52525b]"}`}>{s.severity}</span>
                        : <span className="text-[#3a3a3a]">—</span>}
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={s.status} /></td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a6e3a1]">
                      {s.payout_usd != null ? `$${s.payout_usd.toLocaleString()}` : "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#52525b]">{fmtDate(s.submitted_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => { setEditingId(s.id); setEditForm({ status: s.status as SubmissionStatus, payout_usd: s.payout_usd?.toString() ?? "", notes: s.notes, platform_reference: s.platform_reference }); }}
                          className="rounded px-2 py-1 font-mono text-[11px] text-[#52525b] transition hover:bg-[#2e2e2e] hover:text-[#f1f5f9]">
                          edit
                        </button>
                        <button
                          onClick={() => remove(s.id)}
                          className="rounded px-2 py-1 font-mono text-[11px] text-[#52525b] transition hover:bg-[#2e2e2e] hover:text-[#f87171]">
                          ×
                        </button>
                      </div>
                    </td>
                  </tr>
                  {editingId === s.id && (
                    <tr key={`edit-${s.id}`} className="bg-[#1a1a1a]">
                      <td colSpan={7} className="px-4 py-4">
                        <div className="grid gap-3 md:grid-cols-3">
                          <div>
                            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Status</label>
                            <select
                              className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] focus:border-[#f59e0b] focus:outline-none"
                              value={editForm.status ?? s.status}
                              onChange={(e) => setEditForm({ ...editForm, status: e.target.value as SubmissionStatus })}>
                              {STATUS_OPTIONS.map((v) => <option key={v} value={v}>{v}</option>)}
                            </select>
                          </div>
                          <div>
                            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Payout (USD)</label>
                            <input
                              type="number"
                              className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
                              placeholder="0.00"
                              value={editForm.payout_usd ?? ""}
                              onChange={(e) => setEditForm({ ...editForm, payout_usd: e.target.value })}
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Platform ref.</label>
                            <input
                              className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
                              placeholder="Report ID"
                              value={editForm.platform_reference ?? ""}
                              onChange={(e) => setEditForm({ ...editForm, platform_reference: e.target.value })}
                            />
                          </div>
                          <div className="md:col-span-3">
                            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-widest text-[#52525b]">Notes</label>
                            <textarea
                              rows={2}
                              className="w-full rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none resize-none"
                              value={editForm.notes ?? ""}
                              onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                            />
                          </div>
                        </div>
                        <div className="mt-3 flex justify-end gap-2">
                          <button onClick={() => setEditingId(null)} className="rounded px-3 py-1.5 text-xs text-[#52525b] transition hover:text-[#94a3b8]">Cancel</button>
                          <button onClick={() => save(s.id)} disabled={saving}
                            className="rounded-lg bg-[#f59e0b] px-4 py-1.5 text-xs font-semibold text-[#161616] transition hover:bg-[#fbbf24] disabled:opacity-50">
                            {saving ? "Saving…" : "Save"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
