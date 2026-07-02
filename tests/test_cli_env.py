"""CLI environment-variable resolution for the Lark MCP URL.

The plugin layer resolves the Lark URL from the canonical ``RESILIENCE_LARK_URL``
with ``LARK_MCP_URL`` kept as a legacy alias. The CLI subcommands must follow the
same contract the README and CHANGELOG advertise. Otherwise ``export
RESILIENCE_LARK_URL=...`` is silently ignored and every CLI call falls back to
the default URL.
"""

from pytest_resilience_agent.cli import _DEFAULT_LARK_URL, _lark_url, build_parser


def _args(argv):
    return build_parser().parse_args(argv)


def test_canonical_env_is_honored(monkeypatch):
    monkeypatch.delenv("LARK_MCP_URL", raising=False)
    monkeypatch.setenv("RESILIENCE_LARK_URL", "https://canonical.example")
    assert _lark_url(_args(["discover"])) == "https://canonical.example"


def test_legacy_alias_still_works(monkeypatch):
    monkeypatch.delenv("RESILIENCE_LARK_URL", raising=False)
    monkeypatch.setenv("LARK_MCP_URL", "https://legacy.example")
    assert _lark_url(_args(["discover"])) == "https://legacy.example"


def test_canonical_takes_precedence_over_alias(monkeypatch):
    monkeypatch.setenv("RESILIENCE_LARK_URL", "https://canonical.example")
    monkeypatch.setenv("LARK_MCP_URL", "https://legacy.example")
    assert _lark_url(_args(["discover"])) == "https://canonical.example"


def test_explicit_flag_beats_env(monkeypatch):
    monkeypatch.setenv("RESILIENCE_LARK_URL", "https://canonical.example")
    monkeypatch.setenv("LARK_MCP_URL", "https://legacy.example")
    resolved = _lark_url(_args(["--lark-url", "https://flag.example", "discover"]))
    assert resolved == "https://flag.example"


def test_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("RESILIENCE_LARK_URL", raising=False)
    monkeypatch.delenv("LARK_MCP_URL", raising=False)
    assert _lark_url(_args(["discover"])) == _DEFAULT_LARK_URL
