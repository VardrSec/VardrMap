"use client";

import { useState } from "react";
import DraftIdentityEditor, { type IdentityEdit, type Source } from "./DraftIdentityEditor";
import { buttonClass, Field, fieldClass } from "./workflowUi";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function label(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

const SOURCE_LABELS = { value_env: "Environment reference", value_keychain: "Keychain reference", anonymous: "No credentials", unknown: "Review in JSON" };

function credentialSource(value: unknown): Source | "unknown" {
  const { type, header, value: literal, value_env, value_keychain } = record(value);
  if ((literal != null && literal !== "") || (type !== "bearer" && type !== "api_key_header" && type !== "static_header")
    || (value_env != null && typeof value_env !== "string") || (value_keychain != null && typeof value_keychain !== "string")) {
    return "unknown";
  }
  const env = label(value_env);
  const keychain = label(value_keychain);
  if (env && keychain) return "unknown";
  if (type === "static_header" && !env && !keychain) {
    return header === "" || header == null ? "anonymous" : "unknown";
  }
  if (type === "static_header" && !label(header)) return "unknown";
  if (env) return "value_env";
  if (keychain) return "value_keychain";
  return "unknown";
}

type ReviewProps = { json: string; onChange?: (json: string) => void };

function CaseIdentities({ json, open, onChange }: ReviewProps & { open: boolean }) {
  const [selection, setSelection] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  if (!open) return null;
  let cases: unknown;
  try { cases = JSON.parse(json); } catch { return <p>Complete the draft JSON to review identities.</p>; }
  if (!Array.isArray(cases)) return <p>Draft cases must be a JSON array.</p>;
  if (!cases.length) return <p>No draft cases to review.</p>;

  const index = Math.min(selection, cases.length - 1);
  const draft = record(cases[index]);
  const spec = record(draft.spec);
  const resource = record(spec.resource);
  const verification = record(spec.write_verification);
  const verifier = record(verification.identity);
  const identities = Array.isArray(spec.identities) ? spec.identities.map(record) : [];
  const ids = identities.map(identity => label(identity.id)?.trim() ?? "");
  const idCounts = new Map<string, number>();
  for (const id of ids) idCounts.set(id, (idCounts.get(id) ?? 0) + 1);
  const access = Array.isArray(spec.expected_access) ? spec.expected_access : [];
  const decisions = new Map<string, string>();
  for (const entry of access) {
    const { identity_id, decision } = record(entry);
    if (typeof identity_id !== "string" || !identity_id.trim()) continue;
    const current = decision === "allow" || decision === "deny" || decision === "skip" ? decision : "Review in JSON";
    const previous = decisions.get(identity_id);
    decisions.set(identity_id, previous && previous !== current ? "Conflicting decisions" : current);
  }
  const identity = editing === null ? undefined : identities[editing];
  const credential = record(identity?.credential);
  const source = credentialSource(credential);
  const entries = identity ? access.map(record).filter(entry => entry.identity_id === identity.id) : [];
  const decision = entries[0]?.decision;
  const editableDecision = entries.length > 1 || (decision != null && decision !== "allow" && decision !== "deny" && decision !== "skip")
    || (spec.expected_access != null && !Array.isArray(spec.expected_access)) ? null : String(decision ?? "");

  function apply(edit: IdentityEdit) {
    if (editing === null || !onChange) return;
    const updated: unknown[] = JSON.parse(json);
    const spec = record(record(updated[index]).spec);
    const identity = record(Array.isArray(spec.identities) && spec.identities[editing]);
    const access = Array.isArray(spec.expected_access) ? spec.expected_access : [];
    const entries = access.map(record).filter(entry => entry.identity_id === identity.id);
    if (identity.id !== edit.id) {
      for (const entry of entries) entry.identity_id = edit.id;
      const owner = record(spec.resource);
      if (owner.owner_identity === identity.id) owner.owner_identity = edit.id;
      for (const step of Array.isArray(spec.setup) ? spec.setup.map(record) : []) {
        if (step.as === identity.id) step.as = edit.id;
      }
      identity.id = edit.id;
    }
    if (edit.role !== (identity.role ?? "")) identity.role = edit.role;
    if (edit.tenant !== (identity.tenant_id ?? "")) identity.tenant_id = edit.tenant;
    if (edit.credential) identity.credential = edit.credential;
    if (edit.decision) {
      if (entries.length === 1) entries[0].decision = edit.decision;
      else spec.expected_access = [...access, { identity_id: edit.id, decision: edit.decision }];
    }
    onChange(JSON.stringify(updated, null, 2));
    setEditing(null);
  }

  return <div className="mt-2 space-y-2">
    {cases.length > 1 && <Field label="Case to review">
      <select className={fieldClass} value={index} onChange={e => setSelection(Number(e.target.value))}>
        {cases.map((item, i) => <option key={i} value={i}>{i + 1}. {label(record(item).name) ?? "Unnamed case"}</option>)}
      </select>
    </Field>}
    <p>Resource owner: {label(resource.owner_identity) ?? "Not declared"} · Resource tenant: {label(resource.tenant_id) ?? "Not declared"}</p>
    {identities.length > 0 ? <div className="overflow-x-auto"><table aria-label="Draft identities" className="w-full text-left text-xs">
      <thead><tr>{["Identity", "Role", "Tenant", "Credential source", "Expected access"].map(header =>
        <th key={header} scope="col" className="p-2 font-semibold">{header}</th>)}{onChange && <th scope="col"><span className="sr-only">Edit identity</span></th>}</tr></thead>
      <tbody>{identities.map((identity, i) => <tr key={i} className="border-t border-[#2e2e2e]">
        <th scope="row" className="p-2 font-mono">{label(identity.id) ?? "Missing identity ID"}</th>
        <td className="p-2">{label(identity.role) ?? "Not declared"}</td>
        <td className="p-2">{label(identity.tenant_id) ?? "Not declared"}</td>
        <td className="p-2">{SOURCE_LABELS[credentialSource(identity.credential)]}</td>
        <td className="p-2">{decisions.get(label(identity.id) ?? "") ?? "Not declared"}</td>
        {onChange && <td className="p-2">{ids[i] && idCounts.get(ids[i]) === 1
          && (identity.role == null || typeof identity.role === "string") && (identity.tenant_id == null || typeof identity.tenant_id === "string")
          ? <button type="button" className={buttonClass} aria-label={`Edit identity ${ids[i]}`} onClick={() => setEditing(i)}>Edit</button>
          : "Review in JSON"}</td>}
      </tr>)}</tbody>
    </table></div> : <p>No identities declared in this draft.</p>}
    {"identity" in verification && <section aria-label="Verification identity">
      <h4 className="font-semibold">Verification identity</h4>
      <p>{label(verifier.id) ?? "Missing identity ID"} · {SOURCE_LABELS[credentialSource(verifier.credential)]}</p>
    </section>}
    {identity && onChange && <DraftIdentityEditor identity={identity} credential={credential}
      source={source === "unknown" ? null : source}
      decision={editableDecision} otherIds={ids.filter((_, i) => i !== editing)} onApply={apply} onClose={() => setEditing(null)} />}
  </div>;
}

export default function DraftIdentityReview({ json, onChange }: ReviewProps) {
  const [open, setOpen] = useState(false);
  return <details className="rounded border border-[#393939] p-3 text-xs text-[#cbd5e1]" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className="cursor-pointer font-semibold">Review draft identities</summary>
    <CaseIdentities json={json} open={open} onChange={onChange} />
  </details>;
}
