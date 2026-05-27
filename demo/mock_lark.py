"""Mock Lark MCP server for offline demos.

Implements the two endpoints our LarkMCPClient exercises:

- ``GET  /v1/projects/{project}/tests?status=failed`` - list failing tests
- ``POST /v1/projects/{project}/tests/{test_name}/resolutions`` - log resolution

The mock keeps a tiny in-memory store of failing tests so the demo can
walk the full loop: list failures → generate resilience test → report
resolution → see the resolution in subsequent calls.

Run standalone::

    uvicorn demo.mock_lark:app --port 8801
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class FailingTest(BaseModel):
    name: str
    status: str = "failed"
    path: str
    last_failure: str
    resolution: dict | None = None


_FAILING: dict[str, list[FailingTest]] = {
    "demo": [
        FailingTest(
            name="test_summarise_keeps_responding_when_gateway_429",
            path="tests/test_summarise.py::test_summarise_keeps_responding_when_gateway_429",
            last_failure="httpx.HTTPStatusError: 429 Too Many Requests",
        ),
        FailingTest(
            name="test_summarise_falls_back_when_primary_5xx",
            path="tests/test_summarise.py::test_summarise_falls_back_when_primary_5xx",
            last_failure="httpx.HTTPStatusError: 502 Bad Gateway",
        ),
        FailingTest(
            name="test_summarise_surfaces_clean_error_on_persistent_outage",
            path="tests/test_summarise.py::test_summarise_surfaces_clean_error_on_persistent_outage",
            last_failure="httpx.HTTPStatusError: 503 Service Unavailable",
        ),
    ]
}


app = FastAPI(title="mock-lark-mcp", version="0.1.0")


class ResolutionRequest(BaseModel):
    pytest_path: str
    source: str


@app.get("/v1/projects/{project}/tests")
def list_tests(project: str, status: str = "failed") -> dict:
    """List tests in the project, optionally filtered by status."""
    tests = _FAILING.get(project, [])
    if status:
        tests = [t for t in tests if t.status == status]
    return {"tests": [t.model_dump() for t in tests]}


@app.post("/v1/projects/{project}/tests/{test_name}/resolutions")
def report_resolution(
    project: str,
    test_name: str,
    req: ResolutionRequest,
) -> dict:
    """Attach a resolution to a failing test."""
    tests = _FAILING.get(project, [])
    for test in tests:
        if test.name == test_name:
            test.resolution = {
                "pytest_path": req.pytest_path,
                "source": req.source,
                "reported_at": datetime.now(UTC).isoformat(),
            }
            return {"ok": True, "test": test.model_dump()}
    raise HTTPException(404, detail=f"test {test_name!r} not found in project {project!r}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
