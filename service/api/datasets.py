import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from service.analyst import Analyst, CONTEXT_LIMIT
from service.api import deps
from service.api.schemas import CollectRequest, DatasetCreate, QuestionRequest
from service.audit import AuditRun, audited
from service.collector import collect as run_calls
from service.config import Settings
from service.planning import Plan, Planner
from service.providers import ProviderError, resolve_source
from service.storage import Storage

router = APIRouter(prefix="/datasets", tags=["datasets"])
PLAN_REUSE_WINDOW = timedelta(minutes=15)


def _required(value: str, name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"Поле {name} обязательно")
    if len(cleaned) > 200:
        raise HTTPException(status_code=400, detail=f"Поле {name}: не более 200 символов")
    return cleaned


@router.post("")
def create_dataset(body: DatasetCreate, db: Storage = Depends(deps.storage)):
    with audited(db, "create_dataset", body.model_dump()) as run:
        name = _required(body.name, "name")
        source = resolve_source(_required(body.source, "source"))
        if source is None:
            raise HTTPException(status_code=422, detail="Источник не поддерживается: CoinGecko, exchangerate.host")
        result = {"status": "ok", "dataset_id": db.create_dataset(name, source.title)}
        run.close(result)
        return result


@router.get("")
def list_datasets(db: Storage = Depends(deps.storage)):
    return db.datasets()


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, db: Storage = Depends(deps.storage)):
    return deps.require_dataset(db, dataset_id)


def execute_collection(db: Storage, cfg: Settings, run: AuditRun, dataset: dict, plan: Plan):
    try:
        saved = db.add_records(dataset["dataset_id"], run_calls(plan, cfg))
    except ProviderError as exc:
        body = {"status": "error", "records_saved": 0, "detail": exc.message}
        run.close(body, "error", exc.message)
        return JSONResponse(status_code=exc.status_code, content=body)
    result = {"status": "ok", "records_saved": saved}
    run.close({**result, "api_url": plan.api_url, "calls": len(plan.calls), "fields_to_keep": plan.fields_to_keep})
    return result


@router.post("/{dataset_id}/collect")
def collect(
    dataset_id: str,
    body: CollectRequest,
    db: Storage = Depends(deps.storage),
    cfg: Settings = Depends(deps.settings),
    planner: Planner = Depends(deps.planner),
):
    query = body.query.strip()
    with audited(db, "collect", {"dataset_id": dataset_id, "query": query}) as run:
        dataset = deps.require_dataset(db, dataset_id)
        source = resolve_source(dataset["source"])
        cached = db.recent_plan(query, source.code, PLAN_REUSE_WINDOW) if query and source else None
        if cached:
            plan = Plan.from_record(cached)
        else:
            plan = planner.plan(query, source)
            db.add_agent_run(query, plan.to_record(), plan.needs_review, plan.reason or plan.llm_error)
        if plan.needs_review:
            result = {"status": "needs_review", "records_saved": 0, "reason": plan.reason, "hints": plan.hints}
            run.close(result, "needs_review", plan.reason)
            return JSONResponse(status_code=422, content=result)
        return execute_collection(db, cfg, run, dataset, plan)


@router.get("/{dataset_id}/records")
def records(dataset_id: str, limit: int = Query(default=50, ge=1, le=500), db: Storage = Depends(deps.storage)):
    with audited(db, "list_records", {"dataset_id": dataset_id, "limit": limit}) as run:
        deps.require_dataset(db, dataset_id)
        rows = db.records(dataset_id, limit)
        run.close({"count": len(rows)})
        return rows


@router.get("/{dataset_id}/export")
def export(
    dataset_id: str,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    limit: int = Query(default=500, ge=1, le=500),
    db: Storage = Depends(deps.storage),
):
    with audited(db, "export", {"dataset_id": dataset_id, "format": format, "limit": limit}) as run:
        dataset = deps.require_dataset(db, dataset_id)
        rows = db.records(dataset_id, limit)
        run.close({"count": len(rows), "format": format})
    headers = {"Content-Disposition": f'attachment; filename="dataset_{dataset["dataset_id"][:8]}.{format}"'}
    if format == "json":
        return JSONResponse(content=rows, headers=headers)
    return Response(content=to_csv(rows), media_type="text/csv; charset=utf-8", headers=headers)


def to_csv(rows: list[dict]) -> str:
    meta = ["id", "created_at", "dataset_id", "source"]
    columns = list(meta)
    for row in rows:
        columns += [k for k in row["record_json"] if k not in columns]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({**{k: row[k] for k in meta}, **row["record_json"]})
    return "\ufeff" + buffer.getvalue()


@router.post("/{dataset_id}/ask")
def ask(
    dataset_id: str,
    body: QuestionRequest,
    db: Storage = Depends(deps.storage),
    analyst: Analyst = Depends(deps.analyst),
):
    question = body.question.strip()
    with audited(db, "ask", {"dataset_id": dataset_id, "question": question}) as run:
        dataset = deps.require_dataset(db, dataset_id)
        if not question:
            raise HTTPException(status_code=400, detail="Поле question обязательно")
        answer = analyst.answer(question, dataset, db.records(dataset_id, CONTEXT_LIMIT))
        error = answer.reason if answer.needs_review else None
        db.add_agent_run(question, {**answer.to_record(), "dataset_id": dataset_id}, answer.needs_review, error)
        response = answer.to_response()
        run.close({**response, "llm_raw": answer.llm_raw}, "needs_review" if answer.needs_review else "ok", error)
        return response
