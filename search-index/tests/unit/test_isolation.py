"""The package only imports its own code, the standard library and its declared dependencies."""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "search_index"

# Distribution declared in pyproject.toml -> root modules it provides.
DECLARED_IMPORT_ROOTS = {
    "elasticsearch": {"elasticsearch"},
    "pydantic": {"pydantic"},
}


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def declared_distributions() -> set[str]:
    tomllib = pytest.importorskip("tomllib", reason="requires Python >= 3.11")
    project = tomllib.loads((SRC.parents[1] / "pyproject.toml").read_text())["project"]
    requirements = list(project["dependencies"])
    for extra_requirements in project.get("optional-dependencies", {}).values():
        requirements.extend(extra_requirements)
    names = set()
    for requirement in requirements:
        name = requirement
        for separator in "<>=!~[; ":
            name = name.split(separator)[0]
        names.add(name.lower())
    return names


def test_every_import_is_stdlib_the_package_itself_or_a_declared_dependency():
    allowed = {"search_index"} | set(sys.stdlib_module_names)
    declared = declared_distributions()
    for dist, roots in DECLARED_IMPORT_ROOTS.items():
        if dist in declared:
            allowed |= roots

    offenders = {
        str(path.relative_to(SRC)): sorted(imported_roots(path) - allowed)
        for path in SRC.rglob("*.py")
        if imported_roots(path) - allowed
    }

    assert offenders == {}


def test_the_declared_runtime_dependencies_are_the_ones_the_allowlist_knows():
    # If someone declares another dependency in pyproject.toml, this test forces an explicit
    # decision about which root modules it provides (and so which imports are allowed).
    unknown = declared_distributions() - set(DECLARED_IMPORT_ROOTS) - {
        "pytest",
        "pytest-cov",
        "ruff",
    }

    assert unknown == set()
