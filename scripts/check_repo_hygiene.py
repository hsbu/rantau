"""Inspect Git's index without printing file contents or credential values."""

import re
import subprocess
from pathlib import PurePosixPath

FORBIDDEN = frozenset(
    {
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".next",
        ".turbo",
        "out",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        ".generated",
        ".idea",
        ".vscode",
    }
)
SUFFIXES = (".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db", ".tsbuildinfo")
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{32,}"
)


def inspect_path(path: str, content: str) -> list[str]:
    parts = PurePosixPath(path).parts
    name = parts[-1]
    findings: list[str] = []
    if set(parts) & FORBIDDEN or name.endswith(SUFFIXES) or name == ".coverage":
        findings.append("local or generated artifact")
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        findings.append("local environment file")
    if name == "generated.d.ts" or name == "next-env.d.ts":
        findings.append("generated type output")
    if SECRET.search(content):
        findings.append("possible credential; inspect locally and rotate if real")
    if name == ".env.example":
        for line in content.splitlines():
            if line.startswith("OPENAI_API_KEY="):
                value = line.partition("=")[2].strip().strip("\"'")
                if value and value != "replace-with-local-key":
                    findings.append("API key template must be blank or a placeholder")
    return findings


def main() -> int:
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    failures: list[str] = []
    for path in filter(None, paths):
        raw = subprocess.check_output(["git", "show", f":{path}"])
        for reason in inspect_path(path, raw.decode("utf-8", errors="replace")):
            failures.append(f"{path}: {reason}")
    for failure in failures:
        print(failure)
    if not failures:
        print("Repository hygiene: passed (Git index)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
