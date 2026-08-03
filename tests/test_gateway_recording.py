"""The gateway client records every call so a Contract can be checked later.

Each ``chat`` call appends a CallRecord to ``client.calls`` carrying the parsed
reply (or None), the wall-clock elapsed seconds, and the raised error (or None).
This is the ledger a resilience Contract inspects at teardown.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from pytest_resilience_agent.gateway import AIGatewayClient

_URL = "https://gateway.local"
_COMPLETIONS = f"{_URL}/chat/completions"


def _ok_body(content: str = "hello", model: str = "backup-model") -> dict:
    return {"model": model, "choices": [{"message": {"content": content}}]}


@respx.mock
def test_successful_chat_is_recorded() -> None:
    respx.post(_COMPLETIONS).mock(return_value=httpx.Response(200, json=_ok_body()))
    client = AIGatewayClient(base_url=_URL)
    try:
        reply = client.chat([{"role": "user", "content": "hi"}], model="primary-model")
    finally:
        client.close()

    assert len(client.calls) == 1
    record = client.calls[0]
    assert record.reply is reply
    assert record.model_requested == "primary-model"
    assert record.error is None
    assert record.elapsed is not None and record.elapsed >= 0


@respx.mock
def test_failed_chat_is_recorded_and_reraised() -> None:
    respx.post(_COMPLETIONS).mock(return_value=httpx.Response(502))
    client = AIGatewayClient(base_url=_URL)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.chat([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert len(client.calls) == 1
    record = client.calls[0]
    assert record.reply is None
    assert isinstance(record.error, httpx.HTTPStatusError)
    assert record.elapsed is not None


@respx.mock
def test_malformed_200_body_is_recorded_and_reraised() -> None:
    # A 200 with a non-JSON body (a proxy error page) must still land in the
    # ledger with error set, so the "every call" invariant holds and a contract
    # sees the failed call instead of reporting "never called".
    respx.post(_COMPLETIONS).mock(
        return_value=httpx.Response(200, content=b"<html>proxy error</html>")
    )
    client = AIGatewayClient(base_url=_URL)
    try:
        with pytest.raises(Exception):  # noqa: B017 - httpx raises a JSON decode error
            client.chat([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert len(client.calls) == 1
    record = client.calls[0]
    assert record.reply is None
    assert record.error is not None
    assert record.elapsed is not None


@respx.mock
def test_calls_ledger_starts_empty() -> None:
    client = AIGatewayClient(base_url=_URL)
    try:
        assert client.calls == []
    finally:
        client.close()
