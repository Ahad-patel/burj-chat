"""Executable enforcement of the Clean Architecture dependency rule.

The whole design rests on one claim: the domain layer depends on nothing.
That claim is what makes the guardrails unit-testable without a network call and
the LLM provider swappable by changing a single environment variable.

A rule that lives only in a README erodes. These tests make it fail the build.

Python note: `ast` parses source into a syntax tree *without importing it*, so
this inspects the code statically. Importing the modules to inspect them would
defeat the purpose — an import would execute the very dependencies we forbid.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
DOMAIN_ROOT = APP_ROOT / "domain"

# Anything the domain layer must never reach for. Matched against the root of
# the dotted module path, so "fastapi" also catches "fastapi.responses".
FORBIDDEN_IN_DOMAIN = frozenset(
    {
        # Web framework
        "fastapi",
        "starlette",
        "uvicorn",
        # Validation framework — domain uses stdlib dataclasses instead, so that
        # "no framework dependencies" is a fact rather than a slogan.
        "pydantic",
        "pydantic_settings",
        # LLM SDKs — the entire point of the LLMClient port
        "anthropic",
        "google",
        "openai",
        # I/O and transport
        "httpx",
        "requests",
        "aiohttp",
        "sqlalchemy",
        "redis",
        # Our own outer layers
        "app.api",
        "app.core",
        "app.infrastructure",
        "app.schemas",
        "app.services",
    }
)

# Only these modules may import a vendor SDK. If this set grows, provider
# swapping has stopped being free and the design has drifted.
SDK_IMPORT_ALLOWLIST = frozenset(
    {
        "app.infrastructure.llm.gemini_client",
        "app.infrastructure.llm.anthropic_client",
    }
)
VENDOR_SDKS = frozenset({"anthropic", "google", "openai"})


def _python_files(root: Path) -> Iterator[Path]:
    """Yield every .py file under `root`, skipping caches."""
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def _imported_modules(path: Path) -> set[str]:
    """Return every module name imported by `path`, fully dotted.

    Handles both `import x.y` and `from x.y import z`. Relative imports are
    skipped here because ruff's TID rule already bans them project-wide.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)

    return modules


def _violates(module: str, forbidden: frozenset[str]) -> bool:
    """True if `module` is, or lives beneath, any forbidden prefix."""
    return any(module == bad or module.startswith(f"{bad}.") for bad in forbidden)


def _module_name(path: Path) -> str:
    """Convert backend/app/domain/ports/llm_client.py -> app.domain.ports.llm_client."""
    relative = path.relative_to(APP_ROOT.parent).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts)


def _domain_files() -> list[Path]:
    return list(_python_files(DOMAIN_ROOT))


@pytest.mark.parametrize("path", _domain_files(), ids=_module_name)
def test_domain_imports_only_stdlib(path: Path) -> None:
    """The domain layer must not import any framework, SDK, or outer layer."""
    offenders = sorted(
        module for module in _imported_modules(path) if _violates(module, FORBIDDEN_IN_DOMAIN)
    )

    assert not offenders, (
        f"{_module_name(path)} imports {offenders}.\n"
        "The domain layer must depend on nothing but the standard library and "
        "other domain modules. If you need this capability, declare a port in "
        "app/domain/ports/ and implement it in app/infrastructure/."
    )


def test_vendor_sdks_are_confined_to_their_adapters() -> None:
    """Only the two LLM adapters may import a vendor SDK.

    This is what backs the promise that switching LLM_PROVIDER requires no
    changes anywhere else: if no other module can even see the SDK, no other
    module can be coupled to it.
    """
    leaks: dict[str, list[str]] = {}

    for path in _python_files(APP_ROOT):
        module = _module_name(path)
        if module in SDK_IMPORT_ALLOWLIST:
            continue

        imported = sorted(m for m in _imported_modules(path) if _violates(m, VENDOR_SDKS))
        if imported:
            leaks[module] = imported

    assert not leaks, (
        f"Vendor SDK imports found outside the adapter layer: {leaks}.\n"
        "Route this through the LLMClient port instead."
    )


def test_domain_layer_exists() -> None:
    """Guard against the boundary tests silently passing on an empty tree.

    Without this, deleting the domain directory would make every test above
    vacuously pass — a green build that proves nothing.
    """
    assert _domain_files(), f"No Python files found under {DOMAIN_ROOT}"
