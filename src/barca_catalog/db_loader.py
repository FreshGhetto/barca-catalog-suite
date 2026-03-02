from __future__ import annotations
from pathlib import Path
import io
from typing import Dict
import json
import pandas as pd

from .models import Article, StoreRow

def _to_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0

def _pick(r, *cands: str) -> str:
    """Pick first non-empty field among candidate column names."""
    for c in cands:
        try:
            v = r.get(c, "")
        except Exception:
            v = ""
        s = str(v or "").strip()
        if s:
            return s
    return ""

def load_articles_from_barca_db(db: str | Path | pd.DataFrame | bytes | bytearray) -> Dict[str, Article]:
    """Carica il DB BARCA (CSV generato dal parser) e ritorna dict code->Article.

    Supporta:
      - path CSV (str/Path)
      - pandas.DataFrame (utile quando il CSV è già in memoria)
    """
    if isinstance(db, (bytes, bytearray)):
        # Support in-memory CSV bytes (Streamlit uploader / generated DB)
        df = pd.read_csv(io.BytesIO(db), dtype=str, keep_default_na=False, encoding_errors="replace")
    elif isinstance(db, pd.DataFrame):
        df = db.copy()
    else:
        db_path = Path(db)
        if not db_path.exists():
            raise FileNotFoundError(str(db_path))
        df = pd.read_csv(db_path, dtype=str, keep_default_na=False, encoding_errors="replace")

    if df.empty:
        return {}

    # normalize column names (case/space insensitive)
    df.columns = [str(c).strip().lower() for c in df.columns]

    # normalize numeric
    for col in ["giac","con","ven","perc_ven"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # normalize keys
    if "articolo" not in df.columns and "code" in df.columns:
        df["articolo"] = df["code"]
    if "neg" not in df.columns and "store" in df.columns:
        df["neg"] = df["store"]

    df["articolo"] = df.get("articolo", "").astype(str).str.strip().str.upper().str.replace(" ", "", regex=False)
    df["neg"] = df.get("neg", "").astype(str).str.strip().str.upper().str.replace(" ", "", regex=False)

    arts: Dict[str, Article] = {}

    for _, r in df.iterrows():
        code = str(r.get("articolo","")).strip().upper().replace(" ", "")
        if not code:
            continue

        # --- metadata fallbacks (different exports use different names)
        descr = _pick(r, "descrizione", "product", "description")
        color = _pick(r, "colore", "color")
        season = _pick(r, "stagione_da", "stagione_descr", "season")
        supplier = _pick(r, "fornitore", "supplier", "brand")
        reparto = _pick(r, "reparto", "department")
        categoria = _pick(r, "categoria", "category")
        tipologia = _pick(r, "tipologia", "type", "tipologia_descr")

        ar = arts.get(code)
        if ar is None:
            ar = Article(
                code=code,
                description=descr,
                color=color,
                season=season,
                supplier=supplier,
                reparto=reparto,
                categoria=categoria,
                tipologia=tipologia,
            )
            arts[code] = ar
        else:
            # fill missing meta
            for attr, val in [
                ("description", descr),("color", color),("season", season),
                ("supplier", supplier),("reparto", reparto),("categoria", categoria),("tipologia", tipologia)
            ]:
                if (not getattr(ar, attr)) and val:
                    setattr(ar, attr, val)

        sf = str(r.get("source_file","") or "")
        if sf:
            ar.source_files.add(sf)

        store = str(r.get("neg","") or "").strip().upper().replace(" ", "")
        giac = _to_float(r.get("giac",0.0))
        con  = _to_float(r.get("con",0.0))
        ven  = _to_float(r.get("ven",0.0))
        perc = _to_float(r.get("perc_ven",0.0))

        sizes = {}
        sj = str(r.get("sizes_json","") or "")
        if sj and sj not in ("{}", "[]"):
            try:
                j = json.loads(sj)
                for k, v in (j or {}).items():
                    try:
                        sizes[int(k)] = float(v)
                    except Exception:
                        pass
            except Exception:
                sizes = {}

        ar.stores[store] = StoreRow(store=store, giac=giac, con=con, ven=ven, perc_ven=perc, sizes=sizes)

    # recompute totals from stores (excluding XX)
    for ar in arts.values():
        ar.recompute_totals()

    return arts
