# Contributing

Thanks for your interest in pytest-resilience-agent. This is a small alpha project shipped during the DevNetwork AI+ML Hackathon, so the contribution flow is light.

## Reporting a bug

Open an issue with:

- What you ran (pytest invocation, marker selection, Python version)
- What you expected the resilience scenario to do
- What happened instead (timeline output on failure helps)
- A minimal scenario or fixture snippet that reproduces it (strip any real API keys or gateway tokens first)

## Suggesting a feature

Open an issue first so we can talk through the use case before you write code. The project scope is intentionally narrow: pytest-driven resilience testing for LLM applications via Lark MCP plus TrueFoundry AI Gateway, with rule-based assertions and explicit chaos markers. Feature requests that pull it elsewhere will get a polite redirect.

## Submitting a pull request

1. Fork the repo and create a branch from `main`.
2. Make your changes. Keep the diff focused on one thing.
3. Add or update tests in `tests/`. The CI runs `pytest -v` on Python 3.11, 3.12, and 3.13.
4. Run the tests locally before pushing:
   ```bash
   pip install -e ".[dev]"
   pytest tests -m "not integration"
   ```
5. New scenarios, fixtures, or markers need at least one happy-path test and one chaos-injection test that exercises the timeline output.
6. Open the PR with a short description of what changed and why.

## Code style

- Python 3.11+. Type hints on public functions.
- Function and variable names in English, snake_case (e.g., `inject_timeout`, `assert_recovery`).
- One responsibility per function. If a function grows past 30-40 lines, split it.
- Ruff handles lint and formatting. Run `ruff check . && ruff format .` before opening a PR.

## Security

If you find something that could leak gateway tokens, MCP server credentials, or PII from a real LLM transcript, please report privately. See `SECURITY.md` for the disclosure channel.
