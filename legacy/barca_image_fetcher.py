from typing import Optional, Tuple
import requests

import barca_catalog_generator as bcg

# Sessione unica riutilizzata (più veloce e identica al metodo vecchio)
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        # usa lo stesso User-Agent del tuo script originale
        ua = getattr(bcg, "UA", None)
        if ua:
            s.headers.update({"User-Agent": ua})
        _SESSION = s
    return _SESSION


def fetch_image_for_code(code: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Scarica l'immagine usando ESATTAMENTE la logica del tuo barca_catalog_generator.py.
    Ritorna: (image_bytes, error_string)
    """
    try:
        session = _get_session()
        url, img_bytes, err = bcg.fetch_best_image_for_code(session, str(code).strip())
        if img_bytes:
            return img_bytes, None
        return None, err or "not_found"
    except Exception as e:
        return None, f"exc_{type(e).__name__}"
