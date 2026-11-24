"""Every package an image's Python imports is one its Dockerfile installs.

The dev environment holds every dependency group at once, so an import of a package only another
group brings (numpy, through the dashboard's) passes every other test and stops the image at start.
"""

import ast
import re
import subprocess
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROVIDERS_HERE = packages_distributions()

# Dockerfile: (the source its image runs, the uv project it installs, the flags it installs it with)
IMAGES = {
    "yapit/gateway/Dockerfile": ("yapit/gateway", ".", ["--no-dev"]),
    "yapit/workers/kokoro/Dockerfile.cpu": ("yapit/workers/kokoro", "yapit/workers/kokoro/cpu", []),
    "yapit/workers/kokoro/Dockerfile.gpu": ("yapit/workers/kokoro", "yapit/workers/kokoro/gpu", []),
    "yapit/workers/yolo/Dockerfile.cpu": ("yapit/workers/yolo", "yapit/workers/yolo/cpu", []),
    "yapit/workers/yolo/Dockerfile.gpu": ("yapit/workers/yolo", "yapit/workers/yolo/gpu", []),
}


def test_every_image_built_from_the_python_is_checked():
    assert {str(p.relative_to(REPO)) for p in (REPO / "yapit").rglob("Dockerfile*")} == set(IMAGES)


@pytest.mark.parametrize("image", IMAGES)
def test_image_installs_every_package_its_code_imports(image):
    source, project, flags = IMAGES[image]
    installed = installed_in_image(project, flags)
    missing = [
        f"{path.relative_to(REPO)}: import {name}"
        for path, name in third_party_imports(source_closure(REPO / source))
        if not providers(name) & installed
    ]
    assert not missing, f"the image {image} builds does not install:\n" + "\n".join(missing)


def installed_in_image(project: str, flags: list[str]) -> set[str]:
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-project", "--no-hashes", "--no-annotate", "--no-header", *flags],
        cwd=REPO / project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {normalized(m[1]) for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", exported, re.MULTILINE)}


def providers(top_level_module: str) -> set[str]:
    """The distributions that install a module, by what is installed here, else by its name."""
    return {normalized(d) for d in PROVIDERS_HERE.get(top_level_module, [top_level_module])}


def normalized(distribution: str) -> str:
    return re.sub(r"[-_.]+", "-", distribution).lower()


def source_closure(root: Path) -> set[Path]:
    """The files under root, and every yapit module they import, transitively, with their packages."""
    pending = list(root.rglob("*.py"))
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        pending += [p for p in package_inits(path) if p not in seen]
        for name in imported_modules(path):
            if name.split(".")[0] == "yapit":
                pending += [p for p in module_files(name) if p not in seen]
    return seen


def third_party_imports(files: set[Path]):
    for path in sorted(files):
        for name in sorted({n.split(".")[0] for n in imported_modules(path)}):
            if name != "yapit" and name not in sys.stdlib_module_names:
                yield path, name


def imported_modules(path: Path) -> set[str]:
    """Each module an import statement in the file names, `from a import b` naming both a and a.b."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module and not node.level, (
                f"{path}:{node.lineno}: a relative import, which this check cannot follow"
            )
            names.add(node.module)
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
    return names


def module_files(name: str) -> list[Path]:
    base = REPO.joinpath(*name.split("."))
    return [p for p in (base.with_suffix(".py"), base / "__init__.py") if p.exists()]


def package_inits(path: Path) -> list[Path]:
    return [
        REPO / d / "__init__.py"
        for d in path.relative_to(REPO).parents
        if d.parts and (REPO / d / "__init__.py").exists()
    ]
