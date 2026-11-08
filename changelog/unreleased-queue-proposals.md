# Operator-approved queue proposals (unreleased)

- Reuse existing pending proposals for `queue_job` and `queue_pipeline` requests;
  creating or rejecting a proposal creates no jobs. Pipelines retain the existing
  one-to-eight-stage bound. Proposals show exact JSON inputs for operator review.
- Full-scope operator approval locks the engagement and proposal, reruns existing
  request/configuration/membership/rate/case/dependency validation, and atomically
  commits jobs, job audits and proposal resolution. Repeat approval refuses.
- Job creation uses the approving operator's identity; the retained proposal records
  the proponent, reason and source. Publish the existing SSE update after commit.
- Queue-only approval does not advance permission authority revision or grant any
  execution authority; existing separate Gate snapshot/contract checks still apply.
- Existing direct jobs/pipelines routes reuse the same transactional helpers with
  their ordinary commit, response, policy and SSE behavior unchanged.

Workflow review now describes fixed setup, preflight and reset declarations plus
known capture/substitution limitations. It always requires Runner validation;
editing generated JSON clears stale summaries. Cleanup, expiry and prior-object
assumptions remain operator review requirements, separate from access outcomes.

Portable deliverables retain selected same-engagement job timing, terminal state,
frozen case hashes and redacted input context. Runner/tool identity is bounded
reported metadata, not server attestation. Credential/request payload omissions
are explicit; neither independent reassessment nor replay authority is claimed.
Historical receipt hashes remain unchanged when provenance is absent.
Shared pipeline creation checks Stop Work before writing any jobs.
