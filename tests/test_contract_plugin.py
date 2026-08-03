"""End-to-end: the plugin checks a declared contract automatically.

A test declares ``contract=`` on the resilience marker and makes gateway calls.
After the test body runs, the plugin evaluates the contract against the calls
the gateway recorded, and fails the test if the contract is violated. The test
body itself carries no contract asserts.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

_GATEWAY = "https://gw.local"


def _make_test(pytester: pytest.Pytester, *, contract: str, content: str, extra: str = "") -> None:
    pytester.makepyfile(
        f"""
        import httpx
        import respx
        import pytest

        from pytest_resilience_agent import Contract

        @respx.mock
        @pytest.mark.resilience(contract={contract})
        def test_agent(ai_gateway):
            respx.post("{_GATEWAY}/chat/completions").mock(
                return_value=httpx.Response(
                    200, json={{"model": "backup", "choices": [{{"message": {{"content": "{content}"}}}}]}}
                )
            )
            ai_gateway.chat([{{"role": "user", "content": "hi"}}], model="primary")
            {extra}
        """
    )


def test_contract_fails_the_test_when_violated(pytester: pytest.Pytester) -> None:
    # responds required, but the gateway returns empty content -> contract fails
    _make_test(pytester, contract="Contract(responds=True)", content="")
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*resilience contract violated*", "*responds*"])


def test_contract_passes_when_satisfied(pytester: pytest.Pytester) -> None:
    _make_test(pytester, contract="Contract(responds=True)", content="here you go")
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(passed=1)


def test_no_contract_kwarg_does_not_interfere(pytester: pytest.Pytester) -> None:
    # Marker without contract= must behave exactly as before (no enforcement).
    _make_test(pytester, contract="None", content="")
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(passed=1)


def test_names_fallback_contract_end_to_end(pytester: pytest.Pytester) -> None:
    # reply model "backup" differs from requested "primary" -> names_fallback holds
    _make_test(pytester, contract="Contract(names_fallback=True)", content="ok")
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(passed=1)


def test_contract_declared_but_gateway_never_called_fails(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest
        from pytest_resilience_agent import Contract

        @pytest.mark.resilience(contract=Contract(responds=True))
        def test_agent(ai_gateway):
            pass  # declared a contract but never drove the gateway
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*never called*"])


def test_surfaces_clear_error_catches_a_silent_empty_across_two_calls(
    pytester: pytest.Pytester,
) -> None:
    # Two calls: first returns content, second returns empty with a 200 (no
    # raised error). responds= is existential and would pass, but
    # surfaces_clear_error= is universal and must flag the silent-empty second call.
    pytester.makepyfile(
        f"""
        import httpx
        import respx
        import pytest

        from pytest_resilience_agent import Contract

        @respx.mock
        @pytest.mark.resilience(contract=Contract(surfaces_clear_error=True))
        def test_agent(ai_gateway):
            route = respx.post("{_GATEWAY}/chat/completions")
            route.side_effect = [
                httpx.Response(200, json={{"model": "m", "choices": [{{"message": {{"content": "ok"}}}}]}}),
                httpx.Response(200, json={{"model": "m", "choices": [{{"message": {{"content": ""}}}}]}}),
            ]
            ai_gateway.chat([{{"role": "user", "content": "one"}}])
            ai_gateway.chat([{{"role": "user", "content": "two"}}])
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*surfaces_clear_error*"])


def test_body_failure_is_not_masked_by_a_passing_contract(pytester: pytest.Pytester) -> None:
    # The body asserts False after a satisfying call; the original failure must
    # surface, not be replaced by a contract pass.
    _make_test(
        pytester,
        contract="Contract(responds=True)",
        content="ok",
        extra='assert False, "body-level failure"',
    )
    result = pytester.runpytest("-p", "no:cacheprovider", f"--resilience-gateway-url={_GATEWAY}")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*body-level failure*"])
