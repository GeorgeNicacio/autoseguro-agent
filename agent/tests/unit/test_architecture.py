"""Regra de dependência do hexágono: o domínio não conhece infraestrutura (SOLID · D)."""

import ast
from pathlib import Path

import pytest

DOMAIN = Path(__file__).parents[2] / "src" / "autoseguro_agent" / "domain"
FORBIDDEN = ("httpx", "langgraph", "anthropic", "sqlite3", "fastapi", "structlog", "tenacity")
FORBIDDEN_INTERNAL = ("autoseguro_agent.adapters", "autoseguro_agent.graph", "autoseguro_agent.api")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda p: p.name)
def test_domain_has_no_infra_imports(path: Path) -> None:
    bad = {
        n
        for n in _imports(path)
        if n.split(".")[0] in FORBIDDEN or n.startswith(FORBIDDEN_INTERNAL)
    }
    assert not bad, f"{path.name} importa infraestrutura: {bad}"
