import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from service import __version__
from service.api import ai, audit, datasets
from service.config import get_settings
from service.storage import Storage

WEB = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = get_settings()
    Storage(cfg.database_path).migrate()
    log.info("database: %s", cfg.database_path)
    log.info("llm: %s", f"{cfg.llm_model} (t={cfg.llm_temperature})" if cfg.llm_enabled else "disabled")
    log.info("exchangerate.host key: %s", "set" if cfg.exchangerate_key else "missing")
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="Разведчик валют и криптоактивов", version=__version__, lifespan=lifespan)
    application.include_router(datasets.router)
    application.include_router(ai.router)
    application.include_router(audit.router)
    application.mount("/static", StaticFiles(directory=WEB), name="static")

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB / "index.html")

    @application.get("/health", tags=["service"])
    def health():
        cfg = get_settings()
        return {
            "status": "ok",
            "version": __version__,
            "llm_configured": cfg.llm_enabled,
            "llm_model": cfg.llm_model,
            "llm_temperature": cfg.llm_temperature,
            "exchangerate_configured": bool(cfg.exchangerate_key),
        }

    return application


app = create_app()
