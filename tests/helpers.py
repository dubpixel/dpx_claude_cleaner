"""
Shared test helpers.

src/dpx_claude_Cleaner.py and src/dpx_vscode_Cleaner.py both have
mixed-case filenames that aren't conventional importable module names, so
they're loaded via importlib rather than a normal `import` statement.
"""
import importlib.util
import json
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "src" / "dpx_claude_Cleaner.py"
_VSCODE_MODULE_PATH = Path(__file__).resolve().parent.parent / "src" / "dpx_vscode_Cleaner.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load_module(_MODULE_PATH, "dpx_claude_cleaner_under_test")
vc = _load_module(_VSCODE_MODULE_PATH, "dpx_vscode_cleaner_under_test")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write a list of dicts as newline-delimited JSON, like a real session file."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
