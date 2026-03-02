from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence
import csv
import io
import re
import sys

COMMON_CODE_COLS = [
    "codice", "code", "articolo", "article", "sku", "id", "id_articolo", "cod_articolo"
]

# Barca codes always look like: 59/0642CTM
CODE_RE = re.compile(r"\b\d{1,3}/[A-Z0-9]{2,}\b", re.IGNORECASE)

_DELIM_CANDIDATES: Sequence[str] = (";", ",", "\t", "|")


def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        return dialect.delimiter
    except Exception:
        counts = {d: sample.count(d) for d in _DELIM_CANDIDATES}
        return max(counts, key=counts.get) if counts else ";"


def _normalize_code(s: str) -> str:
    s = (s or "").strip().upper()
    s = s.strip('"').strip("'")
    s = s.replace(" ", "")
    return s


def _dedup_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _try_parse_with_legacy_barca_parser(data: bytes) -> Optional[List[str]]:
    """Use Diego's proven parser for 'Analisi Articoli' / ANART report exports.

    The legacy parser returns a DataFrame with a 'code' column, and it is robust to:
    - broken quoting
    - newlines inside fields
    - variable number of columns per row
    """
    try:
        legacy_dir = Path(__file__).resolve().parents[2] / "legacy"
        legacy_path = str(legacy_dir)
        if legacy_path not in sys.path:
            sys.path.insert(0, legacy_path)

        import barca_parser  # type: ignore

        df = barca_parser.clean_anart_report_bytes(data)  # type: ignore
        if df is None or len(df) == 0 or "code" not in df.columns:
            return None

        codes = []
        for v in df["code"].astype(str).tolist():
            v = _normalize_code(v)
            m = CODE_RE.search(v)
            if m:
                codes.append(m.group(0).upper())
        return _dedup_keep_order(codes)
    except Exception:
        return None


def load_codes_csv(path: str | Path, code_column: Optional[str] = None) -> List[str]:
    """Load a list of item codes from a CSV.

    Priority:
    1) Try the legacy 'barca_parser.clean_anart_report_bytes' (handles Barca report exports).
    2) Fallback to a tolerant csv-module reader for simple "one-column codes" files.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    data = path.read_bytes()

    # 1) Try the proven parser first
    parsed = _try_parse_with_legacy_barca_parser(data)
    if parsed:
        return parsed

    # 2) Fallback: tolerant CSV reader (for already-clean lists)
    text = data.decode("utf-8", errors="replace")
    sample = "\n".join(text.splitlines()[:25])
    delim = _sniff_delimiter(sample)

    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]] if rows[0] else []
    data_rows = rows[1:] if header else rows

    col_idx: Optional[int] = None
    if header:
        if code_column and code_column.strip().lower() in header:
            col_idx = header.index(code_column.strip().lower())
        else:
            for cand in COMMON_CODE_COLS:
                if cand in header:
                    col_idx = header.index(cand)
                    break

    out: List[str] = []
    for r in data_rows:
        if not r:
            continue

        val = ""
        if col_idx is not None and col_idx < len(r):
            val = r[col_idx]
        else:
            # fallback: scan all cells and pick the first code-like token found
            joined = " ".join([c for c in r if c])
            m = CODE_RE.search(joined)
            if m:
                out.append(m.group(0).upper())
                continue
            # else: first non-empty
            for cell in r:
                if cell and cell.strip():
                    val = cell
                    break

        val = _normalize_code(val)
        m = CODE_RE.search(val)
        if m:
            out.append(m.group(0).upper())

    return _dedup_keep_order(out)
