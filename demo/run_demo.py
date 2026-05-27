"""End-to-end resilience demo.

Drives the sample agent through every chaos scenario and prints a rich
table showing what was injected, what the agent did, and whether the
resilience contract held.

Run::

    python demo/run_demo.py

No external accounts are required: the chaos controller mocks the gateway
URL out the box, and we point the sample agent at the same URL. The
TrueFoundry / Lark integration story is told in the README and demo
narration; this script proves the test-layer mechanics.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException
from rich.console import Console
from rich.table import Table

from demo.sample_agent.app import summarise_email
from pytest_resilience_agent.chaos import ChaosController


@dataclass
class CaseResult:
    """Outcome record for one demo case."""

    scenario: str
    expected: str
    observed: str
    attempts: int
    fallback_used: bool
    passed: bool


def _case_llm_5xx() -> CaseResult:
    controller = ChaosController(
        scenarios=["llm_5xx"],
        target_gateway_url="https://gateway.local/v1/chat/completions",
    )
    controller.enter()
    try:
        reply = summarise_email("Refund my order #423 please.", timeout=2.0)
        passed = reply.fallback_used and reply.content == "recovered"
        return CaseResult(
            scenario="llm_5xx",
            expected="retry recovers, content non-empty, fallback_used=True",
            observed=f"content={reply.content!r}",
            attempts=reply.attempts,
            fallback_used=reply.fallback_used,
            passed=passed,
        )
    finally:
        controller.exit()


def _case_rate_limit() -> CaseResult:
    controller = ChaosController(scenarios=["rate_limit"])
    controller.enter()
    try:
        reply = summarise_email("Cancel my subscription.", timeout=2.0)
        # 429 should be retried; success on second attempt
        passed = reply.attempts >= 2 and "choices" not in reply.content.lower()
        return CaseResult(
            scenario="rate_limit",
            expected="retry on Retry-After hint, eventual 200",
            observed=f"content={reply.content!r}",
            attempts=reply.attempts,
            fallback_used=reply.fallback_used,
            passed=passed,
        )
    finally:
        controller.exit()


def _case_partial_outage() -> CaseResult:
    controller = ChaosController(scenarios=["partial_outage"])
    controller.enter()
    try:
        reply = summarise_email("Where is my package?", timeout=2.0)
        passed = "back online" in reply.content
        return CaseResult(
            scenario="partial_outage",
            expected="retry succeeds, content includes recovery marker",
            observed=f"content={reply.content!r}",
            attempts=reply.attempts,
            fallback_used=reply.fallback_used,
            passed=passed,
        )
    finally:
        controller.exit()


def _case_persistent_5xx() -> CaseResult:
    """Three consecutive 5xx - agent must surface clean 503 not crash."""
    import respx

    from pytest_resilience_agent.scenarios import LLM5xx

    controller = ChaosController(scenarios=[])
    controller._mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
    controller._mock.start()
    scenario = LLM5xx(controller._mock, controller.target_gateway_url, fail_first_n=10)
    scenario.apply()
    try:
        try:
            summarise_email("Test persistent outage.", timeout=2.0)
            return CaseResult(
                scenario="persistent_5xx",
                expected="surface HTTPException 503 after retries exhausted",
                observed="no exception raised (BAD)",
                attempts=0,
                fallback_used=False,
                passed=False,
            )
        except HTTPException as exc:
            passed = exc.status_code == 503
            return CaseResult(
                scenario="persistent_5xx",
                expected="HTTPException 503 surfaced cleanly",
                observed=f"HTTPException({exc.status_code}, {exc.detail!r})",
                attempts=0,
                fallback_used=False,
                passed=passed,
            )
    finally:
        scenario.revert()
        controller._mock.stop()


CASES: list[tuple[str, Callable[[], CaseResult]]] = [
    ("Transient 5xx, single retry recovers", _case_llm_5xx),
    ("429 Rate limit with Retry-After", _case_rate_limit),
    ("Partial outage (503 then 200)", _case_partial_outage),
    ("Persistent 5xx exhausts retries", _case_persistent_5xx),
]


def main() -> int:
    console = Console()
    console.rule("[bold orange3]pytest-resilience-agent demo[/]")
    console.print(
        "Running the sample FastAPI agent against each chaos scenario."
        "\nEvery scenario is injected via respx at the HTTP layer."
        "\nThe agent has retry logic; we assert on the user-visible contract."
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Case", style="cyan", no_wrap=False)
    table.add_column("Expected behaviour", style="white")
    table.add_column("Observed", style="white")
    table.add_column("Attempts", justify="right")
    table.add_column("Fallback?", justify="center")
    table.add_column("Result", justify="center")

    failures = 0
    for label, case in CASES:
        result = case()
        verdict = "[bold green]PASS[/]" if result.passed else "[bold red]FAIL[/]"
        if not result.passed:
            failures += 1
        table.add_row(
            label,
            result.expected,
            result.observed,
            str(result.attempts),
            "yes" if result.fallback_used else "no",
            verdict,
        )

    console.print(table)
    console.rule()
    if failures:
        console.print(f"[bold red]{failures} case(s) failed.[/]")
        return 1
    console.print(
        "[bold green]All cases met the resilience contract.[/] "
        "The agent retried, recovered, or surfaced a clean error on every fault."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
