from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db
from deps import get_current_user, get_engagement_or_404, log_action
from models import ManualTest
from schemas import ManualTestCreate, ManualTestUpdate
from serializers import serialize_manual_test

router = APIRouter()


@router.get("/engagements/{program_id}/manual-tests")
def get_manual_tests(
    program_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    query = db.query(ManualTest).filter(ManualTest.program_id == program_id)
    total = query.count()
    tests = query.order_by(ManualTest.created_at.desc()).offset(offset).limit(limit).all()
    return {"manual_tests": [serialize_manual_test(t) for t in tests], "total": total, "offset": offset, "limit": limit}


@router.post("/engagements/{program_id}/manual-tests")
def add_manual_test(
    program_id: str,
    payload: ManualTestCreate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    test = ManualTest(
        program_id=program_id,
        title=payload.title,
        hypothesis=payload.hypothesis or "",
        payload=payload.payload or "",
        evidence=payload.evidence or "",
        status=payload.status,
    )
    db.add(test)
    db.flush()
    log_action(db, current_user["github_id"], "create", "manual_test", test.id, program_id)
    db.commit()
    db.refresh(test)
    return serialize_manual_test(test)


@router.patch("/engagements/{program_id}/manual-tests/{test_id}")
def update_manual_test(
    program_id: str,
    test_id: str,
    payload: ManualTestUpdate,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    test = db.query(ManualTest).filter(
        ManualTest.id == test_id,
        ManualTest.program_id == program_id,
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Manual test not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(test, key, value)
    log_action(db, current_user["github_id"], "update", "manual_test", test_id, program_id)
    db.commit()
    db.refresh(test)
    return serialize_manual_test(test)


@router.delete("/engagements/{program_id}/manual-tests/{test_id}")
def delete_manual_test(
    program_id: str,
    test_id: str,
    current_user: dict[str, str] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    test = db.query(ManualTest).filter(
        ManualTest.id == test_id,
        ManualTest.program_id == program_id,
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Manual test not found")
    log_action(db, current_user["github_id"], "delete", "manual_test", test_id, program_id)
    db.delete(test)
    db.commit()
    return {"message": "Manual test deleted"}
