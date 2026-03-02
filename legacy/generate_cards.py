from __future__ import annotations

import argparse
import csv
from pathlib import Path

from barca_cards.run_manager import prepare_run_dirs
from barca_cards.io_codes import load_codes_csv
from barca_cards.season_parser import parse_season_csv
from barca_cards.images_provider import fetch_image_bytes
from barca_cards.card_renderer import render_card
from barca_cards.season_id import season_from_filename


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season1", required=True, help="CSV stagione 1 (es. 24E_donna.csv)")
    parser.add_argument("--season2", required=True, help="CSV stagione 2 (es. 24G_donna.csv)")
    parser.add_argument("--codes", required=True, help="CSV lista codici (anche report 'Analisi Articoli')")
    parser.add_argument("--code-col", default=None, help="(Opzionale) Nome colonna codici nel CSV lista")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    paths = prepare_run_dirs(project_root)

    season_files = [Path(args.season1), Path(args.season2)]
    codes_csv = Path(args.codes)
    code_col = args.code_col

    # === PARSE + MERGE STAGIONE ===
    all_articles = {}

    season_labels = [season_from_filename(p) for p in season_files]
    run_label = "_".join([s for s in season_labels if s]) or "SEASON_RUN"

    for sf in season_files:
        if not sf.exists():
            raise FileNotFoundError(f"File stagione non trovato: {sf}")
        data = parse_season_csv(sf)

        for code, ar in data.items():
            if not ar.season:
                ar.season = season_from_filename(sf)

            if code not in all_articles:
                all_articles[code] = ar
            else:
                base = all_articles[code]

                for attr in ["description", "color", "season", "supplier", "reparto", "categoria", "tipologia"]:
                    if getattr(base, attr, "") == "" and getattr(ar, attr, "") != "":
                        setattr(base, attr, getattr(ar, attr))

                base.stores.update(ar.stores)

                base.giac = sum(sr.giac for sr in base.stores.values())
                base.con = sum(sr.con for sr in base.stores.values())
                base.ven = sum(sr.ven for sr in base.stores.values())
                base.perc_ven = (base.ven / base.con * 100.0) if base.con > 0 else 0.0

                size_totals = {}
                for sr in base.stores.values():
                    for s, v in sr.sizes.items():
                        size_totals[s] = size_totals.get(s, 0.0) + v
                base.size_totals = size_totals

    # debug indice
    index_path = paths.tmp / f"articles_index_{run_label}.csv"
    with open(index_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "description", "color", "season", "supplier", "stores", "giac", "con", "ven", "perc_ven"])
        for code, ar in sorted(all_articles.items()):
            w.writerow([code, ar.description, ar.color, ar.season, ar.supplier, len(ar.stores), ar.giac, ar.con, ar.ven, ar.perc_ven])

    # === LISTA CODICI ===
    if not codes_csv.exists():
        raise FileNotFoundError(f"File lista codici non trovato: {codes_csv}")

    codes = load_codes_csv(codes_csv, code_column=code_col)

    missing = []
    img_errors = []

    cards_dir = paths.output / f"cards_{run_label}"
    cards_dir.mkdir(parents=True, exist_ok=True)

    for code in codes:
        ar = all_articles.get(code)
        if ar is None:
            missing.append(code)
            continue

        img_bytes, err = fetch_image_bytes(code)
        if err:
            img_errors.append((code, err))

        card = render_card(ar, img_bytes)
        out_path = cards_dir / f"{code.replace('/', '_')}.jpg"
        card.save(out_path, quality=92)

    miss_path = paths.output / f"missing_codes_{run_label}.csv"
    with open(miss_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["code"])
        for c in missing:
            w.writerow([c])

    err_path = paths.output / f"image_errors_{run_label}.csv"
    with open(err_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["code", "error"])
        for c, e in img_errors:
            w.writerow([c, e])

    print("OK ✅")
    print(f"Card generate in: {cards_dir}")
    print(f"Missing: {miss_path}")
    print(f"Image errors: {err_path}")
    print(f"Debug: {paths.tmp} (prev: {paths.prev})")


if __name__ == "__main__":
    main()
