"""PR C repo invariant: no hardcoded internal endpoint literals outside
services/runtime_config.py.

Internal service endpoints (Ollama :11434, Kronos :8100, SearxNG :8080) and
machine-specific addresses (Tailscale 100.101.*, LAN 192.168.*) must resolve
through services/runtime_config.py — divergent inline defaults caused real
laptop-vs-server incidents (four different Ollama defaults as of 2026-06-10).

Modeled on test_root_py_inventory_classified: scans git-tracked .py files.
"""
import re
import subprocess
from pathlib import Path

_ENDPOINT_LITERAL = re.compile(r":11434|:8100|:8080|100\.101\.|192\.168\.")

# Files allowed to carry endpoint literals:
_ALLOWED = {
    "services/runtime_config.py",  # the single source of truth
    "post_run.py",                 # deploy tooling — out of PR C scope (D2)
    "compare_llm_models.py",       # laptop-only dev script
}


def _is_exempt(name: str) -> bool:
    if name in _ALLOWED:
        return True
    if name.startswith("tests/"):
        return True
    if Path(name).name.startswith("_test_"):  # root-level dev scratch scripts
        return True
    return False


def test_no_hardcoded_endpoint_literals_outside_runtime_config():
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True, text=True, cwd=str(root),
    )
    offenders = []
    for name in result.stdout.splitlines():
        if not name.endswith(".py") or _is_exempt(name):
            continue
        path = root / name
        if not path.exists():  # deleted-but-staged edge case
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _ENDPOINT_LITERAL.search(line):
                offenders.append(f"  {name}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        "Hardcoded internal endpoint literal(s) found outside "
        "services/runtime_config.py — add an accessor there instead:\n"
        + "\n".join(offenders)
    )
