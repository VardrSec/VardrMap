"""Relationships between identities, tenants, resources and operations, and the
boundaries between them that have not been evaluated.

Everything here is read from facts a person reviewed and saved in stored Gate cases:
each identity's declared `role` and `tenant_id`, a case's `resource` context
(`owner_identity`, `tenant_id`) and its `role_hierarchy`, plus the current coverage
result for each case. Nothing is inferred from traffic, nothing is guessed about who
should have access, and an identity whose tenant or role was never declared stays
unclassified instead of being assumed.

A *boundary class* describes how a caller relates to the owner of the object under
test:

* `cross_tenant`   the caller's declared tenant differs from the object's tenant.
* `same_tenant_peer` the caller shares the object's tenant but is not its owner.
* `higher_privilege` the caller's role outranks the owner's in the case's role hierarchy.
* `anonymous`      the caller sends no credentials.

A hypothesis is a question worth putting to the target, never a finding. It says
which boundary has no current, evaluated result on an operation and lists the
facts that make the question askable.
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


def _is_anonymous(identity: dict) -> bool:
    credential = identity.get("credential") if isinstance(identity.get("credential"), dict) else {}
    return credential.get("type") == "static_header" and not credential.get("header")


def _identity_table(specs: list[dict]) -> dict[str, dict]:
    """First declaration of each identity id, with the attributes a person reviewed."""
    table: dict[str, dict] = {}
    for spec in specs:
        for identity in spec.get("identities") or []:
            if isinstance(identity, dict) and identity.get("id") and identity["id"] not in table:
                table[str(identity["id"])] = {
                    "identity_id": str(identity["id"]),
                    "role": str(identity.get("role") or "") or None,
                    "tenant_id": str(identity.get("tenant_id") or "") or None,
                    "anonymous": _is_anonymous(identity),
                }
    return table


def classify(spec: dict, subject: dict, owner: dict, resource: dict) -> tuple[list[str], list[str]]:
    """Boundary classes of `subject` relative to the owner, with the facts behind them."""
    classes, basis = [], []
    if subject["anonymous"]:
        return ["anonymous"], [f"{subject['identity_id']} sends no credentials"]
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


def build_relationships(db: Session, program_id: str) -> dict:
    coverage = build_coverage(db, program_id)
    cases = {
        c.id: c.spec if isinstance(c.spec, dict) else {}
        for c in db.query(AuthorizationTestCase).filter(AuthorizationTestCase.program_id == program_id).all()
    }
    identities = _identity_table(list(cases.values()))
    people = [i for i in identities.values() if not i["anonymous"]]

    # Which boundary classes this engagement's reviewed identities make askable at all.
    tenants = sorted({i["tenant_id"] for i in people if i["tenant_id"]})
    by_tenant: dict[str, int] = defaultdict(int)
    for person in people:
        if person["tenant_id"]:
            by_tenant[person["tenant_id"]] += 1
    ranked_roles = {
        r for spec in cases.values() for r in (spec.get("role_hierarchy") or [])
        if r in {p["role"] for p in people}
    }
    askable = {
        "cross_tenant": len(tenants) >= 2,
        "same_tenant_peer": any(n >= 2 for n in by_tenant.values()),
        "higher_privilege": len(ranked_roles) >= 2,
        "anonymous": any(i["anonymous"] for i in identities.values()),
    }
    askable_basis = {
        "cross_tenant": "Identities are declared in tenants: " + ", ".join(tenants) + ".",
        "same_tenant_peer": "Several identities share a tenant: " + ", ".join(f"{t} ({n})" for t, n in sorted(by_tenant.items()) if n >= 2) + ".",
        "higher_privilege": "Roles in a case's role hierarchy: " + ", ".join(sorted(ranked_roles)) + ".",
        "anonymous": "An identity without credentials is declared: " + ", ".join(sorted(i["identity_id"] for i in identities.values() if i["anonymous"])) + ".",
    }

    undeclared = sorted(i["identity_id"] for i in people if not i["tenant_id"] and tenants)
    hypotheses = []
    for op in coverage["operations"]:
        reasons = {r["code"] for r in op["priority_reasons"]}
        if not reasons:
            continue
        evaluated: dict[str, list[str]] = defaultdict(list)
        pending: dict[str, str] = {}
        has_owner_context = False
        for entry in op["cases"]:
            spec = cases.get(entry["case_id"], {})
            resource = spec.get("resource") if isinstance(spec.get("resource"), dict) else {}
            owner_id = str(resource.get("owner_identity") or "")
            owner = identities.get(owner_id)
            has_owner_context = has_owner_context or owner is not None
            for subject_id in entry["identities"]:
                subject = identities.get(subject_id)
                if subject is None or subject_id == owner_id:
                    continue
                # An anonymous caller needs no owner to be classified; every other
                # class is defined relative to the reviewed owner of the object.
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
        label = f"{op['method']} {op['path_template']}"
        for klass in CLASSES:
            if not askable[klass] or evaluated.get(klass):
                continue
            status = pending.get(klass, "untested")
            basis = [askable_basis[klass]]
            basis += [r["detail"] for r in op["priority_reasons"]][:2]
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
        "identities": sorted(identities.values(), key=lambda i: i["identity_id"]),
        "tenants": tenants,
        "askable_boundaries": {k: askable[k] for k in CLASSES},
        "identities_without_tenant": undeclared,
        "hypotheses": hypotheses,
        "summary": {
            "hypotheses": len(hypotheses),
            **{s: sum(1 for h in hypotheses if h["status"] == s) for s in rank},
        },
    }
