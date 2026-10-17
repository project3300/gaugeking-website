"""Guardian gate: conservative checks on an untrusted Copilot patch.

This script never executes candidate code; GitHub branch protections still apply.
"""
import ast
import pathlib
import re
import subprocess
import sys

ALLOWED = {"natsoft_browser.py"}
MAX_LINES = 120

def main():
    base = sys.argv[1]
    head = sys.argv[2]
    names = subprocess.check_output(
        ["git", "diff", "--name-only", base, head], text=True
    ).splitlines()
    if not names or any(n not in ALLOWED for n in names):
        raise SystemExit("Guardian blocked: change outside allowlisted Natsoft browser file")
    stats = subprocess.check_output(
        ["git", "diff", "--numstat", base, head], text=True
    ).splitlines()
    total = sum(int(x) + int(y) for x, y, _ in (line.split("\t") for line in stats))
    if total > MAX_LINES:
        raise SystemExit(f"Guardian blocked: patch too large ({total} lines)")
    candidate = subprocess.check_output(
        ["git", "show", f"{head}:natsoft_browser.py"], text=True
    )
    original = subprocess.check_output(
        ["git", "show", f"{base}:natsoft_browser.py"], text=True
    )
    ast.parse(candidate)
    ast.parse(original)
    # Prevent malicious or accidental redirection to a non-Natsoft domain.
    for needle in ("ALLOWED_NATSOFT_HOSTS", "safe(url)", "discover_meetings", "discover_live_result"):
        if needle == "ALLOWED_NATSOFT_HOSTS":
            continue
        if needle not in candidate:
            raise SystemExit("Guardian blocked: required scraper entrypoint removed")
    # Cross-check security-critical URL restrictions remain unchanged.
    def get_func(source, name):
        tree = ast.parse(source)
        f = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
        return ast.dump(f, include_attributes=False) if f else None
    if get_func(candidate, "safe") != get_func(original, "safe"):
        raise SystemExit("Guardian blocked: Natsoft URL allowlist changed")
    if get_func(candidate, "fetch_natsoft_raw") != get_func(original, "fetch_natsoft_raw"):
        raise SystemExit("Guardian blocked: transport security guard changed")
    # Fail closed if a Copilot repair removes the authoritative Live-column path.
    # This is a structural guard, not proof that Natsoft's live format parses.
    live_function = next(
        (n for n in ast.parse(candidate).body
         if isinstance(n, ast.FunctionDef) and n.name == "discover_live_result"), None
    )
    if live_function is None:
        raise SystemExit("Guardian blocked: Live discovery function missing")
    live_source = ast.get_source_segment(candidate, live_function) or ""
    required_live_markers = ('[id$="c2"]', "live_cell.click", "no Live timing link")
    if not all(marker in live_source for marker in required_live_markers):
        raise SystemExit("Guardian blocked: authoritative Live column selection removed")
    if 'date_link.click' in live_source or '[id$="c3"]' in live_source:
        raise SystemExit("Guardian blocked: historical date/View fallback introduced")
    for blocked in ("subprocess", "os.system", "eval(", "exec(", "pickle", "base64.b64decode"):
        if blocked in candidate and blocked not in original:
            raise SystemExit("Guardian blocked: suspicious new execution primitive")
    print("Guardian static gate passed. Runtime verification still required.")

if __name__ == "__main__":
    main()
