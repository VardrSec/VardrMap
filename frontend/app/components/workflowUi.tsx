import { ReactNode } from "react";
import { AuthFetch } from "../types";

export const fieldClass = "w-full rounded-md border border-[#393939] bg-[#111] px-3 py-2 text-sm text-[#f1f5f9] focus:border-[#f59e0b] focus:outline-none";
export const buttonClass = "rounded-md border border-[#393939] px-3 py-2 text-xs text-[#cbd5e1] hover:border-[#f59e0b] disabled:opacity-40";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block space-y-1.5 text-xs text-[#94a3b8]"><span>{label}</span>{children}</label>;
}

export async function requestJson<T>(fetch: AuthFetch, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`);
  return data as T;
}

export function errorText(error: unknown) { return error instanceof Error ? error.message : "Request failed."; }

export function Pages({ offset, count, total, busy, change }: { offset: number; count: number; total: number; busy?: boolean; change: (offset: number) => void }) {
  return <div className="flex items-center justify-between gap-3 text-xs text-[#94a3b8]">
    <span>{total === 0 ? "No items" : `${offset + 1}–${Math.min(offset + 50, total)} of ${total}`}</span>
    <div className="flex gap-2"><button type="button" className={buttonClass} disabled={busy || offset === 0} onClick={() => change(Math.max(0, offset - 50))}>Previous</button>
      <button type="button" className={buttonClass} disabled={busy || count === 0 || offset + count >= total} onClick={() => change(offset + 50)}>Next</button></div>
  </div>;
}
