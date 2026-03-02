import re
import csv
from pathlib import Path
from collections import defaultdict

import pandas as pd
import pdfplumber


ART_RE = re.compile(r"^(48|49)/[A-Z0-9]+$", re.IGNORECASE)
TOT_G = re.compile(r"TOT\.\s*GIAC\.\s*(\d+)", re.IGNORECASE)
TOT_C = re.compile(r"TOT\.\s*CON\.\s*(\d+)", re.IGNORECASE)
TOT_V = re.compile(r"TOT\.\s*VEN\.\s*(\d+)", re.IGNORECASE)

def parse_pdf_totals(pdf_path: Path) -> dict:
    """
    Estrae TOT GIAC / TOT CON / TOT VEN per articolo dal PDF.
    Ritorna: { articolo: {"giac":int|None, "con":int|None, "ven":int|None} }
    """
    totals = {}
    current_art = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not text.strip():
                continue

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Articolo è spesso a inizio riga
                first = line.split()[0] if line.split() else ""
                if ART_RE.match(first):
                    current_art = first.upper()
                    totals.setdefault(current_art, {"giac": None, "con": None, "ven": None})

                if current_art:
                    mg = TOT_G.search(line)
                    if mg:
                        totals[current_art]["giac"] = int(mg.group(1))
                    mc = TOT_C.search(line)
                    if mc:
                        totals[current_art]["con"] = int(mc.group(1))
                    mv = TOT_V.search(line)
                    if mv:
                        totals[current_art]["ven"] = int(mv.group(1))

    return totals

def load_db_sums(db_csv: Path) -> dict:
    """
    Somma GIAC/CON/VEN per articolo dal DB, escludendo neg == XX.
    Ritorna: { articolo: {"giac":int, "con":int, "ven":int} }
    """
    df = pd.read_csv(db_csv, dtype=str, keep_default_na=False)

    for c in ("giac","con","ven"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    df["neg"] = df["neg"].astype(str).str.strip()
    df["articolo"] = df["articolo"].astype(str).str.strip().str.upper()

    df_store = df[df["neg"].str.upper() != "XX"].copy()

    sums = (
        df_store
        .groupby("articolo")[["giac","con","ven"]]
        .sum()
        .reset_index()
    )

    out = {}
    for _, r in sums.iterrows():
        out[r["articolo"]] = {"giac": int(r["giac"]), "con": int(r["con"]), "ven": int(r["ven"])}
    return out

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="PDF report (24E_donna.pdf)")
    ap.add_argument("--db", required=True, help="CSV DB generato (barca_db.csv)")
    ap.add_argument("--outdir", default="data/temp", help="Cartella output report")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    db_path  = Path(args.db)
    outdir   = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    print(f"Leggo PDF: {pdf_path}")
    pdf_tot = parse_pdf_totals(pdf_path)
    print(f"Articoli con TOT trovati nel PDF: {len(pdf_tot)}")

    print(f"Leggo DB: {db_path}")
    db_sum = load_db_sums(db_path)
    print(f"Articoli nel DB (somma negozi): {len(db_sum)}")

    # Confronto
    all_arts = sorted(set(pdf_tot.keys()) | set(db_sum.keys()))
    rows = []

    mism = 0
    missing_in_pdf = 0
    missing_in_db = 0
    incomplete_pdf_tot = 0

    for art in all_arts:
        p = pdf_tot.get(art)
        d = db_sum.get(art)

        status = "OK"
        if p is None:
            status = "MISSING_IN_PDF"
            missing_in_pdf += 1
        elif d is None:
            status = "MISSING_IN_DB"
            missing_in_db += 1
        else:
            # PDF totals completi?
            if p["giac"] is None or p["con"] is None or p["ven"] is None:
                status = "PDF_TOTALS_INCOMPLETE"
                incomplete_pdf_tot += 1
            else:
                if (p["giac"], p["con"], p["ven"]) != (d["giac"], d["con"], d["ven"]):
                    status = "MISMATCH"
                    mism += 1

        rows.append({
            "articolo": art,
            "status": status,
            "pdf_giac": None if p is None else p["giac"],
            "pdf_con":  None if p is None else p["con"],
            "pdf_ven":  None if p is None else p["ven"],
            "db_giac":  None if d is None else d["giac"],
            "db_con":   None if d is None else d["con"],
            "db_ven":   None if d is None else d["ven"],
        })

    report_path = outdir / "audit_pdf_vs_db_report.csv"
    pd.DataFrame(rows).to_csv(report_path, index=False, encoding="utf-8")

    print("\n=== RISULTATO AUDIT ===")
    print(f"Tot articoli (unione PDF+DB): {len(all_arts)}")
    print(f"MISMATCH: {mism}")
    print(f"MISSING_IN_PDF: {missing_in_pdf}")
    print(f"MISSING_IN_DB: {missing_in_db}")
    print(f"PDF_TOTALS_INCOMPLETE: {incomplete_pdf_tot}")
    print(f"\n✅ Report salvato: {report_path}")

    # Stampa i primi 30 mismatch per comodità
    if mism > 0:
        df = pd.read_csv(report_path)
        print("\nPrimi 30 MISMATCH:")
        print(df[df["status"]=="MISMATCH"].head(30).to_string(index=False))

if __name__ == "__main__":
    main()