from __future__ import annotations
from typing import Optional, Tuple

def fetch_image_bytes(code: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Wrapper robusto:
    - prova a usare legacy/barca_image_fetcher.py (che a sua volta usa barca_catalog_generator.py)
    - se mancano dipendenze, ritorna errore chiaro
    """
    try:
        # Import lazy to keep app start fast
        from legacy_imports import legacy_fetch_image_for_code
        return legacy_fetch_image_for_code(code)
    except Exception as e:
        return None, f"image_fetch_unavailable:{type(e).__name__}"
