import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from service.api import deps
from service.api.datasets import execute_collection
from service.api.schemas import PlanRequest
from service.audit import audited
from service.config import Settings
from service.planning import Planner
from service.providers import resolve_source
from service.storage import Storage

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/plan_and_collect")
def plan_and_collect(
    body: PlanRequest,
    db: Storage = Depends(deps.storage),
    cfg: Settings = Depends(deps.settings),
    planner: Planner = Depends(deps.planner),
):
    query = body.query.strip()
    payload = {"query": query, "dataset_id": body.dataset_id, "collect": body.collect}
    with audited(db, "plan_and_collect", payload) as run:
        dataset = deps.require_dataset(db, body.dataset_id) if body.dataset_id else None
        plan = planner.plan(query, resolve_source(dataset["source"]) if dataset else None)
        error = plan.reason if plan.needs_review else (f"LLM: {plan.llm_error}" if plan.llm_error else None)
        db.add_agent_run(query, plan.to_record(), plan.needs_review, error)
        response = plan.to_response()
        run.close({**response, "llm_raw": plan.llm_raw}, "needs_review" if plan.needs_review else "ok", error)

    if not (body.collect and dataset and not plan.needs_review):
        return response
    with audited(db, "collect", {"dataset_id": dataset["dataset_id"], "query": query}) as run:
        result = execute_collection(db, cfg, run, dataset, plan)
    if isinstance(result, JSONResponse):
        return JSONResponse(status_code=result.status_code, content={**response, "collect": json.loads(result.body)})
    return {**response, "records_saved": result["records_saved"]}
