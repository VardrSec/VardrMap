import type { WorkflowReview } from "../types";

const BLOCKERS: Record<string, string> = {
  setup_capture: "Setup/reset capture is outside the controlled fixed-request profile.",
  template_substitution: "Template substitution is outside the controlled fixed-request profile.",
};

export default function WorkflowReviewSummary({ review, label = "Workflow prerequisites" }: { review?: WorkflowReview; label?: string }) {
  return <details className="mt-2 text-[11px] text-[#94a3b8]">
    <summary className="cursor-pointer">{label} · Runner validation required</summary>
    {review ? <>
      <p className="mt-1">Setup steps: {review.setup_count ?? "unknown"}. Identity preflight: {review.preflight_identity_ids.length ? review.preflight_identity_ids.join(", ") : "not declared"}.</p>
      <p>Captures: {review.captures_declared ? "declared" : "not observed"}. Substitutions: {review.substitutions_observed ? "observed" : "not observed"}. Write reset: {review.write_reset_declared ? "declared" : "not declared"}.</p>
      {review.fixed_profile_blockers.length > 0 ? <ul className="list-disc pl-4 text-[#fbbf24]">{review.fixed_profile_blockers.map(code => <li key={code}>{BLOCKERS[code] ?? "Unsupported requirement; Runner validation is required."}</li>)}</ul> : <p>No known capture/substitution blocker observed; this is not an execution-plan validation.</p>}
    </> : <p className="mt-1">Review the current edited JSON; a generated summary does not validate your changes.</p>}
    <p className="mt-1">Write reset is not end-of-case cleanup. Cleanup is not automated by this summary.</p>
    <p>Identity preflight is point-in-time; token expiry, refresh and lifecycle transitions are not established.</p>
    <p>Review prior-object existence, ownership and state. Record these prerequisites and any cleanup or expiry requirements in the existing case description.</p>
    <p>These workflow facts do not change reported access outcomes or establish workflow coverage.</p>
  </details>;
}
