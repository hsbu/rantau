"""Static guards for repository-wide financial rules."""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
FINANCIAL_PACKAGES = ("finance", "university", "demo")
BACKEND_ONLY_ACTIONS = ("post_university_ledger", "approve_reconciliation", "reset_demo_fixture")
# Dev A's explicit offline harness is the one documented application file that uses fixtures.
OFFLINE_HARNESS = BACKEND / "agent" / "demo.py"


def python_files(*packages):
    return [path for package in packages for path in (BACKEND / package).rglob("*.py")]


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            yield node.annotation
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from (arg.annotation for arg in node.args.args if arg.annotation)
            if node.returns:
                yield node.returns


def uses_float_for_values(tree):
    calls = (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "float"
    )
    literals = (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    )
    hints = (
        name
        for annotation in annotations(tree)
        for name in ast.walk(annotation)
        if isinstance(name, ast.Name) and name.id == "float"
    )
    return [*calls, *literals, *hints]


def test_no_binary_float_value_touches_money_code():
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in python_files(*FINANCIAL_PACKAGES)
        for node in uses_float_for_values(parse(path))
    ]
    assert not offenders


def test_backend_only_actions_are_unreachable_from_the_agent_and_public_routers():
    exposed = [
        path.name
        for path in python_files("agent", "kb")
        if any(action in path.read_text(encoding="utf-8") for action in BACKEND_ONLY_ACTIONS)
    ]
    assert not exposed


def test_application_code_never_imports_test_fakes():
    offenders = [
        path
        for path in BACKEND.rglob("*.py")
        if path != OFFLINE_HARNESS and imports_tests(parse(path))
    ]
    assert not offenders


def imports_tests(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tests":
            return True
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "tests" for a in node.names
        ):
            return True
    return False
