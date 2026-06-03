# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for v0.2
- Multi-turn conversation chaos (failure injection mid-conversation)
- Semantic assertion hooks (composability with eval frameworks)
- LLM-driven scenario classifier behind the existing `pick_scenarios` interface
- Scenario composition primitives (e.g. `rate_limit` then `partial_outage`)

## [0.1.0] - 2026-05-27

Initial release. Built for the DevNetwork [AI + ML] Hackathon 2026, Lark and
TrueFoundry sponsor tracks.

### Added

**Plugin**
- `pytest_resilience_agent.plugin` registers the `resilience` pytest marker
  with strict-marker support
- `ai_gateway` fixture: returns an `AIGatewayClient` configured from
  `--resilience-gateway-url` CLI option or `TFY_GATEWAY_URL` env var
- `chaos` fixture: applies named scenarios from the marker for the test
  duration, with automatic cleanup
- `--resilience-record PATH` option writes a JSON timeline of every chaos
  event to disk at session finish
- `pytest_runtest_logreport` hook attaches a "chaos events" section to each
  test report so judges and engineers see what was injected next to the
  test outcome

**Chaos scenarios**
- `llm_timeout`: gateway sleeps past the request timeout
- `llm_5xx`: gateway returns 502 for the first N calls, then succeeds
- `rate_limit`: gateway returns 429 with `Retry-After`
- `mcp_error`: Lark MCP server raises a JSON-RPC error envelope
- `partial_outage`: first call 503, retry succeeds
- `cost_exceeded`: gateway returns 402 quota_exceeded
- `wrong_model_returned`: gateway silently routes to an unintended model
- `stream_stall`: gateway returns 200 with empty content (stream drop)
- `network_blip`: ConnectError on first N calls, recovery after

**Generator**
- `pytest_resilience_agent.generator.generate_test` writes a runnable
  pytest file for any failure text, with chaos scenarios picked from a
  deterministic regex rule set (ADR 0003)
- 9 regex rules cover the common failure-text patterns: 429, 502, 503,
  504, 402, connection errors, empty/stream, MCP, model mismatch

**CLI**
- `pytest-resilience-agent` console script with five subcommands:
  - `scenarios` lists the registered chaos scenarios
  - `discover` lists failing tests via Lark MCP
  - `generate` synthesises resilience tests from Lark failures
  - `run` executes the generated tests through pytest
  - `report` pushes resolution status back to Lark

**Demo entry points**
- `demo/run_demo.py`: drives the sample FastAPI agent through every chaos
  scenario with a Rich-table summary
- `demo/run_full_loop.py`: full end-to-end loop — spins up mock Lark
  server in a background thread, pulls failures, generates resilience
  tests, runs pytest, reports resolutions back to Lark
- `demo/mock_truefoundry.py`: in-process mock of the TrueFoundry AI
  Gateway with a Gemini → Claude → local fallback chain
- `demo/mock_lark.py`: in-process mock of the Lark MCP server with seeded
  failing-test data
- `demo/sample_agent/app.py`: sample FastAPI agent that summarises
  customer emails through the gateway with retry logic

**Tests and quality**
- 16 passing tests covering plugin registration, fixture wiring, every
  chaos scenario, the timeline export, and the report hook
- 5 example end-user tests in `demo/example_agent_tests/` showing the
  four patterns we expect adopters to copy
- Prose style scanner via `scripts/check_text_style.py` plus
  pre-commit configuration (ruff format + lint, trailing-whitespace,
  YAML/TOML/large-file checks)
- 3 ADRs in `docs/adr/`:
  - 0001: resilience-first direction, not eval-first
  - 0002: respx as the chaos injection layer
  - 0003: rule-based scenario picker for v0.1, LLM-driven option for v0.2

**Observability**
- OpenTelemetry spans on every chaos scenario apply / revert, ready for
  OTLP export to Cloud Trace or any compatible backend

### Known limitations

- Semantic-level paraphrased failures are out of scope (use phoenix2pytest
  or DeepEval for those)
- Multi-turn conversation chaos is on the v0.2 roadmap
- Distributed-system chaos (network partitions across services) is out of
  scope for v0.1; the HTTP-layer approach covers gateway, model, MCP, and
  rate limiter in one mechanism

[Unreleased]: https://github.com/golikovichev/pytest-resilience-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/golikovichev/pytest-resilience-agent/releases/tag/v0.1.0
