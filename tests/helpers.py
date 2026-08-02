"""
Shared test helpers.

src/dpx_claude_Cleaner.py has a mixed-case filename that isn't a
conventional importable module name, so it's loaded via importlib rather
than a normal `import` statement.
"""
import importlib.util
import json
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "src" / "dpx_claude_Cleaner.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("dpx_claude_cleaner_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load_module()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write a list of dicts as newline-delimited JSON, like a real session file."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
