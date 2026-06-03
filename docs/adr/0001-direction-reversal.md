# ADR 0001: Resilience-first direction, not eval-first

## Status

Accepted.

## Context

The LLM testing ecosystem in 2026 is dominated by eval frameworks (DeepEval,
Opik, pytest-evals, Langfuse, Phoenix evals). They all share a direction:
the engineer writes evals against a known specification, runs them, and
gets a score. This works well for correctness questions answered on a
clean path: "does this prompt return JSON?", "does the answer cite the
right facts?".

Production failure modes the team actually pays for are different:

- the primary model browns out at 02:14 on a Saturday;
- an MCP server starts returning tool errors for one specific tool;
- a rate limit kicks in halfway through a long completion;
- the gateway silently downgrades to a smaller fallback model.

None of these show up on a clean-path eval suite.

## Decision

We design the plugin around a different axis: **resilience under chaos
injection**, not correctness under a known spec. Tests declare what
faults they want injected via a marker, the plugin installs the faults
at the HTTP layer, and the assertion is on the user-visible contract
(must respond, must surface a clear error, must log the fallback path).

Tests that score model output quality belong in DeepEval / pytest-evals.
Tests that prove the agent survives infrastructure breakage belong here.
The two suites compose without overlap.

## Consequences

- The default chaos library lives at the HTTP layer (`respx`), so the
  same scenario runs whether the agent uses OpenAI SDK, raw httpx, or a
  TrueFoundry-style gateway.
- The plugin has a small surface area: one marker, two fixtures, a
  scenario registry. Easy to learn for end users already on pytest.
- Combining with eval frameworks is a documentation problem, not a code
  one. Each suite owns a different axis.

## Alternatives considered

- **Build on top of an existing eval framework.** Rejected: the eval
  frameworks treat each test as "one run, one score". Resilience tests
  need explicit fault injection and assertions on retry / fallback
  behaviour, which does not fit cleanly into "run and score".
- **Process-level chaos (kill processes, drop packets).** Rejected for
  v0.1: too platform-specific. The HTTP-layer approach covers gateway,
  model, MCP, and rate limiter in one mechanism.
