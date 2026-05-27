"""Full end-to-end demo: Lark mock → generator → pytest run → Lark resolution.

Walks the entire product story in one script, with zero external accounts:

1. Spin up the mock Lark MCP server (ASGI in-process) and seed three
   failing tests in the «demo» project.
2. Pull the failures via LarkMCPClient pointed at the in-process server.
3. Generate a resilience pytest file for each failure (chosen scenarios
   matched to the failure text).
4. Run pytest against the generated directory; collect outcomes.
5. For each test that passed under chaos, report the resolution back
   to the mock Lark so the failure UI would show the new pytest path.
6. Print a rich summary table.

This is the «one command and you see the whole product» entry point.

Run::

    python -X utf8 -m demo.run_full_loop
"""

from __future__ import annotations

import socket
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from rich.console import Console
from rich.table import Table

from demo.mock_lark import app as mock_lark_app
from pytest_resilience_agent.generator import generate_test
from pytest_resilience_agent.lark_mcp import LarkMCPClient


def _free_port() -> int:
    """Pick a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def lark_mock_server() -> Iterator[str]:
    """Run the mock Lark MCP FastAPI app in a background thread.

    Yields the base URL the caller can POST/GET against.
    Shuts the server down on exit.
    """
    port = _free_port()
    config = uvicorn.Config(
        mock_lark_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for the server to start accepting connections
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)


def _run_pytest_collect_only(test_dir: Path) -> dict[str, bool]:
    """Run pytest against the generated directory; return name → passed map.

    Uses subprocess to isolate the nested pytest run from this script's
    interpreter state, which is the cleanest way to get reliable outcomes.
    """
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "pytest",
            str(test_dir),
            "-v",
            "--no-header",
            "--override-ini",
            "testpaths=",
            "--rootdir",
            str(test_dir),
        ],
        capture_output=True,
        text=True,
    )
    outcomes: dict[str, bool] = {}
    # Combine stdout + stderr and parse line-by-line for pytest verdicts.
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    for line in combined.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        # pytest -v lines look like
        #   tmp/.../test_x.py::test_x PASSED [100%]
        # Some pytest versions add a leading status char.
        parts = line.split()
        # Find the token containing "::"; that's the test id.
        test_id = next((p for p in parts if "::" in p), None)
        if not test_id:
            continue
        if "PASSED" in line:
            outcomes[test_id] = True
        elif "FAILED" in line or "ERROR" in line:
            outcomes[test_id] = False
    # If we still got nothing, surface a bit of context for the demo viewer.
    if not outcomes:
        print("--- pytest stdout ---", file=sys.stderr)
        print(combined[-1500:], file=sys.stderr)
    return outcomes


def main() -> int:
    console = Console(force_terminal=True)
    console.rule("[bold orange3]pytest-resilience-agent - full loop demo[/]")

    with tempfile.TemporaryDirectory(prefix="resagent_") as tmp, lark_mock_server() as lark_url:
        gen_dir = Path(tmp) / "generated"
        console.print(f"[dim]Mock Lark server up at {lark_url}[/]")

        # 1. Pull failures from mock Lark
        lark = LarkMCPClient(base_url=lark_url)
        failures = lark.list_failing_tests("demo")
        lark.close()
        console.print(f"[cyan]Lark reports {len(failures)} failing test(s).[/]")

        # 2. Generate resilience tests
        generated = []
        for failure in failures:
            artefact = generate_test(failure.name, failure.last_failure or "", gen_dir)
            generated.append((failure, artefact))
            console.print(
                f"  → generated [green]{artefact.file_path.name}[/] "
                f"with scenarios {artefact.scenarios}"
            )

        # 3. Run pytest against generated tests
        console.print("[cyan]Running generated tests...[/]")
        outcomes = _run_pytest_collect_only(gen_dir)

        # 4. Report resolutions for passing tests
        resolutions = 0
        lark = LarkMCPClient(base_url=lark_url)
        try:
            for failure, artefact in generated:
                # Match the pytest nodeid prefix
                passed = any(
                    artefact.file_path.name in test_id and outcomes[test_id] for test_id in outcomes
                )
                if passed:
                    lark.report_resolved(
                        project="demo",
                        test_name=failure.name,
                        pytest_path=str(artefact.file_path),
                    )
                    resolutions += 1
        finally:
            lark.close()

        # 5. Summary
        table = Table(title="Round-trip summary")
        table.add_column("Original failure", style="cyan")
        table.add_column("Scenarios applied", style="green")
        table.add_column("Generated test", style="dim")
        table.add_column("Result", justify="center")
        passes = 0
        for failure, artefact in generated:
            passed = any(
                artefact.file_path.name in test_id and outcomes[test_id] for test_id in outcomes
            )
            if passed:
                passes += 1
            verdict = "[bold green]PASS[/]" if passed else "[bold red]FAIL[/]"
            table.add_row(
                failure.name,
                ", ".join(artefact.scenarios),
                artefact.file_path.name,
                verdict,
            )
        console.print(table)
        console.print(f"[bold]Resolutions reported to Lark: {resolutions} / {len(generated)}[/]")

    return 0 if passes == len(generated) else 1


if __name__ == "__main__":
    sys.exit(main())
