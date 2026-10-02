from typing import Literal

from fastapi import APIRouter, Depends, Query

from service.api import deps
from service.storage import Storage

router = APIRouter(tags=["audit"])


@router.get("/audit/runs")
def audit_runs(
    limit: int = Query(default=100, ge=1, le=500),
    status: Literal["ok", "needs_review", "error"] | None = None,
    action: str | None = Query(default=None, max_length=50),
    db: Storage = Depends(deps.storage),
):
    return db.audit(limit, status, action)


@router.get("/audit/summary")
def audit_summary(db: Storage = Depends(deps.storage)):
    return db.audit_stats()


@router.get("/agent_runs")
def agent_runs(
    limit: int = Query(default=50, ge=1, le=500),
    needs_review: bool | None = None,
    db: Storage = Depends(deps.storage),
):
    return db.agent_runs(limit, needs_review)
