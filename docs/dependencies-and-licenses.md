# Backend dependency decisions

Phase 2 uses Python 3.12 and uv. Exact resolutions are in `uv.lock`.

| Dependency | Purpose | Upstream license |
| --- | --- | --- |
| Pydantic | Validate immutable component data and UI/API schemas | MIT |
| FastAPI | Thin health/readiness HTTP routes | MIT |
| Uvicorn | Local ASGI server | BSD-3-Clause |
| HTTPX (development) | In-process ASGI endpoint tests | BSD-3-Clause |
| pytest | Backend tests | MIT |
| pytest-asyncio | Async cancellation and responsiveness tests | Apache-2.0 |
| Ruff | Python linting and formatting | MIT |
| mypy | Strict static type checks | MIT |
| uv_build | Editable installation of `backend/src/voice_assistant` | MIT OR Apache-2.0 |

The licenses were checked against upstream PyPI project metadata before adding
these dependencies. Pydantic is already transitive through existing tooling;
declaring it directly records the backend's own requirement. No additional
inference, audio, logging or workflow framework is introduced.

Package installation uses PyPI. Phase 2 tests use synthetic data and fake engines,
require no models or microphone, and make no external API calls. The local health
server performs no downloads or engine initialization. Inference dependencies
remain those verified in [verification.md](verification.md); distribution of Piper
and voices still requires the review recorded there.

Sources: [Pydantic](https://pypi.org/project/pydantic/),
[FastAPI](https://pypi.org/project/fastapi/), [Uvicorn](https://pypi.org/project/uvicorn/),
[HTTPX](https://pypi.org/project/httpx/), [pytest](https://pypi.org/project/pytest/),
[pytest-asyncio](https://pypi.org/project/pytest-asyncio/),
[Ruff](https://pypi.org/project/ruff/), [mypy](https://pypi.org/project/mypy/),
[uv_build](https://pypi.org/project/uv-build/).
