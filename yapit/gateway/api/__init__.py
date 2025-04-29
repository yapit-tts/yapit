from importlib import import_module
from pathlib import Path

# auto-import subpackages so routers register
for pkg in Path(__file__).parent.iterdir():
    if (pkg / "__init__.py").exists():
        import_module(f"{__package__}.{pkg.name}")
