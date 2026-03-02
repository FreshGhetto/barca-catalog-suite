
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

import excel_parser
from excel_parser import parse_situazione_articoli_excel

PARSE_SEASON_VERSION = "2026-02-26-excel-project-v10-validator-synthxx"

# Columns we expect
NUMERIC_COLS = ["giac", "con", "ven", "perc_ven"]
TEXT_COLS = [
    "stagione_da", "stagione_descr", "fornitore", "reparto", "categoria", "tipologia",
    "source_file", "source_sheet", "articolo", "descrizione", "colore", "neg",
]
DEFAULT_OUT_DB = Path("data/processed/barca_db.csv")


def clean_temp_dir(temp_dir: Path) -> None:
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)


def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    # Create missing expected columns to avoid KeyErrors
    for c in TEXT_COLS:
        if c not in df.columns:
            df[c] = ""
    for c in NUMERIC_COLS:
        if c not in df.columns:
            df[c] = 0.0
    # normalize types
    for c in TEXT_COLS:
        df[c] = df[c].astype("string").fillna("")
    for c in NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def save_debug_snapshot(df: pd.DataFrame, temp_dir: Path, input_path: Path) -> Path:
    snap = temp_dir / f"{input_path.stem}__parsed_snapshot.csv"
    df.to_csv(snap, index=False, encoding="utf-8-sig")
    return snap


def update_db(df_new: pd.DataFrame, out_db: Path) -> pd.DataFrame:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    df_new.to_csv(out_db, index=False, encoding="utf-8-sig")
    return df_new


def validate_totals_synthxx(db: pd.DataFrame, temp_dir: Path) -> pd.DataFrame:
    """
    Validation that is compatible with synth-XX mode:
    - We group only by stable identifiers (file/sheet/season/article).
    - We consider the total row as any row with neg == 'XX' (regardless of is_total flags).
    - We ignore description/color differences to avoid 'orphan_total_row' due to metadata drift.
    - If there are no store rows for an article, we skip totals validation for that article.
    """
    if db is None or db.empty:
        return pd.DataFrame(columns=["type","key","col","sum_stores","xx_total","delta"])

    db = _ensure_cols(db.copy())

    group_cols = ["source_file", "source_sheet", "stagione_da", "stagione_descr", "articolo"]

    rows = []
    for gkey, gdf in db.groupby(group_cols, dropna=False):
        source_file, source_sheet, stagione_da, stagione_descr, articolo = gkey

        stores = gdf[gdf["neg"].astype(str).str.upper() != "XX"]
        totals = gdf[gdf["neg"].astype(str).str.upper() == "XX"]

        # If an article has no store rows, totals in the sheet are usually empty; skip.
        if len(stores) == 0:
            continue

        if len(totals) == 0:
            rows.append({
                "type": "missing_total_row",
                "key": "|".join([str(x) for x in gkey]),
                "col": "",
                "sum_stores": "",
                "xx_total": "",
                "delta": "",
            })
            continue

        # Use the first XX row (there should be exactly one in synthXX mode)
        xx = totals.iloc[0]

        for col in ["giac", "con", "ven"]:
            sum_stores = float(pd.to_numeric(stores[col], errors="coerce").fillna(0.0).sum())
            xx_total = float(pd.to_numeric(xx[col], errors="coerce") if col in xx else 0.0)
            delta = sum_stores - xx_total
            # tiny float noise tolerance
            if abs(delta) > 1e-9:
                rows.append({
                    "type": "total_mismatch",
                    "key": "|".join([str(x) for x in gkey]),
                    "col": col,
                    "sum_stores": sum_stores,
                    "xx_total": xx_total,
                    "delta": delta,
                })

    mismatch_df = pd.DataFrame(rows, columns=["type","key","col","sum_stores","xx_total","delta"])
    out = temp_dir / "validation_mismatch.csv"
    mismatch_df.to_csv(out, index=False, encoding="utf-8-sig")
    return mismatch_df


def extract_articles_from_excel(xlsx_path: Path, sheet: Optional[str]) -> List[str]:
    """
    Extract article codes from Excel by scanning the first column for patterns like 48/.... or 49/....
    This is only for completeness checks.
    """
    import re
    from openpyxl import load_workbook

    wb = load_workbook(filename=str(xlsx_path), read_only=True, data_only=True)

    ws = None
    if sheet is None:
        ws = wb.worksheets[0]
    else:
        # accept both index ("0") and sheet name
        if isinstance(sheet, str) and sheet.strip().isdigit():
            ws = wb.worksheets[int(sheet)]
        else:
            ws = wb[sheet]

    pat = re.compile(r"^\s*(\d{2}/[A-Z0-9]+)\s*$", re.IGNORECASE)
    arts = []
    for row in ws.iter_rows(values_only=True):
        v = row[0] if row else None
        if v is None:
            continue
        s = str(v).strip()
        m = pat.match(s)
        if m:
            arts.append(m.group(1).upper())
    # unique preserving order
    seen = set()
    out = []
    for a in arts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def validate_completeness(input_files: List[Path], db: pd.DataFrame, sheet: Optional[str], temp_dir: Path) -> pd.DataFrame:
    if db is None or db.empty:
        miss = pd.DataFrame(columns=["source_file","articolo"])
        (temp_dir / "validation_missing_articles.csv").write_text("", encoding="utf-8")
        return miss

    db = _ensure_cols(db.copy())
    db_arts = set(db["articolo"].astype(str).str.upper().str.strip().tolist())

    missing_rows = []
    for fp in input_files:
        excel_arts = extract_articles_from_excel(fp, sheet)
        for a in excel_arts:
            if a not in db_arts:
                missing_rows.append({"source_file": fp.name, "articolo": a})

    missing_df = pd.DataFrame(missing_rows, columns=["source_file","articolo"])
    missing_df.to_csv(temp_dir / "validation_missing_articles.csv", index=False, encoding="utf-8-sig")
    return missing_df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=str, required=True, help="Path to input .xlsx")
    ap.add_argument("--sheet", type=str, default=None, help="Sheet index (e.g. 0) or name")
    ap.add_argument("--clean-temp", action="store_true", help="Clean temp directory before running")
    ap.add_argument("--debug", action="store_true", help="Write debug snapshot to data/temp")
    ap.add_argument("--validate", action="store_true", help="Run validation after parsing")
    args = ap.parse_args()

    print(f"🔎 excel_parser version: {getattr(excel_parser, 'EXCEL_PARSER_VERSION', 'unknown')}")
    print(f"🔎 parse_season_excel version: {PARSE_SEASON_VERSION}")

    project_root = Path(".")
    temp_dir = project_root / "data" / "temp"
    processed_dir = project_root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    if args.clean_temp:
        clean_temp_dir(temp_dir)
        print("🧹 data/temp pulita")

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))

    print(f"→ Parsing: {input_path.name}")

    df = parse_situazione_articoli_excel(input_path, sheet=args.sheet, temp_convert_dir=temp_dir)
    df = _ensure_cols(df)

    if args.debug:
        snap = save_debug_snapshot(df, temp_dir, input_path)
        print(f"  [debug] snapshot: {snap.name} (righe: {len(df)})")

    db_path = DEFAULT_OUT_DB
    update_db(df, db_path)

    print(f"\n✅ DB aggiornato: {db_path.resolve()}")
    print(f"   Righe totali: {len(df)}")
    try:
        stores_unique = df[df["neg"].astype(str).str.upper() != "XX"]["neg"].nunique()
    except Exception:
        stores_unique = df["neg"].nunique()
    print(f"   Negozi unici: {stores_unique}")
    print(f"   Righe totali XX: {(df['neg'].astype(str).str.upper()=='XX').sum()}")

    if args.validate:
        mismatch_df = validate_totals_synthxx(df, temp_dir)
        if mismatch_df.empty:
            print("\n✅ VALIDATION OK: nessun mismatch trovato.")
        else:
            print("\n⚠️ VALIDATION: trovati mismatch.")
            print(f"   Report: {(temp_dir / 'validation_mismatch.csv').resolve()}\n")
            print("Dettaglio mismatch types:")
            print(mismatch_df.groupby("type").size())

        # completeness
        missing_df = validate_completeness([input_path], df, args.sheet, temp_dir=temp_dir)
        if missing_df.empty:
            print("\n✅ COMPLETEZZA OK: nessun articolo mancante (Excel → DB).")
        else:
            print("\n❌ COMPLETEZZA KO: articoli mancanti (Excel → DB).")
            print(f"   Report: {(temp_dir / 'validation_missing_articles.csv').resolve()}")


if __name__ == "__main__":
    main()
