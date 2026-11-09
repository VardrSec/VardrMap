# NM-2 worker decisions — historical reference

The options in this document preceded the November 5, 2026 lifecycle decision.
They are no longer a pending approval request or an implementation task list.
The complete earlier analysis remains in the
[immutable historical version](https://github.com/VardrSec/VardrMap/blob/b9dc151e5e6c17cc7b88ff2b3bb00eca6732c312/docs/nm2-worker-decisions-pending.md).
Temporary backup exceptions, personal workstation references and cloud-review
handoff instructions in that record are not current operator guidance.

## Existing approved constraints

The architecture retains one Runner, explicit worker enablement, shared job
validation, local credential custody, bounded execution and conservative recovery.
The selected lifecycle design is documented in
[Runner ADR 0043](https://github.com/VardrSec/VardrRunner/blob/main/docs/adr/0043-proposed-linux-worker-lifecycle-owner.md).
Its implementation history does not waive unresolved safety or release gates.

## C — Container containment

See the [historical alternatives](https://github.com/VardrSec/VardrMap/blob/b9dc151e5e6c17cc7b88ff2b3bb00eca6732c312/docs/nm2-worker-decisions-pending.md#c--container-containment)
and the current lifecycle ADR. Do not infer containment from a container's mere presence.

## B — Issuer, enrollment and secret bootstrap

Use the distribution's [local managed setup](https://github.com/VardrSec/VardrSec/blob/main/docs/local-managed-setup.md)
for current provisioning and separate signing custody. Historical alternatives are
not instructions to create another enrollment or authorization service.

## L — Operator lifecycle and recovery

Use the [worker operator guide](https://github.com/VardrSec/VardrSec/blob/main/docs/nm2-worker-operator.md)
for explicit status, stop and recovery. Unknown execution remains held; service
availability alone grants no execution authority.

## Review handoff

There is no pending handoff on this page. Current acceptance and outstanding
C09/C10 and release decisions belong to the
[New Moon ledger](https://github.com/VardrSec/VardrSec/blob/main/docs/new-moon-acceptance.md)
and [architecture review](https://github.com/VardrSec/VardrSec/blob/main/docs/new-moon-architecture-review.md).
