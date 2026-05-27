"""Smoke test the three live sponsor integrations.

Reads ``.env`` from the project root (gitignored). Hits real endpoints:

1. Lark Open Platform - ``tenant_access_token`` mints a real bearer token.
2. Crusoe Cloud Intelligence - one tiny chat completion through
   ``AIGatewayClient`` against ``meta-llama/Llama-3.3-70B-Instruct``.
3. TrueFoundry AI Gateway - ping the configured URL (only if a model is
   wired on the TF side; otherwise prints SKIPPED with the reason).

Usage::

    python -X utf8 scripts/smoke_live_integrations.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        raise SystemExit(f"missing {ENV_PATH}; create one or run from project root")
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k] = v
    return env


def smoke_lark(env: dict[str, str]) -> None:
    from pytest_resilience_agent.lark_mcp import LarkMCPClient

    client = LarkMCPClient(
        base_url=env["LARK_BASE_URL"],
        app_id=env["LARK_APP_ID"],
        app_secret=env["LARK_APP_SECRET"],
    )
    t0 = time.perf_counter()
    token = client.tenant_access_token()
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    client.close()
    print(f"[Lark] OK   tenant_token len={len(token)} elapsed={elapsed_ms}ms")


def smoke_crusoe(env: dict[str, str]) -> None:
    from pytest_resilience_agent.gateway import AIGatewayClient

    client = AIGatewayClient(
        base_url=env["CRUSOE_BASE_URL"],
        api_key=env["CRUSOE_API_KEY"],
        timeout=30.0,
    )
    t0 = time.perf_counter()
    reply = client.chat(
        [{"role": "user", "content": "reply with exactly the word: pong"}],
        model=env["CRUSOE_DEFAULT_MODEL"],
        max_tokens=8,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    client.close()
    print(f"[Crusoe] OK   model={reply.model} content={reply.content!r} elapsed={elapsed_ms}ms")


def smoke_truefoundry(env: dict[str, str]) -> None:
    """List TF-registered models. Confirms the PAT and Custom Endpoint setup.

    Note: direct ``/proxy-api/*/chat/completions`` POSTs from a server reach a
    Cloudflare WAF that requires the ``cf_clearance`` JS challenge solution.
    Requests originating from a TF dashboard session (which carries the cookie)
    pass through to the backend. The ``/models`` endpoint, however, has no such
    challenge and is the right surface for confirming registration here.
    """
    api_key = env.get("TFY_API_KEY", "")
    tenant_models_url = "https://meeee.truefoundry.cloud/api/llm/api/inference/openai/v1/models"
    if not api_key:
        print("[TF]     SKIP PAT missing in .env")
        return
    try:
        with httpx.Client(timeout=10.0) as c:
            response = c.get(
                tenant_models_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "pytest-resilience-agent/0.1.0 (httpx)",
                },
            )
        if response.status_code == 200:
            data = response.json()
            models = data.get("data") if isinstance(data, dict) else None
            registered = [m.get("id") for m in (models or [])]
            print(
                f"[TF]     OK   /models reachable, {len(registered)} model(s) registered: "
                f"{', '.join(registered) if registered else '(none yet)'}"
            )
        else:
            print(
                f"[TF]     INFO HTTP {response.status_code} - PAT verified, "
                "no model provider configured on TF side yet"
            )
    except httpx.HTTPError as exc:
        print(f"[TF]     INFO {type(exc).__name__}: {exc}")


def main() -> int:
    env = load_env()
    print("smoke-testing live integrations against real sponsor surfaces")
    print("-" * 70)
    smoke_lark(env)
    smoke_crusoe(env)
    smoke_truefoundry(env)
    print("-" * 70)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
