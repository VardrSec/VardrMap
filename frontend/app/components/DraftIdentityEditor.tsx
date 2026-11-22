import { useEffect, useRef, useState } from "react";
import { buttonClass, Field, fieldClass } from "./workflowUi";

type DraftObject = Record<string, unknown>;
export type Source = "value_env" | "value_keychain" | "anonymous";

export interface IdentityEdit {
  id: string;
  role: string;
  tenant: string;
  credential?: DraftObject;
  decision: string;
}

export default function DraftIdentityEditor({ identity, credential, source, decision, otherIds, onApply, onClose }: {
  identity: DraftObject; credential: DraftObject; source: Source | null; decision: string | null;
  otherIds: string[]; onApply: (edit: IdentityEdit) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState(source);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);

  function apply(form: HTMLFormElement) {
    const fields = new FormData(form);
    const input = (name: string) => String(fields.get(name) ?? "");
    const requestedId = input("identity");
    const id = requestedId === identity.id ? requestedId : requestedId.trim();
    if (!id.trim() || otherIds.includes(id.trim())) {
      setError("Choose a nonempty identity ID unique to this case.");
      return;
    }
    let updated: DraftObject | undefined;
    if (selected) {
      const reference = input("reference");
      if (selected !== "anonymous" && !reference.trim()) {
        setError("Enter the environment variable name or keychain account.");
        return;
      }
      if (selected !== source || (selected !== "anonymous" && reference !== credential[selected])) {
        updated = { ...credential };
        delete updated.value_env;
        delete updated.value_keychain;
        if (selected === "anonymous") {
          if (identity.preflight != null) {
            setError("Remove the authenticated preflight in the JSON editor before choosing no credentials.");
            return;
          }
          updated.type = "static_header";
          updated.header = "";
        } else {
          if (source === "anonymous") updated.type = "bearer";
          updated[selected] = reference;
        }
      }
    }
    onApply({ id, role: input("role"), tenant: input("tenant"), credential: updated, decision: input("decision") });
  }

  return <dialog ref={dialog} onCancel={onClose} aria-label="Edit draft identity"
    className="fixed inset-0 m-auto w-full max-w-md rounded-lg border border-[#393939] bg-[#151515] p-5 text-[#f1f5f9] backdrop:bg-black/70">
    <form className="space-y-3" onSubmit={e => { e.preventDefault(); apply(e.currentTarget); }}>
      <h3 className="font-semibold">Edit draft identity</h3>
      <Field label="Identity ID"><input name="identity" className={fieldClass} required defaultValue={String(identity.id)} /></Field>
      <Field label="Role"><input name="role" className={fieldClass} defaultValue={String(identity.role ?? "")} /></Field>
      <Field label="Tenant"><input name="tenant" className={fieldClass} defaultValue={String(identity.tenant_id ?? "")} /></Field>
      {source === null ? <p>Review this credential in the JSON editor.</p> : <>
        <Field label="Credential source"><select className={fieldClass} value={selected ?? ""} onChange={e => setSelected(e.target.value as Source)}>
          <option value="anonymous">No credentials</option><option value="value_env">Environment variable</option><option value="value_keychain">Keychain account</option>
        </select></Field>
        {selected !== "anonymous" && selected !== null && <Field label={selected === "value_env" ? "Environment variable name" : "Keychain account name"}>
          <input key={selected} name="reference" className={fieldClass} autoComplete="off" required defaultValue={String(credential[selected] ?? "")} />
        </Field>}
        {source === "anonymous" && selected !== "anonymous" && <p>The new credential uses bearer authentication.</p>}
      </>}
      {decision === null ? <p>Review the conflicting or invalid access entries in the JSON editor.</p> :
        <Field label="Expected access"><select name="decision" className={fieldClass} defaultValue={decision}>
          {!decision && <option value="">Choose a decision</option>}
          <option value="allow">Allow</option><option value="deny">Deny</option><option value="skip">Skip</option>
        </select></Field>}
      {error && <p role="alert" className="text-red-400">{error}</p>}
      <div className="flex gap-2"><button type="submit" className={buttonClass}>Apply to draft</button>
        <button type="button" className={buttonClass} onClick={onClose}>Cancel</button></div>
    </form>
  </dialog>;
}
