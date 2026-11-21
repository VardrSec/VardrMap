"use client";

import { useState } from "react";
import { Field, fieldClass } from "./workflowUi";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function label(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function credentialSource(value: unknown) {
  const { type, header, value: literal, value_env, value_keychain } = record(value);
  if ((literal != null && literal !== "") || (type !== "bearer" && type !== "api_key_header" && type !== "static_header")
    || (value_env != null && typeof value_env !== "string") || (value_keychain != null && typeof value_keychain !== "string")) {
    return "Review in JSON";
  }
  const env = label(value_env);
  const keychain = label(value_keychain);
  if (env && keychain) return "Review in JSON";
  if (type === "static_header" && !env && !keychain) {
    return header === "" || header == null ? "No credentials" : "Review in JSON";
  }
  if (type === "static_header" && !label(header)) return "Review in JSON";
  if (env) return "Environment reference";
  if (keychain) return "Keychain reference";
  return "Review in JSON";
}

function CaseIdentities({ json, open }: { json: string; open: boolean }) {
  const [selection, setSelection] = useState(0);
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
  const decisions = new Map<string, string>();
  for (const entry of Array.isArray(spec.expected_access) ? spec.expected_access : []) {
    const { identity_id, decision } = record(entry);
    if (typeof identity_id !== "string" || !identity_id.trim()) continue;
    const current = decision === "allow" || decision === "deny" || decision === "skip" ? decision : "Review in JSON";
    const previous = decisions.get(identity_id);
    decisions.set(identity_id, previous && previous !== current ? "Conflicting decisions" : current);
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
        <th key={header} scope="col" className="p-2 font-semibold">{header}</th>)}</tr></thead>
      <tbody>{identities.map((identity, i) => <tr key={i} className="border-t border-[#2e2e2e]">
        <th scope="row" className="p-2 font-mono">{label(identity.id) ?? "Missing identity ID"}</th>
        <td className="p-2">{label(identity.role) ?? "Not declared"}</td>
        <td className="p-2">{label(identity.tenant_id) ?? "Not declared"}</td>
        <td className="p-2">{credentialSource(identity.credential)}</td>
        <td className="p-2">{decisions.get(label(identity.id) ?? "") ?? "Not declared"}</td>
      </tr>)}</tbody>
    </table></div> : <p>No identities declared in this draft.</p>}
    {"identity" in verification && <section aria-label="Verification identity">
      <h4 className="font-semibold">Verification identity</h4>
      <p>{label(verifier.id) ?? "Missing identity ID"} · {credentialSource(verifier.credential)}</p>
    </section>}
  </div>;
}

export default function DraftIdentityReview({ json }: { json: string }) {
  const [open, setOpen] = useState(false);
  return <details className="rounded border border-[#393939] p-3 text-xs text-[#cbd5e1]" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className="cursor-pointer font-semibold">Review draft identities</summary>
    <CaseIdentities json={json} open={open} />
  </details>;
}
