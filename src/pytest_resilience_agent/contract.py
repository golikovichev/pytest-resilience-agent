"""Declarative resilience contracts.

A :class:`Contract` states what an agent owes the caller when a dependency
breaks under chaos. The plugin records every gateway call as a
:class:`CallRecord` and, at test teardown, checks the declared contract against
that ledger. A resilience test declares the invariant once on the marker
instead of repeating the same asserts in each test::

    @pytest.mark.resilience(
        scenarios=["llm_timeout"],
        contract=Contract(responds=True, latency_under=2.0),
    )
    def test_chat(ai_gateway, chaos):
        ai_gateway.chat([{"role": "user", "content": "hi"}])
        # no manual asserts: the contract is checked automatically
"""

from __future__ import annotations

from dataclasses import dataclass

from pytest_resilience_agent.gateway import ChatReply


@dataclass
class CallRecord:
    """One recorded gateway call, captured by the recording client.

    ``model_requested`` is the model the caller asked for; ``reply`` is the
    parsed reply (``None`` if the call raised); ``elapsed`` is wall-clock
    seconds around the call; ``error`` is the exception raised, if any.
    """

    model_requested: str
    reply: ChatReply | None
    elapsed: float | None
    error: Exception | None


@dataclass(frozen=True)
class Contract:
    """What the agent owes the caller when a dependency breaks.

    Every clause is opt-in: an unset clause is not checked. ``check`` returns a
    list of human-readable violation strings (empty when the contract holds).

    Clause quantifiers differ by intent. ``responds`` and ``names_fallback`` are
    existential (they hold when *some* call satisfies them), so ``responds=True``
    means "the agent answered under chaos", not "no call failed". Pair it with
    ``surfaces_clear_error`` to also forbid a silent empty reply.
    ``surfaces_clear_error`` and ``latency_under`` are universal: they hold only
    when *every* recorded call satisfies them.
    """

    responds: bool = False
    names_fallback: bool = False
    surfaces_clear_error: bool = False
    latency_under: float | None = None

    def check(self, calls: list[CallRecord]) -> list[str]:
        """Return the list of contract violations for ``calls`` (empty if none)."""
        if not calls:
            return ["contract declared but the gateway was never called"]
        violations: list[str] = []

        if self.responds and not any(c.reply and c.reply.content for c in calls):
            violations.append("responds: no call returned non-empty content under chaos")

        if self.names_fallback and not any(
            c.reply and c.reply.model and c.reply.model != c.model_requested for c in calls
        ):
            violations.append(
                "names_fallback: no reply came from a fallback model "
                "(reply.model never differed from the requested model)"
            )

        if self.surfaces_clear_error:
            silent = [
                c for c in calls if (c.reply is None or not c.reply.content) and c.error is None
            ]
            if silent:
                violations.append(
                    f"surfaces_clear_error: {len(silent)} call(s) returned empty "
                    "without raising a recognizable error"
                )

        if self.latency_under is not None:
            slow = [c for c in calls if c.elapsed is not None and c.elapsed > self.latency_under]
            if slow:
                worst = max(c.elapsed for c in slow if c.elapsed is not None)
                violations.append(
                    f"latency_under={self.latency_under}s: {len(slow)} call(s) exceeded, "
                    f"worst {worst:.3f}s"
                )

        return violations


__all__ = ["CallRecord", "Contract"]
