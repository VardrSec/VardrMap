"""Authorization test cases — stored VardrGate specs, scoped to an engagement.

A test case is stored once and referenced from a job by id, so `ScanJob.config`
stays flat (`{"test_case_id": ...}`) and one case can back many runs. The spec is
inlined when the job is handed to a runner, which is why VardrRunner needs no
change to consume it.

The spec is VardrGate's own `AuthorizationTestCase` JSON, stored verbatim.
VardrGate owns that schema; this module validates only what it must:

1. Enough shape that a stored case cannot fail VardrGate's own `validate()` for
   a reason we could have caught at write time (id, identities, request).
2. **That no live credential is stored.** Every identity must reference its
   secret with `value_env` or `value_keychain`, which VardrRunner resolves on the
   operator's machine. This is the one place an operator could paste a live
   bearer token into the database, and the platform's rule is that raw secrets
   are never stored.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action, require_member_write
from models import AuthorizationTestCase
from security import strip_html

router = APIRouter(tags=["test_cases"])

# Mirrors VardrGate's model.CredentialType.
_CREDENTIAL_TYPES = {"bearer", "api_key_header", "static_header"}

# VardrRunner's _resolve_identity_secrets accepts exactly these reference forms.
_SECRET_REFS = ("value_env", "value_keychain")

_MAX_SPEC_BYTES = 256_000


class TestCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default="", max_length=5000)
    spec: dict

    @classmethod
    def _clean(cls, v):
        return strip_html(v) if v else ""


class TestCaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    spec: Optional[dict] = None


def _reject_literal_credentials(spec: dict) -> None:
    """Refuse a spec carrying a live secret.

    VardrGate's examples ship literal `value` fields because it is convenient to
    run one locally. Stored here, that value would sit in the database and travel
    in every API response for the case. Identities must reference a secret the
    runner resolves instead.

    An empty `value` is allowed: the anonymous identity in a BOLA case is
    legitimately `{"type": "static_header", "header": "", "value": ""}`.
    """
    for i, identity in enumerate(spec.get("identities") or []):
        if not isinstance(identity, dict):
            raise HTTPException(status_code=400, detail=f"identities[{i}] must be an object")
        cred = identity.get("credential")
        if not isinstance(cred, dict):
            raise HTTPException(
                status_code=400, detail=f"identities[{i}] must have a credential object"
            )

        ctype = cred.get("type")
        if ctype not in _CREDENTIAL_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"identities[{i}].credential.type must be one of {sorted(_CREDENTIAL_TYPES)}",
            )

        if str(cred.get("value") or "").strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"identities[{i}].credential must not contain a literal 'value' — "
                    f"reference the secret with 'value_env' or 'value_keychain' so it is "
                    f"resolved on the runner and never stored here"
                ),
            )

        refs = [r for r in _SECRET_REFS if str(cred.get(r) or "").strip()]
        if len(refs) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"identities[{i}].credential may specify at most one of {list(_SECRET_REFS)}",
            )
        # A credential with no reference at all is the anonymous case, which is
        # only meaningful for static_header. Requiring one for bearer/api_key
        # catches a case that would fail in VardrGate's validate() at run time.
        if not refs and ctype != "static_header":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"identities[{i}].credential of type '{ctype}' needs 'value_env' or "
                    f"'value_keychain'"
                ),
            )


def _validate_spec(spec: Any) -> dict:
    """Shape checks that mirror VardrGate's own validate(), plus the secret rule."""
    if not isinstance(spec, dict) or not spec:
        raise HTTPException(status_code=400, detail="spec must be a non-empty object")
    if len(str(spec)) > _MAX_SPEC_BYTES:
        raise HTTPException(status_code=400, detail="spec is too large")

    if not str(spec.get("id") or "").strip():
        raise HTTPException(status_code=400, detail="spec.id is required")

    identities = spec.get("identities")
    if not isinstance(identities, list) or not identities:
        raise HTTPException(status_code=400, detail="spec.identities must be a non-empty array")

    seen: set[str] = set()
    for i, identity in enumerate(identities):
        ident_id = str((identity or {}).get("id") or "").strip() if isinstance(identity, dict) else ""
        if not ident_id:
            raise HTTPException(status_code=400, detail=f"identities[{i}] must have an id")
        if ident_id in seen:
            raise HTTPException(status_code=400, detail=f"duplicate identity id '{ident_id}'")
        seen.add(ident_id)

    request = spec.get("request")
    if not isinstance(request, dict):
        raise HTTPException(status_code=400, detail="spec.request is required")
    if not str(request.get("method") or "").strip():
        raise HTTPException(status_code=400, detail="spec.request.method is required")
    if not str(request.get("url") or "").strip():
        raise HTTPException(status_code=400, detail="spec.request.url is required")

    # expected_access is optional in the model but a case without it emits no
    # findings, so a stored one is almost certainly a mistake worth flagging.
    for i, expected in enumerate(spec.get("expected_access") or []):
        if not isinstance(expected, dict):
            raise HTTPException(status_code=400, detail=f"expected_access[{i}] must be an object")
        if str(expected.get("identity_id") or "") not in seen:
            raise HTTPException(
                status_code=400,
                detail=f"expected_access[{i}].identity_id does not match any identity",
            )

    _reject_literal_credentials(spec)
    return spec


def serialize_test_case(tc: AuthorizationTestCase) -> dict:
    return {
        "id": tc.id,
        "program_id": tc.program_id,
        "name": tc.name,
        "test_case_id": tc.test_case_id or "",
        "description": tc.description or "",
        "spec": tc.spec or {},
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
        "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
    }


def _get_or_404(program_id: str, test_case_id: str, db: Session) -> AuthorizationTestCase:
    """Fetch scoped to the engagement. Caller must have verified engagement access."""
    row = (
        db.query(AuthorizationTestCase)
        .filter(
            AuthorizationTestCase.id == test_case_id,
            AuthorizationTestCase.program_id == program_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Test case not found")
    return row


@router.get("/engagements/{program_id}/test-cases")
def list_test_cases(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    rows = (
        db.query(AuthorizationTestCase)
        .filter(AuthorizationTestCase.program_id == program_id)
        .order_by(AuthorizationTestCase.created_at.desc())
        .all()
    )
    return {"test_cases": [serialize_test_case(r) for r in rows]}


@router.post("/engagements/{program_id}/test-cases", status_code=201)
def create_test_case(
    program_id: str,
    body: TestCaseCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    spec = _validate_spec(body.spec)

    row = AuthorizationTestCase(
        program_id=program_id,
        owner_github_id=current_user["github_id"],
        name=body.name,
        test_case_id=str(spec.get("id") or "")[:200],
        description=strip_html(body.description) if body.description else "",
        spec=spec,
    )
    db.add(row)
    db.flush()
    log_action(db, current_user["github_id"], "create", "test_case", row.id, program_id)
    db.commit()
    db.refresh(row)
    return serialize_test_case(row)


@router.get("/engagements/{program_id}/test-cases/{test_case_id}")
def get_test_case(
    program_id: str,
    test_case_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    return serialize_test_case(_get_or_404(program_id, test_case_id, db))


@router.patch("/engagements/{program_id}/test-cases/{test_case_id}")
def update_test_case(
    program_id: str,
    test_case_id: str,
    body: TestCaseUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    row = _get_or_404(program_id, test_case_id, db)

    fields = body.model_dump(exclude_unset=True)
    if fields.get("spec") is not None:
        spec = _validate_spec(fields["spec"])
        row.spec = spec
        row.test_case_id = str(spec.get("id") or "")[:200]
    if fields.get("name") is not None:
        row.name = fields["name"]
    if fields.get("description") is not None:
        row.description = strip_html(fields["description"]) or ""

    row.updated_at = datetime.now(timezone.utc)
    log_action(db, current_user["github_id"], "update", "test_case", row.id, program_id)
    db.commit()
    db.refresh(row)
    return serialize_test_case(row)


@router.delete("/engagements/{program_id}/test-cases/{test_case_id}")
def delete_test_case(
    program_id: str,
    test_case_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    row = _get_or_404(program_id, test_case_id, db)
    log_action(db, current_user["github_id"], "delete", "test_case", test_case_id, program_id)
    db.delete(row)
    db.commit()
    return {"message": "Test case deleted"}
