# ADR 0002: respx as the chaos injection layer

## Status

Accepted.

## Context

Chaos scenarios need to intercept outbound HTTP calls from the agent
under test and return controlled failures: 502, 429 with Retry-After,
empty body, connection error, slow response, JSON-RPC error envelope.

Three candidate mechanisms:

1. Monkey-patch the AI Gateway client class. Simple but only catches code
   that uses our client; users on the OpenAI SDK or raw httpx escape.
2. WSGI / ASGI middleware on a local mock server. Realistic but heavy:
   each test spins up a process, real socket connections, real ports.
3. Patch httpx at the transport layer via `respx`.

## Decision

Use `respx`. It mounts a transport that intercepts every httpx call
the test process makes, including calls from third-party libraries
that use httpx under the hood (OpenAI SDK, anthropic SDK, etc).

## Consequences

- Scenarios are tiny: each is a small class with `apply` and `revert`
  methods that install one respx route.
- The plugin works for any agent that talks to LLM infrastructure over
  httpx. Agents on aiohttp / requests need extra work but those are
  documented as next-iteration follow-ups.
- We do not need to spin up real processes for the basic test path,
  which keeps the suite fast (~10s for the full chaos scenario set on
  a laptop).

## Alternatives considered

- **`pytest-httpx`.** Similar mechanism but more verbose API for our
  needs; respx routes are slightly easier to compose.
- **`unittest.mock.patch` on httpx.Client.send.** Works for tightly-
  controlled tests but does not cover the AsyncClient path or the
  internal transport layer that some SDKs use directly.
