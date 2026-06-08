"use client";

import { useState } from "react";
import { Program, AuthFetch } from "../types";
import { Panel, Input, Textarea, PrimaryButton, ListCard, SectionHeader } from "./ui";

export default function ScopeSection({ program, authFetch, onRefresh, setMessage }: {
  program: Program;
  authFetch: AuthFetch;
  onRefresh: () => Promise<void>;
  setMessage: (m: string) => void;
}) {
  const [scopeIn,  setScopeIn]  = useState({ value: "", kind: "domain", notes: "" });
  const [scopeOut, setScopeOut] = useState({ value: "", kind: "domain", notes: "" });

  async function addScopeItem(scopeType: "in" | "out") {
    const payload = scopeType === "in" ? scopeIn : scopeOut;
    if (!payload.value.trim()) return;
    try {
      const res = await authFetch(`/programs/${program.id}/scope/${scopeType}`, { method: "POST", body: JSON.stringify(payload) });
      if (!res.ok) throw new Error();
      if (scopeType === "in") setScopeIn({ value: "", kind: "domain", notes: "" });
      else setScopeOut({ value: "", kind: "domain", notes: "" });
      await onRefresh();
      setMessage("Scope updated.");
    } catch { setMessage("Failed to add scope item."); }
  }

  async function deleteScopeItem(scopeType: "in" | "out", itemId: string) {
    try {
      await authFetch(`/programs/${program.id}/scope/${scopeType}/${itemId}`, { method: "DELETE" });
      await onRefresh();
      setMessage("Scope item deleted.");
    } catch { setMessage("Failed to delete scope item."); }
  }

  return (
    <div className="space-y-7">
      <SectionHeader title="Scope" description="Keep clear in-scope and out-of-scope boundaries before testing." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="In-Scope Assets">
          <div className="grid gap-3">
            <Input label="Value" value={scopeIn.value} onChange={(v) => setScopeIn({ ...scopeIn, value: v })} />
            <Input label="Kind"  value={scopeIn.kind}  onChange={(v) => setScopeIn({ ...scopeIn, kind: v })} />
            <Textarea label="Notes" value={scopeIn.notes} onChange={(v) => setScopeIn({ ...scopeIn, notes: v })} />
            <PrimaryButton onClick={() => addScopeItem("in")} label="Add In-Scope Asset" />
          </div>
          <div className="mt-5 space-y-2">
            {(program.scope?.in ?? []).map((item) => (
              <ListCard key={item.id} title={item.value} subtitle={`${item.kind}${item.notes ? ` — ${item.notes}` : ""}`} onDelete={() => deleteScopeItem("in", item.id)} />
            ))}
          </div>
        </Panel>
        <Panel title="Out-of-Scope Assets">
          <div className="grid gap-3">
            <Input label="Value" value={scopeOut.value} onChange={(v) => setScopeOut({ ...scopeOut, value: v })} />
            <Input label="Kind"  value={scopeOut.kind}  onChange={(v) => setScopeOut({ ...scopeOut, kind: v })} />
            <Textarea label="Notes" value={scopeOut.notes} onChange={(v) => setScopeOut({ ...scopeOut, notes: v })} />
            <PrimaryButton onClick={() => addScopeItem("out")} label="Add Out-of-Scope Asset" />
          </div>
          <div className="mt-5 space-y-2">
            {(program.scope?.out ?? []).map((item) => (
              <ListCard key={item.id} title={item.value} subtitle={`${item.kind}${item.notes ? ` — ${item.notes}` : ""}`} onDelete={() => deleteScopeItem("out", item.id)} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
