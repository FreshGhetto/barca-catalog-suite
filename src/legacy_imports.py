from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple
import importlib.util
import sys

_ROOT = Path(__file__).resolve().parents[1]  # project root
_LEGACY_DIR = _ROOT / "legacy"

def _import_legacy_module(name: str, filename: str):
    path = _LEGACY_DIR / filename
    if not path.exists():
        raise FileNotFoundError(str(path))

    # Ensure legacy folder is importable so that legacy modules that do
    # `import barca_catalog_generator` can resolve it correctly.
    legacy_path_str = str(_LEGACY_DIR)
    if legacy_path_str not in sys.path:
        sys.path.insert(0, legacy_path_str)

    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def legacy_fetch_image_for_code(code: str) -> Tuple[Optional[bytes], Optional[str]]:
    mod = _import_legacy_module("_barca_image_fetcher_legacy", "barca_image_fetcher.py")
    if not hasattr(mod, "fetch_image_for_code"):
        raise AttributeError("legacy barca_image_fetcher.py missing fetch_image_for_code")
    return mod.fetch_image_for_code(code)
