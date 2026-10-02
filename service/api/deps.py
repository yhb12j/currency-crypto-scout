from fastapi import Depends, HTTPException

from service.analyst import Analyst
from service.config import Settings, get_settings
from service.llm import LLMClient
from service.planning import Planner
from service.storage import Storage


def settings() -> Settings:
    return get_settings()


def storage(cfg: Settings = Depends(settings)) -> Storage:
    return Storage(cfg.database_path, cfg.redact)


def planner(cfg: Settings = Depends(settings)) -> Planner:
    return Planner(LLMClient(cfg))


def analyst(cfg: Settings = Depends(settings)) -> Analyst:
    return Analyst(LLMClient(cfg))


def require_dataset(db: Storage, dataset_id: str) -> dict:
    dataset = db.dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Набор данных не найден")
    return dataset
