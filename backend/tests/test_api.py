import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from voice_assistant.__main__ import main
from voice_assistant.api import create_app
from voice_assistant.controller import Controller
from voice_assistant.readiness import ComponentName, Probe, ReadinessService
from voice_assistant.state import AssistantState

from .fakes import FakeEngines


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            yield client


async def available() -> bool:
    return True


def ready_probes() -> dict[ComponentName, Probe]:
    return dict.fromkeys(ComponentName, available)


async def test_liveness_is_not_readiness_and_default_does_not_claim_engines_ready() -> None:
    async with client_for(create_app()) as client:
        health = await client.get("/health")
        assert health.status_code == 200 and health.json() == {"status": "ok"}
        ready = await client.get("/ready")
        assert ready.status_code == 503
        assert ready.json()["status"] == "not_ready"
        assert all(c["status"] == "not_configured" for c in ready.json()["components"])
        assert ready.headers["cache-control"] == "no-store"
        assert (await client.post("/turns")).status_code == 404
        assert (await client.get("/docs")).status_code == 404


async def test_all_ready_returns_200() -> None:
    async with client_for(create_app(ReadinessService(ready_probes()))) as client:
        response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


@pytest.mark.parametrize("name", [ComponentName.LLM, ComponentName.TTS])
async def test_unavailable_engine_is_visible_without_exception_details(name: ComponentName) -> None:
    async def unavailable() -> bool:
        raise RuntimeError("secret local path and content")

    probes = ready_probes()
    probes[name] = unavailable
    async with client_for(create_app(ReadinessService(probes))) as client:
        response = await client.get("/ready")
        assert response.status_code == 503
        assert {"name": name.value, "status": "unavailable"} in response.json()["components"]
        assert "secret" not in response.text


async def test_health_remains_responsive_while_readiness_and_turn_are_waiting() -> None:
    entered = asyncio.Event()
    gate = asyncio.Event()

    async def slow_probe() -> bool:
        entered.set()
        await gate.wait()
        return True

    fake = FakeEngines()
    fake.gates["llm"] = asyncio.Event()
    controller = Controller(fake.components())
    await controller.set_microphone(True)
    controller.release(controller.begin_turn())
    await fake.reached("llm")
    probes = ready_probes()
    probes[ComponentName.LLM] = slow_probe
    app = create_app(ReadinessService(probes, deadline=0.1), controller)
    async with client_for(app) as client:
        request = asyncio.create_task(client.get("/ready"))
        await entered.wait()
        async with asyncio.timeout(1):
            health = await client.get("/health")
            assert health.status_code == 200
            assert not gate.is_set() and controller.busy
            response = await request
        assert response.status_code == 503
        assert {"name": "llm", "status": "timeout"} in response.json()["components"]
    assert not controller.busy
    assert not controller.microphone_enabled
    assert controller.state == AssistantState.IDLE


async def test_host_validation_and_no_cross_origin_access() -> None:
    async with client_for(create_app()) as client:
        assert (await client.get("/health", headers={"Host": "evil.example"})).status_code == 400
        response = await client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers


def test_supported_launcher_binds_only_loopback() -> None:
    with patch("voice_assistant.__main__.uvicorn.run") as run:
        main()
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["access_log"] is False
    assert run.call_args.kwargs["proxy_headers"] is False


async def test_repeated_readiness_does_not_spawn_more_stubborn_probes() -> None:
    gate = asyncio.Event()
    calls = 0

    async def stubborn() -> bool:
        nonlocal calls
        calls += 1
        while not gate.is_set():
            try:
                await gate.wait()
            except asyncio.CancelledError:
                continue
        return True

    service = ReadinessService({ComponentName.LLM: stubborn}, deadline=0.01)
    try:
        await service.check()
        await service.check()
        assert calls == 1
    finally:
        gate.set()
        await service.close()
