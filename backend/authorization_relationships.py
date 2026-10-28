"""Relationships between identities, tenants, resources and operations, and the
boundaries between them that have not been evaluated.

Everything here is read from facts a person reviewed and saved in stored Gate cases:
each identity's declared `role` and `tenant_id`, a case's `resource` context
(`owner_identity`, `tenant_id`) and its `role_hierarchy`, plus the current coverage
result for each case. Nothing is inferred from traffic, nothing is guessed about who
should have access, and an attribute that was never declared stays unknown.

Two rules keep this honest:

* **Declarations are never silently reconciled.** If cases disagree about an identity's
  tenant, role or credential kind, the engagement-wide value is *unknown*, the
  disagreement is reported in `identity_conflicts`, and nothing is built on it.
  A case that omits an attribute does not contradict one that declares it.
* **A relationship is established only by the case that declares it.** An identity id
  that happens to match in another case does not lend that case a tenant or a role.
  Each case is classified from its own reviewed declarations alone.

A *boundary class* describes how a caller relates to the owner of the object under
test:

* `cross_tenant`   the caller's declared tenant differs from the object's tenant.
* `same_tenant_peer` the caller shares the object's tenant but is not its owner.
* `higher_privilege` the caller's role outranks the owner's in the case's role hierarchy.
* `anonymous`      the caller sends no credentials.

A hypothesis is a question to put to the target, never a finding.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict

from sqlalchemy.orm import Session

from authorization_coverage import build_coverage
from models import AuthorizationTestCase

CLASSES = ("cross_tenant", "same_tenant_peer", "higher_privilege", "anonymous")
CLASS_LABEL = {
    "cross_tenant": "a caller from a different tenant",
    "same_tenant_peer": "another caller in the same tenant",
    "higher_privilege": "a caller with a higher role than the owner",
    "anonymous": "a caller without credentials",
}
_DRAFT_IDENTITY_LIMIT = 6


def _credential(identity: dict) -> dict:
    return identity.get("credential") if isinstance(identity.get("credential"), dict) else {}


def _is_anonymous(identity: dict) -> bool:
    credential = _credential(identity)
    return credential.get("type") == "static_header" and not credential.get("header")


def _reference(identity: dict) -> tuple:
    """The credential *reference* (never a value) an identity declares."""
    credential = _credential(identity)
    return (
        credential.get("type"),
        credential.get("header") or None,
        credential.get("value_env") or None,
        credential.get("value_keychain") or None,
    )


def _local_table(spec: dict) -> dict[str, dict]:
    """One case's own reviewed declarations: the only basis for classifying that case."""
    table: dict[str, dict] = {}
    for identity in spec.get("identities") or []:
        if isinstance(identity, dict) and identity.get("id"):
            table[str(identity["id"])] = {
                "identity_id": str(identity["id"]),
                "role": str(identity.get("role") or "") or None,
                "tenant_id": str(identity.get("tenant_id") or "") or None,
                "anonymous": _is_anonymous(identity),
                "reference": _reference(identity),
            }
    return table


def merge_identities(specs: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Engagement-wide view of each identity, with contradictions reported.

    An attribute is established only if every declaration that sets it agrees. Omission is
    neutral. Disagreement leaves the value unknown and is returned as a conflict.
    """
    seen: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    cases_of: dict[str, int] = defaultdict(int)
    for spec in specs:
        for identity_id, row in _local_table(spec).items():
            cases_of[identity_id] += 1
            for attribute in ("role", "tenant_id"):
                if row[attribute]:
                    seen[identity_id][attribute].add(row[attribute])
            seen[identity_id]["kind"].add("anonymous" if row["anonymous"] else "credentialed")
            seen[identity_id]["reference"].add(row["reference"])
    table, conflicts = {}, []
    for identity_id in sorted(seen):
        attrs = seen[identity_id]
        bad: list[str] = []

        def value(attribute):
            values = attrs.get(attribute, set())
            if len(values) > 1:
                bad.append(attribute)
                conflicts.append({"identity_id": identity_id, "attribute": attribute, "values": sorted(values)})
                return None
            return next(iter(values), None)

        role, tenant = value("role"), value("tenant_id")
        kinds = attrs["kind"]
        if len(kinds) > 1:
            bad.append("credential")
            conflicts.append({"identity_id": identity_id, "attribute": "credential", "values": sorted(kinds)})
        elif len(attrs["reference"]) > 1:
            bad.append("credential")
            conflicts.append({
                "identity_id": identity_id, "attribute": "credential",
                "values": sorted(" ".join(str(p) for p in ref if p) for ref in attrs["reference"]),
            })
        table[identity_id] = {
            "identity_id": identity_id, "role": role, "tenant_id": tenant,
            "anonymous": kinds == {"anonymous"}, "conflicts": bad,
            "reference": next(iter(attrs["reference"])) if len(attrs["reference"]) == 1 else None,
        }
    return table, conflicts


def classify(spec: dict, subject: dict, owner: dict, resource: dict) -> tuple[list[str], list[str]]:
    """Boundary classes of `subject` relative to the owner, from one case's own declarations."""
    if subject["anonymous"]:
        return ["anonymous"], [f"{subject['identity_id']} sends no credentials"]
    classes, basis = [], []
    object_tenant = (resource.get("tenant_id") or owner.get("tenant_id") or None)
    if subject["tenant_id"] and object_tenant:
        if subject["tenant_id"] != object_tenant:
            classes.append("cross_tenant")
            basis.append(f"{subject['identity_id']} is declared in tenant {subject['tenant_id']}; the object is in {object_tenant}")
        else:
            classes.append("same_tenant_peer")
            basis.append(f"{subject['identity_id']} and the object share tenant {object_tenant}")
    hierarchy = [str(r) for r in spec.get("role_hierarchy") or []]
    if hierarchy and subject["role"] in hierarchy and owner.get("role") in hierarchy:
        if hierarchy.index(subject["role"]) > hierarchy.index(owner["role"]):
            classes.append("higher_privilege")
            basis.append(f"{subject['identity_id']} ({subject['role']}) outranks the owner ({owner['role']}) in the role hierarchy")
    return classes, basis


def _askable(table: dict[str, dict], hierarchies: list[list[str]]) -> tuple[dict, dict]:
    """Which boundary classes the *established* identity attributes make testable."""
    people = [i for i in table.values() if not i["anonymous"] and not i["conflicts"]]
    by_tenant: dict[str, int] = defaultdict(int)
    for person in people:
        if person["tenant_id"]:
            by_tenant[person["tenant_id"]] += 1
    tenants = sorted(by_tenant)
    ranked = sorted({
        r for h in hierarchies for r in h if r in {p["role"] for p in people}
    })
    anonymous = sorted(i["identity_id"] for i in table.values() if i["anonymous"] and not i["conflicts"])
    askable = {
        "cross_tenant": len(tenants) >= 2,
        "same_tenant_peer": any(n >= 2 for n in by_tenant.values()),
        "higher_privilege": len(ranked) >= 2,
        "anonymous": bool(anonymous),
    }
    basis = {
        "cross_tenant": "Identities are declared in tenants: " + ", ".join(tenants) + ".",
        "same_tenant_peer": "Several identities share a tenant: " + ", ".join(f"{t} ({n})" for t, n in sorted(by_tenant.items()) if n >= 2) + ".",
        "higher_privilege": "Roles in a case's role hierarchy: " + ", ".join(ranked) + ".",
        "anonymous": "An identity without credentials is declared: " + ", ".join(anonymous) + ".",
    }
    return askable, basis


def build_relationships(db: Session, program_id: str) -> dict:
    coverage = build_coverage(db, program_id)
    cases = {
        c.id: c.spec if isinstance(c.spec, dict) else {}
        for c in db.query(AuthorizationTestCase).filter(AuthorizationTestCase.program_id == program_id).all()
    }
    table, conflicts = merge_identities(list(cases.values()))
    hierarchies = [[str(r) for r in s.get("role_hierarchy") or []] for s in cases.values() if s.get("role_hierarchy")]
    askable, askable_basis = _askable(table, hierarchies)
    tenants = sorted({i["tenant_id"] for i in table.values() if i["tenant_id"] and not i["conflicts"]})
    people = [i for i in table.values() if not i["anonymous"]]
    undeclared = sorted(i["identity_id"] for i in people if not i["tenant_id"] and "tenant_id" not in i["conflicts"] and tenants)

    hypotheses, evidence = [], []
    for op in coverage["operations"]:
        evaluated: dict[str, list[str]] = defaultdict(list)
        pending: dict[str, str] = {}
        has_owner_context = False
        for entry in op["cases"]:
            spec = cases.get(entry["case_id"], {})
            local = _local_table(spec)
            resource = spec.get("resource") if isinstance(spec.get("resource"), dict) else {}
            owner_id = str(resource.get("owner_identity") or "")
            owner = local.get(owner_id)
            has_owner_context = has_owner_context or owner is not None
            for subject_id in entry["identities"]:
                subject = local.get(subject_id)
                if subject is None or subject_id == owner_id:
                    continue
                if subject["anonymous"]:
                    classes = ["anonymous"]
                elif owner is not None:
                    classes, _ = classify(spec, subject, owner, resource)
                else:
                    continue
                state = entry["identity_states"].get(subject_id)
                for klass in classes:
                    if entry["executed"] and state == "evaluated":
                        evaluated[klass].append(subject_id)
                    else:
                        pending.setdefault(klass, "inconclusive" if entry["executed"] else "reviewed_not_run")
        if evaluated:
            evidence.append({"endpoint_id": op["endpoint_id"], "operation": f"{op['method']} {op['path_template']}",
                             "evaluated": {k: sorted(set(v)) for k, v in evaluated.items()}})
        if not op["priority_reasons"]:
            continue
        label = f"{op['method']} {op['path_template']}"
        for klass in CLASSES:
            if not askable[klass] or evaluated.get(klass):
                continue
            status = pending.get(klass, "untested")
            basis = [askable_basis[klass]] + [r["detail"] for r in op["priority_reasons"]][:2]
            if op["cases"] and not has_owner_context and klass != "anonymous":
                status = "owner_context_missing"
                basis.append("The reviewed cases for this operation declare no resource owner, so this boundary cannot be told apart.")
            hypotheses.append({
                "id": hashlib.sha256(f"{op['endpoint_id']}|{klass}".encode()).hexdigest()[:16],
                "endpoint_id": op["endpoint_id"],
                "operation": label,
                "boundary": klass,
                "status": status,
                "question": f"Has {CLASS_LABEL[klass]} been shown to be denied (or allowed) on {label}?",
                "basis": basis,
            })
    rank = {"untested": 0, "owner_context_missing": 1, "reviewed_not_run": 2, "inconclusive": 3}
    hypotheses.sort(key=lambda h: (rank[h["status"]], h["operation"], CLASSES.index(h["boundary"])))
    return {
        "identities": sorted(({k: v for k, v in i.items() if k != "reference"} for i in table.values()), key=lambda i: i["identity_id"]),
        "identity_conflicts": conflicts,
        "tenants": tenants,
        "askable_boundaries": {k: askable[k] for k in CLASSES},
        "identities_without_tenant": undeclared,
        "boundary_evidence": evidence,
        "hypotheses": hypotheses,
        "summary": {
            "hypotheses": len(hypotheses),
            **{s: sum(1 for h in hypotheses if h["status"] == s) for s in rank},
        },
    }


def draft_for_boundary(db: Session, program_id: str, endpoint_id: str, boundary: str) -> dict:
    """Identities, resource context and gaps for a review-only draft of one boundary question.

    Only unambiguous reviewed metadata is used. Credentials are copied as references, an
    identity with contradictory declarations is left out and reported, and every
    expected decision stays `skip`. Whatever a researcher must still supply is listed in
    `missing_context`; none of it is guessed.
    """
    coverage = build_coverage(db, program_id)
    op = next((o for o in coverage["operations"] if o["endpoint_id"] == endpoint_id), None)
    cases = {
        c.id: c.spec if isinstance(c.spec, dict) else {}
        for c in db.query(AuthorizationTestCase).filter(AuthorizationTestCase.program_id == program_id).all()
    }
    table, all_conflicts = merge_identities(list(cases.values()))
    missing: list[str] = []
    conflicts = [c for c in all_conflicts]

    # The owner comes only from reviewed cases for this very operation.
    owners: dict[str, dict] = {}
    for entry in (op["cases"] if op else []):
        spec = cases.get(entry["case_id"], {})
        resource = spec.get("resource") if isinstance(spec.get("resource"), dict) else {}
        owner_id = str(resource.get("owner_identity") or "")
        if owner_id:
            owners[owner_id] = resource
    owner_id = next(iter(owners)) if len(owners) == 1 else None
    if not owners:
        missing.append("resource.owner_identity: no reviewed case for this operation says who owns the object under test.")
    elif owner_id is None:
        missing.append("resource.owner_identity: reviewed cases for this operation name different owners (" + ", ".join(sorted(owners)) + "); choose one.")

    usable = {k: v for k, v in table.items() if not v["conflicts"]}
    owner = usable.get(owner_id) if owner_id else None
    if owner_id and owner is None:
        missing.append(f"The owner {owner_id} has contradictory declarations, so it cannot anchor a draft.")
        owner_id = None
    chosen: list[dict] = []
    if boundary == "anonymous":
        chosen = [v for v in usable.values() if v["anonymous"]]
        if not chosen:
            missing.append("No anonymous identity has been declared; add one with no credentials.")
    else:
        pool = [v for v in usable.values() if not v["anonymous"] and v["identity_id"] != owner_id]
        if boundary == "cross_tenant":
            if owner and owner["tenant_id"]:
                chosen = [v for v in pool if v["tenant_id"] and v["tenant_id"] != owner["tenant_id"]]
            else:
                chosen = [v for v in pool if v["tenant_id"]]
                if owner_id:
                    missing.append(f"The tenant of the owner {owner_id} is not declared.")
            if not chosen:
                missing.append("No identity in a different tenant is declared.")
        elif boundary == "same_tenant_peer":
            if owner and owner["tenant_id"]:
                chosen = [v for v in pool if v["tenant_id"] == owner["tenant_id"]]
            else:
                chosen = [v for v in pool if v["tenant_id"]]
                if owner_id:
                    missing.append(f"The tenant of the owner {owner_id} is not declared.")
            if not chosen:
                missing.append("No second identity in the owner's tenant is declared.")
        elif boundary == "higher_privilege":
            hierarchies = {tuple(h) for h in [[str(r) for r in s.get("role_hierarchy") or []] for s in cases.values()] if h}
            if len(hierarchies) != 1:
                missing.append("role_hierarchy: " + ("no case declares one." if not hierarchies else "cases declare different hierarchies; choose one."))
            else:
                hierarchy = list(next(iter(hierarchies)))
                if owner and owner["role"] in hierarchy:
                    chosen = [v for v in pool if v["role"] in hierarchy and hierarchy.index(v["role"]) > hierarchy.index(owner["role"])]
                else:
                    missing.append("The owner's role is not declared in the role hierarchy." if owner_id else "The owner is not known, so 'higher than the owner' cannot be decided.")
                    chosen = [v for v in pool if v["role"] in hierarchy]
                if not chosen and owner:
                    missing.append("No identity with a higher role than the owner is declared.")
    identities = []
    if owner:
        identities.append(owner)
    identities += chosen[: _DRAFT_IDENTITY_LIMIT]
    out = []
    for item in identities:
        ref = item["reference"]
        credential = {k: v for k, v in zip(("type", "header", "value_env", "value_keychain"), ref) if v}
        if item["anonymous"]:
            credential = {"type": "static_header", "header": "", "value": ""}
        entry = {"id": item["identity_id"], "credential": credential}
        if item["role"]:
            entry["role"] = item["role"]
        if item["tenant_id"]:
            entry["tenant_id"] = item["tenant_id"]
        out.append(entry)
    resource = None
    if owner_id:
        resource = {"owner_identity": owner_id}
        tenant = (owners.get(owner_id) or {}).get("tenant_id") or (owner["tenant_id"] if owner else None)
        if tenant:
            resource["tenant_id"] = tenant
    hierarchy_out = None
    if boundary == "higher_privilege":
        hs = {tuple(h) for h in [[str(r) for r in s.get("role_hierarchy") or []] for s in cases.values()] if h}
        hierarchy_out = list(next(iter(hs))) if len(hs) == 1 else None
    relevant_conflicts = [c for c in conflicts if c["identity_id"] in {i["identity_id"] for i in table.values()} and c["identity_id"] in {
        v["identity_id"] for v in table.values() if v["conflicts"]
    }]
    if relevant_conflicts:
        missing.append("Identities with contradictory declarations were left out: " + ", ".join(sorted({c["identity_id"] for c in relevant_conflicts})) + ".")
    missing.append("resource.type and resource.object_id: set the concrete object under test.")
    return {
        "identities": out, "resource": resource, "role_hierarchy": hierarchy_out,
        "missing_context": missing, "conflicts": relevant_conflicts,
    }
