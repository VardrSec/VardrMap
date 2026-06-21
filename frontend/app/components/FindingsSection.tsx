"use client";

import { useCallback, useEffect, useState } from "react";
import { Program, Finding, FindingFormState } from "../types";
import { useAppContext } from "../context/AppContext";
import { Panel, Input, Textarea, SelectField, PrimaryButton, DangerButton, SeverityBadge, StatusBadge, SectionHeader } from "./ui";

const EMPTY: FindingFormState = { title: "", severity: "medium", asset: "", status: "new", summary: "", steps: "", impact: "", remediation: "" };

function FindingForm({ value, onChange }: { value: FindingFormState; onChange: (v: FindingFormState) => void }) {
  return (
    <div className="grid gap-3">
      <Input label="Title" value={value.title} onChange={(v) => onChange({ ...value, title: v })} />
      <div className="grid gap-3 md:grid-cols-3">
        <SelectField label="Severity" value={value.severity} onChange={(v) => onChange({ ...value, severity: v })}
          options={["info", "low", "medium", "high", "critical"]} />
        <Input label="Asset" value={value.asset} onChange={(v) => onChange({ ...value, asset: v })} />
        <SelectField label="Status" value={value.status} onChange={(v) => onChange({ ...value, status: v })}
          options={["new", "candidate", "triaged", "in_progress", "closed"]} />
      </div>
      <Textarea label="Summary"     value={value.summary}     onChange={(v) => onChange({ ...value, summary: v })} />
      <Textarea label="Steps"       value={value.steps}       onChange={(v) => onChange({ ...value, steps: v })} />
      <Textarea label="Impact"      value={value.impact}      onChange={(v) => onChange({ ...value, impact: v })} />
      <Textarea label="Remediation" value={value.remediation} onChange={(v) => onChange({ ...value, remediation: v })} />
    </div>
  );
}

export default function FindingsSection({ program }: { program: Program }) {
  const {
    authFetch, setMessage, refreshSelectedProgram, promoteToReport, navigate,
    state: { findingPrefill }, dispatch,
  } = useAppContext();

  function logSubmission(finding: Finding) {
    dispatch({ type: "PROMOTE_TO_SUBMISSION", prefill: { title: finding.title, report_id: "", finding_id: finding.id } });
    navigate("submissions");
  }
  const [findings,       setFindings]       = useState<Finding[]>([]);
  const [total,          setTotal]          = useState(0);
  const [offset,         setOffset]         = useState(0);
  const [loading,        setLoading]        = useState(true);
  const [loadingMore,    setLoadingMore]    = useState(false);
  const [form,           setForm]           = useState<FindingFormState>(EMPTY);
  const [editingId,      setEditingId]      = useState<string | null>(null);
  const [editForm,       setEditForm]       = useState<FindingFormState>(EMPTY);
  const [suggesting,     setSuggesting]     = useState<string | null>(null);
  const [searchInput,    setSearchInput]    = useState("");
  const [search,         setSearch]         = useState("");
  const [severityFilter, setSeverityFilter] = useState("");

  const PAGE = 50;

  function buildParams(off: number, q: string, sev: string) {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(off) });
    if (q)   p.set("search",   q);
    if (sev) p.set("severity", sev);
    return p.toString();
  }

  const loadFindings = useCallback(async (q: string, sev: string, signal?: AbortSignal) => {
    setLoading(true);
    try {
      const res = await authFetch(`/programs/${program.id}/findings?${buildParams(0, q, sev)}`, { signal });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setFindings(Array.isArray(data?.findings) ? data.findings : []);
      setTotal(data?.total ?? 0);
      setOffset(0);
    } catch (e) {
      if ((e as { name?: string }).name !== "AbortError") setMessage("Failed to load findings.");
    } finally { setLoading(false); }
  }, [program.id, authFetch, setMessage]);

  async function loadMore() {
    const next = offset + PAGE;
    setLoadingMore(true);
    try {
      const res = await authFetch(`/programs/${program.id}/findings?${buildParams(next, search, severityFilter)}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setFindings((prev) => [...prev, ...(Array.isArray(data?.findings) ? data.findings : [])]);
      setOffset(next);
    } catch { setMessage("Failed to load more findings."); } finally { setLoadingMore(false); }
  }

  useEffect(() => {
    const ctrl = new AbortController();
    void loadFindings(search, severityFilter, ctrl.signal);
    return () => ctrl.abort();
  }, [loadFindings, search, severityFilter]);

  // Apply the prefill from a promoted scan, then immediately clear it from the
  // reducer. If we didn't clear it, navigating away and back would re-apply the
  // old scan data on top of whatever the user typed.
  useEffect(() => {
    if (findingPrefill) {
      setForm(findingPrefill);
      dispatch({ type: "FINDING_PREFILL_CONSUMED" });
    }
  }, [findingPrefill, dispatch]);

  async function addFinding() {
    if (!form.title.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/findings`, { method: "POST", body: JSON.stringify(form) });
      if (!res.ok) throw new Error();
      setForm(EMPTY);
      await loadFindings(search, severityFilter);
      await refreshSelectedProgram(program.id);
      setMessage("Finding added.");
    } catch { setMessage("Failed to add finding."); }
  }

  async function deleteFinding(findingId: string) {
    if (!confirm("Delete this finding? This cannot be undone.")) return;
    try {
      await authFetch(`/programs/${program.id}/findings/${findingId}`, { method: "DELETE" });
      await loadFindings(search, severityFilter);
      await refreshSelectedProgram(program.id);
      setMessage("Finding deleted.");
    } catch { setMessage("Failed to delete finding."); }
  }

  function startEdit(finding: Finding) {
    setEditingId(finding.id);
    setEditForm({ title: finding.title, severity: finding.severity, asset: finding.asset, status: finding.status, summary: finding.summary, steps: finding.steps, impact: finding.impact, remediation: finding.remediation });
  }

  async function saveEdit(findingId: string) {
    try {
      const res = await authFetch(`/programs/${program.id}/findings/${findingId}`, { method: "PATCH", body: JSON.stringify(editForm) });
      if (!res.ok) throw new Error();
      setEditingId(null);
      await loadFindings(search, severityFilter);
      await refreshSelectedProgram(program.id);
      setMessage("Finding updated.");
    } catch { setMessage("Failed to update finding."); }
  }

  async function aiSuggest(finding: Finding) {
    setSuggesting(finding.id);
    try {
      const res = await authFetch(`/programs/${program.id}/findings/${finding.id}/suggest`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMessage(err.detail || "AI suggestion failed.");
        return;
      }
      const data = await res.json();
      setEditingId(finding.id);
      setEditForm({
        title: finding.title,
        severity: finding.severity,
        asset: finding.asset,
        status: finding.status,
        summary: finding.summary,
        steps: finding.steps,
        impact: data.impact || finding.impact,
        remediation: data.remediation || finding.remediation,
      });
      setMessage(`AI suggestion applied. CVSS: ${data.cvss || "(none)"}`);
    } catch { setMessage("AI suggestion request failed."); } finally { setSuggesting(null); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Findings" description="Track validated issues before drafting the final report." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Add Finding">
          <FindingForm value={form} onChange={setForm} />
          <div className="mt-3">
            <PrimaryButton onClick={addFinding} label="Save Finding" />
          </div>
        </Panel>
        <Panel title={`Finding Tracker${total > 0 ? ` (${total})` : ""}`}>
          <form
            onSubmit={(e) => { e.preventDefault(); setSearch(searchInput); }}
            className="mb-4 flex gap-2">
            <input
              className="flex-1 rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] placeholder-[#3a3a3a] focus:border-[#f59e0b] focus:outline-none"
              placeholder="Search title or asset…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
            <select
              className="rounded-md border border-[#2e2e2e] bg-[#161616] px-3 py-2 text-sm text-[#f1f5f9] focus:border-[#f59e0b] focus:outline-none"
              value={severityFilter}
              onChange={(e) => { setSeverityFilter(e.target.value); }}>
              <option value="">All severities</option>
              {["critical", "high", "medium", "low", "info"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button type="submit" className="rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:text-[#94a3b8]">
              Search
            </button>
            {(search || severityFilter) && (
              <button type="button" onClick={() => { setSearch(""); setSearchInput(""); setSeverityFilter(""); }}
                className="rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:text-[#94a3b8]">
                Clear
              </button>
            )}
          </form>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((n) => (
                <div key={n} className="h-16 animate-pulse rounded-xl border border-[#2e2e2e] bg-[#161616]" />
              ))}
            </div>
          ) : findings.length === 0 ? (
            <p className="text-sm text-[#3a3a3a]">{search || severityFilter ? "No findings match that filter." : "No findings yet."}</p>
          ) : (
            <div className="space-y-3">
              {findings.map((finding) =>
                editingId === finding.id ? (
                  <div key={finding.id} className="rounded-xl border border-[#f59e0b]/30 bg-[#161616] p-4 space-y-3">
                    <FindingForm value={editForm} onChange={setEditForm} />
                    <div className="flex gap-2">
                      <PrimaryButton onClick={() => saveEdit(finding.id)} label="Save" />
                      <button onClick={() => setEditingId(null)} className="rounded-md border border-[#2e2e2e] px-4 py-2 text-sm text-[#52525b] transition hover:text-[#94a3b8]">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div key={finding.id} className="rounded-xl border border-[#2e2e2e] bg-[#161616] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-semibold text-[#f1f5f9]">{finding.title}</div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <SeverityBadge severity={finding.severity} />
                          <StatusBadge   status={finding.status} />
                          {finding.asset && <span className="font-mono text-xs text-[#52525b]">{finding.asset}</span>}
                          {finding.created_at && (
                            <span className="font-mono text-xs text-[#3a3a3a]">
                              {new Date(finding.created_at).toLocaleDateString()}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => aiSuggest(finding)}
                          disabled={suggesting === finding.id}
                          title="Use Claude AI to draft CVSS, impact, and remediation"
                          className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#a6e3a1] disabled:opacity-40">
                          {suggesting === finding.id ? "…" : "AI Suggest"}
                        </button>
                        <button onClick={() => logSubmission(finding)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#a6e3a1]">
                          Log Submission →
                        </button>
                        <button onClick={() => promoteToReport(finding)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                          Draft Report →
                        </button>
                        <button onClick={() => startEdit(finding)} className="rounded-md border border-[#2e2e2e] px-2.5 py-1 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8]">
                          Edit
                        </button>
                        <DangerButton onClick={() => deleteFinding(finding.id)} label="Delete" small />
                      </div>
                    </div>
                    {finding.summary && <p className="mt-3 text-sm text-[#6b7280]">{finding.summary}</p>}
                  </div>
                )
              )}
              {findings.length < total && (
                <button onClick={loadMore} disabled={loadingMore}
                  className="w-full rounded-md border border-[#2e2e2e] px-4 py-2 text-xs text-[#52525b] transition hover:border-[#3a3a3a] hover:text-[#94a3b8] disabled:opacity-50">
                  {loadingMore ? "Loading…" : `Load more (${total - findings.length} remaining)`}
                </button>
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
