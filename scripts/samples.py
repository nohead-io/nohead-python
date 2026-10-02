"""Writes samples.json: for each API-key operation, a Python code sample that calls
it, from the calls in tests/calls.py (which the contract test checks against the
contract). The Nohead API repository puts them in the docs site's API reference
(x-codeSamples).

Run with `uv run python scripts/samples.py`.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import warnings
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nohead import NoheadWarning, Page  # noqa: E402
from nohead._generated.operations import OPERATIONS  # noqa: E402
from tests.calls import every_call, mock_reply  # noqa: E402
from tests.conftest import make_sync  # noqa: E402

HEADER = "from nohead import Nohead\n\nnohead = Nohead()\n\n"
# What a list's items are called in the loop, by operation.
ITEMS = {
    "record_revisions": "revision",
    "schema_changes": "change",
    "webhook_deliveries": "delivery",
    "audit_events": "event",
    "collections_search": "record",
    "projects_search": "record",
}
ROUTES = [
    (op, method, re.compile("^" + re.sub(r"\{\w+\}", "[^/]+", path) + "$"))
    for op, (method, path) in OPERATIONS.items()
]


def item_name(operation: str) -> str:
    for prefix, name in ITEMS.items():
        if operation.startswith(prefix):
            return name
    return operation.split("_")[0].removesuffix("s")


def call_sources() -> list[str]:
    """The source of each lambda in every_call, in order."""
    source = (ROOT / "tests/calls.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "every_call":
            returned = next(n for n in node.body if isinstance(n, ast.Return))
            assert isinstance(returned.value, ast.List)
            return [
                ast.get_source_segment(source, lam.body) or ""
                for lam in returned.value.elts
                if isinstance(lam, ast.Lambda)
            ]
    raise SystemExit("tests/calls.py has no every_call")


def first_operation(requests: list[httpx.Request]) -> str | None:
    for request in requests:
        for op, method, pattern in ROUTES:
            if (
                request.url.host == "api.test"
                and method == request.method
                and pattern.match(request.url.path)
            ):
                return op
    return None


def formatted(code: str) -> str:
    result = subprocess.run(
        ["ruff", "format", "--line-length", "88", "-"],
        input=code,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> None:
    sources = call_sources()
    samples: dict[str, str] = {}
    warnings.simplefilter("ignore", NoheadWarning)
    for index, source in enumerate(sources):
        nohead, recorder = make_sync([mock_reply])
        result = every_call(nohead)[index]()
        op = first_operation(recorder.calls)
        if op is None:
            raise SystemExit(f"No operation for {source}")
        expression = " ".join(source.split())  # ruff re-wraps it
        if isinstance(result, Page):
            name = item_name(op)
            statement = f"for {name} in {expression}:\n    print({name})\n"
        else:
            statement = f"result = {expression}\n"
        samples.setdefault(op, formatted(HEADER + statement))
    path = ROOT / "samples.json"
    path.write_text(json.dumps(dict(sorted(samples.items())), indent=2) + "\n")
    print(f"samples.json: {len(samples)} operations")


if __name__ == "__main__":
    main()
