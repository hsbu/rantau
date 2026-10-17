import pytest

from scripts.check_repo_hygiene import inspect_path


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        "backend/__pycache__/a.pyc",
        "node_modules/x/a.js",
        "frontend/.next/server.js",
        "frontend/tsconfig.tsbuildinfo",
        "db.sqlite3",
    ],
)
def test_artifacts_are_rejected(path):
    assert inspect_path(path, "")


@pytest.mark.parametrize("path", ["uv.lock", "frontend/package-lock.json", "migrations/001.sql"])
def test_reproducible_sources_are_allowed(path):
    assert inspect_path(path, "") == []


def test_secrets_are_detected_without_echoing_values():
    value = "ghp_" + "a" * 40
    findings = inspect_path("config.py", value)
    assert findings
    assert value not in str(findings)
    assert not inspect_path(".env.example", "OPENAI_API_KEY=\n")
    assert not inspect_path(".env.example", "OPENROUTER_API_KEY=\n")
    assert inspect_path(".env.example", "OPENROUTER_API_KEY=synthetic-nonempty-key\n")
