"""Read-only health API. Turn controls require authenticated transport in Phase 3."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from voice_assistant.contracts import Schema
from voice_assistant.controller import Controller
from voice_assistant.readiness import Readiness, ReadinessService


class Health(Schema):
    status: Literal["ok"] = "ok"


def create_app(
    readiness: ReadinessService | None = None,
    controller: Controller | None = None,
) -> FastAPI:
    service = readiness or ReadinessService()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if controller is not None:
                await controller.close()
            await service.close()

    app = FastAPI(
        title="Local Voice Assistant",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        return Health()

    @app.get("/ready", response_model=Readiness)
    async def ready(response: Response) -> Readiness:
        result = await service.check()
        response.status_code = 200 if result.status == "ready" else 503
        response.headers["Cache-Control"] = "no-store"
        return result

    return app
