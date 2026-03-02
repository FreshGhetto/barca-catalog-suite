from __future__ import annotations

from pathlib import Path
import shutil
import csv

import streamlit as st

from barca_cards.run_manager import prepare_run_dirs
from barca_cards.season_parser import parse_season_csv  # deve ritornare (dict, stats)
from barca_cards.io_codes import load_codes_from_csv
from barca_cards.images_provider import fetch_image_bytes
from barca_cards.card_renderer import render_card

st.set_page_config(page_title="Barca – Generatore Catalogo (FIXED)", layout="wide")
st.title("Barca – Generatore Catalogo (Card JPG) • FIXED")
st.caption("Carica 2 file stagione + 1 file lista codici → genera card tecniche con foto e dati. Parser stagione data-driven + debug.")

paths = prepare_run_dirs(Path.cwd())

def save_upload(upload, name: str) -> Path:
    p = paths.inputs_dir / name
    with open(p, "wb") as f:
        f.write(upload.getbuffer())
    return p

with st.sidebar:
    st.header("Input")
    up_s1 = st.file_uploader("Stagione 1 (CSV)", type=["csv"])
    up_s2 = st.file_uploader("Stagione 2 (CSV)", type=["csv"])
    up_lst = st.file_uploader("Lista articoli (CSV)", type=["csv"])
    st.divider()
    keep_prev = st.checkbox("Mantieni _tmp_run_prev per debug", value=True)
    preview_n = st.number_input("Anteprima card (N)", min_value=0, max_value=5, value=1, step=1)

st.info(f"Input salvati in: {paths.inputs_dir}")

btn = st.button("Genera catalogo", type="primary", use_container_width=True, disabled=not (up_s1 and up_s2 and up_lst))

if btn:
    if not keep_prev and paths.prev.exists():
        shutil.rmtree(paths.prev, ignore_errors=True)

    file1 = save_upload(up_s1, "season1.csv")
    file2 = save_upload(up_s2, "season2.csv")
    list_path = save_upload(up_lst, "codes.csv")

    # === PARSE STAGIONI ===
    with st.spinner("Parsing stagione 1..."):
        data1, st1 = parse_season_csv(file1)
    with st.spinner("Parsing stagione 2..."):
        data2, st2 = parse_season_csv(file2)

    # === MERGE ===
    all_articles = dict(data1)
    for code, ar in data2.items():
        if code not in all_articles:
            all_articles[code] = ar
        else:
            base = all_articles[code]
            base.stores.update(ar.stores)

            # ricalcola totali
            base.giac = sum(sr.giac for sr in base.stores.values())
            base.con = sum(sr.con for sr in base.stores.values())
            base.ven = sum(sr.ven for sr in base.stores.values())
            base.perc_ven = (base.ven / base.con * 100.0) if base.con > 0 else 0.0

            size_totals = {}
            for sr in base.stores.values():
                for s, v in sr.sizes.items():
                    size_totals[s] = size_totals.get(s, 0.0) + v
            base.size_totals = size_totals

    st.success(f"Articoli indicizzati: {len(all_articles)}")

    # === DEBUG ===
    with st.expander("Debug parser stagione (importantissimo)", expanded=True):
        colA, colB = st.columns(2)
        with colA:
            st.subheader("Season 1 debug")
            st.write({
                "delimiter": repr(st1.delimiter),
                "rows_total": st1.rows_total,
                "rows_with_code": st1.rows_with_code,
                "rows_short": st1.rows_short,
                "rows_parsed": st1.rows_parsed,
                "first_code_cell": st1.first_code_cell,
                "first_sample": st1.first_sample,
            })
        with colB:
            st.subheader("Season 2 debug")
            st.write({
                "delimiter": repr(st2.delimiter),
                "rows_total": st2.rows_total,
                "rows_with_code": st2.rows_with_code,
                "rows_short": st2.rows_short,
                "rows_parsed": st2.rows_parsed,
                "first_code_cell": st2.first_code_cell,
                "first_sample": st2.first_sample,
            })

    # === LISTA CODICI ===
    with st.spinner("Leggo lista codici..."):
        codes = load_codes_from_csv(list_path)

    st.write(f"Codici richiesti: **{len(codes)}**")

    # === GENERAZIONE CARD ===
    missing = []
    img_errors = []
    generated = 0

    with st.spinner("Genero card..."):
        for code in codes:
            ar = all_articles.get(code)
            if ar is None:
                missing.append(code)
                continue

            img_bytes, err = fetch_image_bytes(code)
            if err:
                img_errors.append((code, err))

            card = render_card(ar, img_bytes)
            out_path = paths.cards_out / f"{code.replace('/', '_')}.jpg"
            card.save(out_path, quality=92)
            generated += 1

            if preview_n and generated <= preview_n:
                st.image(card, caption=code, use_container_width=True)

    # === REPORT ===
    c1, c2, c3 = st.columns(3)
    c1.metric("Card generate", generated)
    c2.metric("Missing", len(missing))
    c3.metric("Errori immagini", len(img_errors))

    st.write("Output su disco:", str(paths.output))

    miss_path = paths.output / "missing_codes_SEASON_RUN.csv"
    with open(miss_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code"])
        w.writerows([[c] for c in missing])

    err_path = paths.output / "image_errors_SEASON_RUN.csv"
    with open(err_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "error"])
        w.writerows(img_errors)

    st.download_button("Scarica missing_codes.csv", data=miss_path.read_bytes(), file_name=miss_path.name, mime="text/csv")
    st.download_button("Scarica image_errors.csv", data=err_path.read_bytes(), file_name=err_path.name, mime="text/csv")

else:
    st.warning("Carica tutti e 3 i file nella sidebar, poi premi “Genera catalogo”.")