"""Command-line tool entry point.

Subcommands:

- ``discover``     list failing tests via Lark MCP (or local mock)
- ``generate``     synthesize resilience test files from those failures
- ``run``          execute the generated tests via pytest
- ``report``       push resolution status back to Lark
- ``scenarios``    print the built-in chaos scenario registry

Install with ``pip install -e .`` and call ``pytest-resilience-agent``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from pytest_resilience_agent.generator import generate_test
from pytest_resilience_agent.lark_mcp import LarkMCPClient
from pytest_resilience_agent.scenarios import registered_scenarios

_DEFAULT_LARK_URL = "http://localhost:8801"
_DEFAULT_PROJECT = "demo"
_DEFAULT_GENERATED_DIR = Path("generated_resilience_tests")


def _console() -> Console:
    """Return a Console that handles UTF-8 cleanly on Windows cp1252 terminals."""
    return Console(force_terminal=True)


def _lark_url(args: argparse.Namespace) -> str:
    return args.lark_url or os.environ.get("LARK_MCP_URL") or _DEFAULT_LARK_URL


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


def cmd_discover(args: argparse.Namespace) -> int:
    """List failing tests from the Lark MCP server."""
    console = _console()
    client = LarkMCPClient(base_url=_lark_url(args))
    try:
        tests = client.list_failing_tests(args.project)
    finally:
        client.close()
    table = Table(title=f"Failing tests in {args.project!r}")
    table.add_column("Name", style="cyan")
    table.add_column("Last failure", style="red")
    table.add_column("Path", style="dim")
    for t in tests:
        table.add_row(t.name, t.last_failure or "", t.path)
    console.print(table)
    if not tests:
        console.print("[yellow]No failing tests reported.[/]")
    return 0


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    """Pull failing tests from Lark and write resilience test files."""
    console = _console()
    client = LarkMCPClient(base_url=_lark_url(args))
    try:
        tests = client.list_failing_tests(args.project)
    finally:
        client.close()
    if not tests:
        console.print("[yellow]No failing tests, nothing to generate.[/]")
        return 0
    out_dir = Path(args.out)
    table = Table(title=f"Generated {len(tests)} resilience test(s)")
    table.add_column("Test name", style="cyan")
    table.add_column("Scenarios", style="green")
    table.add_column("File", style="dim")
    for t in tests:
        generated = generate_test(t.name, t.last_failure or "", out_dir)
        table.add_row(t.name, ", ".join(generated.scenarios), str(generated.file_path))
    console.print(table)
    console.print(f"[green]Wrote {len(tests)} file(s) under {out_dir}[/]")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Run pytest against the generated tests directory."""
    target = Path(args.path)
    if not target.exists():
        _console().print(f"[red]No such path: {target}[/]")
        return 2
    cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "-v", str(target)]
    if args.record:
        cmd.append(f"--resilience-record={args.record}")
    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    """Push a resolution back to Lark."""
    client = LarkMCPClient(base_url=_lark_url(args))
    try:
        client.report_resolved(
            project=args.project,
            test_name=args.test_name,
            pytest_path=args.pytest_path,
        )
    finally:
        client.close()
    _console().print(f"[green]Reported resolution for {args.test_name}[/]")
    return 0


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------


def cmd_scenarios(args: argparse.Namespace) -> int:
    """Print the registered chaos scenario names."""
    console = _console()
    table = Table(title="Registered chaos scenarios")
    table.add_column("Name", style="cyan")
    for name in registered_scenarios():
        table.add_row(name)
    console.print(table)
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse tree."""
    parser = argparse.ArgumentParser(prog="pytest-resilience-agent")
    parser.add_argument(
        "--lark-url",
        default=None,
        help="Lark MCP base URL (env LARK_MCP_URL, default http://localhost:8801)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_disc = sub.add_parser("discover", help="list failing tests via Lark")
    p_disc.add_argument("--project", default=_DEFAULT_PROJECT)
    p_disc.set_defaults(func=cmd_discover)

    p_gen = sub.add_parser("generate", help="generate resilience tests from Lark failures")
    p_gen.add_argument("--project", default=_DEFAULT_PROJECT)
    p_gen.add_argument("--out", default=str(_DEFAULT_GENERATED_DIR))
    p_gen.set_defaults(func=cmd_generate)

    p_run = sub.add_parser("run", help="pytest the generated tests")
    p_run.add_argument("--path", default=str(_DEFAULT_GENERATED_DIR))
    p_run.add_argument("--record", default=None, help="JSON timeline path")
    p_run.set_defaults(func=cmd_run)

    p_rep = sub.add_parser("report", help="push a resolution back to Lark")
    p_rep.add_argument("--project", default=_DEFAULT_PROJECT)
    p_rep.add_argument("--test-name", required=True)
    p_rep.add_argument("--pytest-path", required=True)
    p_rep.set_defaults(func=cmd_report)

    p_sce = sub.add_parser("scenarios", help="list registered chaos scenarios")
    p_sce.set_defaults(func=cmd_scenarios)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
