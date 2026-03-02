from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from openpyxl import load_workbook

EXCEL_PARSER_VERSION = "2026-02-27-excel-v13e-unified-clean-synthXX"


_ART_RE = re.compile(r"^\s*\d+\s*/\s*[A-Za-z0-9]+[A-Za-z0-9]*\s*$")
_SIZE_RE = re.compile(r"^\s*(\d{2})\s*$")


def _norm_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    # normalize weird non-breaking spaces etc.
    return " ".join(s.replace("\xa0", " ").split())


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return 0.0
    s = _norm_str(v)
    if s == "":
        return 0.0
    # italian decimal comma
    s = s.replace(".", "").replace(",", ".") if re.search(r"\d+,\d+", s) else s
    try:
        return float(s)
    except Exception:
        return 0.0



def _find_value_after_label(row: List[Any], label: str) -> Optional[str]:
    """Find value that appears after a label like 'FORNITORE' in the same row.
    Handles patterns: LABEL, ':', VALUE or LABEL, VALUE.
    """
    lab = label.strip().upper()
    cells = [_norm_str(x) for x in row]
    up = [c.upper() for c in cells]
    for i, c in enumerate(up):
        if c == lab:
            # look ahead for first meaningful value (skip ':' and empty)
            for j in range(i + 1, min(i + 8, len(cells))):
                v = cells[j]
                if v == "" or v == ":":
                    continue
                return v
    return None


def _row_contains(row: List[Any], target: str) -> bool:
    t = target.strip().upper()
    return any(_norm_str(x).upper() == t for x in row)


def _update_context_from_row(row: List[Any]) -> Dict[str, str]:
    """Extract supplier/reparto/categoria/tipologia from a row if present."""
    out: Dict[str, str] = {}
    for key, lab in [("fornitore", "FORNITORE"), ("reparto", "REPARTO"), ("categoria", "CATEGORIA")]:
        v = _find_value_after_label(row, lab)
        if v:
            out[key] = v
    # tipologia can appear as 'TIPOLOGIA' in any column; take last non-empty after it
    if _row_contains(row, "TIPOLOGIA") or _row_contains(row, "TIPOLOGIA "):
        # if there is an explicit value after the label use it
        v = _find_value_after_label(row, "TIPOLOGIA")
        if v:
            out["tipologia"] = v
        else:
            vals = [_norm_str(x) for x in row if _norm_str(x)]
            if vals:
                out["tipologia"] = vals[-1]
    return out


def _iter_rows_from_xlsx(xlsx_path: Path, sheet: int | str = 0) -> Tuple[str, Iterable[List[Any]]]:
    wb = load_workbook(filename=str(xlsx_path), read_only=True, data_only=True)
    if isinstance(sheet, int):
        idx = sheet
        if idx < 0 or idx >= len(wb.worksheets):
            idx = 0
        ws = wb.worksheets[idx]
    else:
        # if user passes "0" as a string, treat it as index 0
        if isinstance(sheet, str) and sheet.strip().isdigit():
            idx = int(sheet.strip())
            if 0 <= idx < len(wb.worksheets):
                ws = wb.worksheets[idx]
            else:
                ws = wb.worksheets[0]
        else:
            ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]

    sheet_name = ws.title

    def gen():
        for row in ws.iter_rows(values_only=True):
            yield list(row)

    return sheet_name, gen()


def _find_table_header(row: List[Any]) -> Optional[Dict[str, int]]:
    """Return column indices (0-based) for KPI + perc + sizes if this is the header row."""
    cells = [_norm_str(x).upper() for x in row]
    if not cells:
        return None

    def find_one(target: str) -> Optional[int]:
        for i, c in enumerate(cells):
            if c == target:
                return i
        return None

    neg_i = find_one("NEG")
    giac_i = find_one("GIAC")
    con_i = find_one("CON")
    ven_i = find_one("VEN")

    if neg_i is None or giac_i is None or con_i is None or ven_i is None:
        return None

    # %VEN can be "%VEN" or "% VEN"
    perc_i = None
    for i, c in enumerate(cells):
        if c.replace(" ", "") in ("%VEN", "PERCVEN"):
            perc_i = i
            break

    # sizes: look for 2-digit numbers in header row
    size_cols: Dict[int, int] = {}
    for i, raw in enumerate(row):
        s = _norm_str(raw)
        m = _SIZE_RE.match(s)
        if m:
            size = int(m.group(1))
            size_cols[size] = i

    return {
        "neg": neg_i,
        "giac": giac_i,
        "con": con_i,
        "ven": ven_i,
        "perc": perc_i if perc_i is not None else -1,
        "size_cols_json": json.dumps(size_cols, sort_keys=True),
    }


def parse_situazione_articoli_excel(
    xlsx_path: str | Path,
    sheet: int | str = 0,
    temp_convert_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Parser robusto per il report 'SITUAZIONE ARTICOLI PER NEGOZIO'.
    Layout A (come 24E_donna.xlsx):
      - ARTICOLO codice in col 1
      - descrizione in col 3
      - colore in col 4
      - KPI/Taglie dalla tabella con header: NEG, GIAC, CON, VEN, %VEN, 35..42...
    """
    xlsx_path = Path(xlsx_path)
    source_file = xlsx_path.name

    sheet_name, rows = _iter_rows_from_xlsx(xlsx_path, sheet=sheet)

    # context "fill-down"
    stagione_da = ""
    stagione_descr = ""
    fornitore = ""
    reparto = ""
    categoria = ""
    tipologia = ""

    # table mapping
    table = None  # dict with indices
    size_cols: Dict[int, int] = {}

    # current article context
    cur_art = ""
    cur_descr = ""
    cur_colore = ""

    out: List[Dict[str, Any]] = []

    def flush_row(neg: str, giac: Any, con: Any, ven: Any, perc: Any, row_vals: List[Any]):
        nonlocal out, size_cols
        if not cur_art:
            return

        neg_s = _norm_str(neg).upper()
        if neg_s in {"NEG","GIAC","CON","VEN","%VEN","ARTICOLO"} or neg_s == "":
            return
        # store codes: keep only short alnum codes (AR, AU, ME2, SPW, WEB, 18, 128, etc)
        if not re.match(r"^[A-Z0-9]{1,4}$", neg_s):
            return
        giac_f = _as_float(giac)
        con_f = _as_float(con)
        ven_f = _as_float(ven)
        perc_f = _as_float(perc)

        sizes: Dict[int, float] = {}
        for sz, idx in size_cols.items():
            if idx < len(row_vals):
                q = _as_float(row_vals[idx])
                if q != 0.0:
                    sizes[sz] = q

        sizes_present = 1 if len(sizes) > 0 else 0

        out.append({
            "stagione_da": stagione_da,
            "stagione_descr": stagione_descr,
            "fornitore": fornitore,
            "reparto": reparto,
            "categoria": categoria,
            "tipologia": tipologia,
            "source_file": source_file,
            "source_sheet": sheet_name,
            "is_total": 1 if neg_s == "XX" else 0,
            "articolo": cur_art,
            "descrizione": cur_descr,
            "colore": cur_colore,
            "neg": neg_s,
            "giac": giac_f,
            "con": con_f,
            "ven": ven_f,
            "perc_ven": perc_f,
            "sizes_present": sizes_present,
            "sizes_json": json.dumps({str(k): v for k, v in sizes.items()}, ensure_ascii=False, sort_keys=True) if sizes_present else "",
            "synthetic_total": "",
        })

    for r in rows:
        if not r:
            continue

        # update context by keywords in first cell(s)
        c0 = _norm_str(r[0]).upper()
        c2 = _norm_str(r[2]).upper() if len(r) > 2 else ""
        c3 = _norm_str(r[3]).upper() if len(r) > 3 else ""

        # stagione row example: col4 "Stagione  da:" then values
        if any(_norm_str(x).upper().startswith("STAGIONE") for x in r[:6]):
            # try pick "da" value next to "Stagione  da:"
            # in sample: [None,None,None,'Stagione  da:', '24E','2024 ESTATE',None,'a:', '24E 2024 ESTATE',...]
            for i, v in enumerate(r):
                if _norm_str(v).upper().startswith("STAGIONE"):
                    if i + 1 < len(r):
                        stagione_da = _norm_str(r[i + 1])
                    if i + 2 < len(r):
                        stagione_descr = _norm_str(r[i + 2])
                    break
        # update supplier/reparto/categoria/tipologia if they appear anywhere in the row
        ctx = _update_context_from_row(r)
        if 'fornitore' in ctx:
            fornitore = ctx['fornitore']
        if 'reparto' in ctx:
            reparto = ctx['reparto']
        if 'categoria' in ctx:
            categoria = ctx['categoria']
        if 'tipologia' in ctx:
            tipologia = ctx['tipologia']

        # detect table header row
        header_map = _find_table_header(r)
        if header_map:
            table = header_map
            size_cols = json.loads(table["size_cols_json"])
            continue

        if table is None:
            continue  # not in table yet

        # Determine if this is a new article row:
        art_candidate = _norm_str(r[0])
        if _ART_RE.match(art_candidate):
            cur_art = art_candidate.replace(" ", "")
            cur_descr = _norm_str(r[2]) if len(r) > 2 else ""
            cur_colore = _norm_str(r[3]) if len(r) > 3 else ""

            # also parse the same row as first store row (it has NEG etc)
            neg = r[table["neg"]] if table["neg"] < len(r) else ""
            giac = r[table["giac"]] if table["giac"] < len(r) else 0
            con = r[table["con"]] if table["con"] < len(r) else 0
            ven = r[table["ven"]] if table["ven"] < len(r) else 0
            perc = r[table["perc"]] if table["perc"] != -1 and table["perc"] < len(r) else 0
            flush_row(neg, giac, con, ven, perc, r)
            continue

        # store continuation row: must have NEG filled
        neg_val = r[table["neg"]] if table["neg"] < len(r) else None
        if _norm_str(neg_val) != "":
            # skip page header repeats like "Pagina"
            if _norm_str(neg_val).upper() in ("PAGINA",):
                continue
            giac = r[table["giac"]] if table["giac"] < len(r) else 0
            con = r[table["con"]] if table["con"] < len(r) else 0
            ven = r[table["ven"]] if table["ven"] < len(r) else 0
            perc = r[table["perc"]] if table["perc"] != -1 and table["perc"] < len(r) else 0
            flush_row(neg_val, giac, con, ven, perc, r)

    df = pd.DataFrame(out)
    # Ensure columns exist that downstream expects
    for col in ["stagione_da","stagione_descr","fornitore","reparto","categoria","tipologia",
                "source_file","source_sheet","is_total","articolo","descrizione","colore","neg",
                "giac","con","ven","perc_ven","sizes_present","sizes_json","synthetic_total"]:
        if col not in df.columns:
            df[col] = "" if col not in ("giac","con","ven","perc_ven","sizes_present","is_total") else 0


    # --- Build/override XX totals as synthetic (sum of stores) ---
    # The report's printed 'XX' line can shift columns or be missing; for contabilità we
    # enforce XX = sum(negozi) for giac/con/ven.
    key_cols = ["source_file", "source_sheet", "stagione_da", "stagione_descr", "articolo"]
    # Make sure numeric
    for nc in ["giac", "con", "ven", "perc_ven"]:
        df[nc] = pd.to_numeric(df[nc], errors="coerce").fillna(0)

    new_rows = []
    for _, g in df.groupby(key_cols, dropna=False):
        g = g.copy()
        stores = g[g["neg"] != "XX"]
        sums = stores[["giac", "con", "ven"]].sum()
        con_tot = float(sums["con"])
        ven_tot = float(sums["ven"])
        perc_tot = (ven_tot / con_tot * 100.0) if con_tot else 0.0

        xx_mask = g["neg"] == "XX"
        if xx_mask.any():
            # Override existing XX row values
            idxs = g.index[xx_mask].tolist()
            # If multiple XX rows, keep first and drop others
            keep = idxs[0]
            df.loc[keep, ["giac", "con", "ven", "perc_ven"]] = [float(sums["giac"]), con_tot, ven_tot, perc_tot]
            df.loc[keep, "is_total"] = 1
            df.loc[keep, "synthetic_total"] = 1
            for drop_i in idxs[1:]:
                df = df.drop(index=drop_i)
        else:
            # Create synthetic XX row copying metadata from first store row (or first row)
            base = (stores.iloc[0] if len(stores) else g.iloc[0]).to_dict()
            base.update({
                "neg": "XX",
                "is_total": 1,
                "giac": float(sums["giac"]),
                "con": con_tot,
                "ven": ven_tot,
                "perc_ven": perc_tot,
                "sizes_present": 0,
                "sizes_json": "{}",
                "synthetic_total": 1,
            })
            new_rows.append(base)

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)


    return df
