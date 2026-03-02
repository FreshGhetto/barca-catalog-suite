from __future__ import annotations

import io
import os
import time
import shutil
import zipfile
import uuid
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
import sys
from pathlib import Path as _Path

import streamlit as st

# --- project paths ---
PROJECT_ROOT = _Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# --- temp base (avoid Windows %TEMP% locks / antivirus scans)
TEMP_BASE = PROJECT_ROOT / ".barca_tmp"
TEMP_BASE.mkdir(parents=True, exist_ok=True)

def _purge_old_temp_runs(*, base: Path, older_than_hours: int = 24, also_system_temp: bool = True) -> int:
    """Remove old run folders (best-effort). Returns number of deleted folders."""
    deleted = 0
    cutoff = time.time() - older_than_hours * 3600

    def _purge_in(dir_path: Path, prefixes: tuple[str, ...]) -> None:
        nonlocal deleted
        if not dir_path.exists():
            return
        for p in dir_path.iterdir():
            if not p.is_dir():
                continue
            if not any(p.name.startswith(pref) for pref in prefixes):
                continue
            try:
                mtime = p.stat().st_mtime
            except Exception:
                mtime = 0
            if mtime and mtime > cutoff:
                continue
            try:
                shutil.rmtree(p, ignore_errors=True)
                deleted += 1
            except Exception:
                pass

    _purge_in(base, ("barca_run_", "barca_cards_"))
    if also_system_temp:
        try:
            sys_tmp = Path(tempfile.gettempdir())
            _purge_in(sys_tmp, ("barca_run_", "barca_cards_"))
        except Exception:
            pass
    return deleted

# Pulizia automatica all'avvio (non invasiva)
_purge_old_temp_runs(base=TEMP_BASE, older_than_hours=24)

from barca_catalog.io_codes import load_codes_csv
from barca_catalog.db_loader import load_articles_from_barca_db
from barca_catalog.image_provider import fetch_image_bytes
from barca_catalog.card_renderer import render_card
from barca_catalog.io_excel_convert import ensure_xlsx

# --- vendor loader (parse-season-excel untouched) ---
import importlib.util

VENDOR_PARSE = PROJECT_ROOT / "vendor" / "parse_season_excel"

def _load_vendor_parser():
    path = VENDOR_PARSE / "excel_parser.py"
    spec = importlib.util.spec_from_file_location("_vendor_excel_parser", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Impossibile caricare vendor excel_parser.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_vendor_excel_parser"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    if not hasattr(mod, "parse_situazione_articoli_excel"):
        raise RuntimeError("vendor excel_parser.py non contiene parse_situazione_articoli_excel")
    return mod

_vendor = _load_vendor_parser()
parse_situazione_articoli_excel = _vendor.parse_situazione_articoli_excel

st.set_page_config(page_title="BARCA – Catalog Suite", layout="wide")
st.title("BARCA – Catalog Suite")
st.caption(
    "Carica Excel di stagione + liste codici (CSV) → genera cataloghi JPG con foto e info. "
    "(La parte parse-season-excel rimane intoccata / vendor.)"
)

with st.expander("Che file devo caricare? (testo breve – poi lo cambi tu)", expanded=True):
    st.markdown(
        """
**1) Excel di stagione (.xlsx)**
- Export ‘Situazione Articoli per Negozio’ (uno o più file)
- Foglio: di default **0** (primo foglio)

**2) Liste codici (.csv)**
- Una o più liste con i codici articolo (una colonna o comunque rilevabile)

Poi premi **Genera DB** e **Genera Catalogo**.
        """
    )

def _zip_folder(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(folder)))
    return buf.getvalue()

def _write_uploads(uploaded_files, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for up in uploaded_files:
        # Scriviamo sempre su un path "nuovo" (anche se stesso nome) per evitare cache/lock strani.
        # Manteniamo però il nome originale per chiarezza.
        p = out_dir / up.name
        # Evita file-lock su Windows: scrittura esplicita + flush/fsync
        data = up.getvalue() if hasattr(up, "getvalue") else bytes(up.getbuffer())
        with open(p, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        # Alcuni antivirus/Windows Search possono "toccare" subito il file e bloccarlo un attimo.
        # Aspettiamo che il file sia effettivamente leggibile.
        _wait_until_readable(p)
        # Convert legacy .xls to .xlsx (in-place in temp run dir)
        try:
            p2 = ensure_xlsx(p)
            p = p2
        except Exception:
            # If conversion fails, keep original path; parser may still handle it or raise a clear error later.
            pass
        paths.append(p)
    return paths


def _write_single_upload(up, out_path: Path) -> Path:
    """Scrive un singolo UploadedFile su disco e attende che sia leggibile (Windows-safe)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = up.getvalue() if hasattr(up, "getvalue") else bytes(up.getbuffer())
    with open(out_path, "wb") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    _wait_until_readable(out_path)
    return out_path


def _wait_until_readable(path: Path, *, max_wait_s: float = 8.0) -> None:
    """Attende che un file sia apribile in lettura su Windows (evita WinError 32 intermittente)."""
    start = time.time()
    delay = 0.15
    while True:
        try:
            with open(path, "rb") as _:
                return
        except PermissionError:
            if time.time() - start > max_wait_s:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 1.2)
        except OSError as e:
            # tipico: "WinError 32" (file usato da un altro processo)
            if "WinError 32" in str(e):
                if time.time() - start > max_wait_s:
                    raise
                time.sleep(delay)
                delay = min(delay * 1.6, 1.2)
                continue
            raise


def _retry(call, *, tries: int = 12, delay_s: float = 0.25):
    """Retry robusto per errori intermittenti (WinError 32 / AV / indicizzazione Windows)."""
    last = None
    for i in range(tries):
        try:
            return call()
        except PermissionError as e:
            last = e
            if i < tries - 1:
                time.sleep(min(delay_s * (1.6 ** i), 3.0))
            else:
                raise
        except OSError as e:
            last = e
            if "WinError 32" in str(e) and i < tries - 1:
                time.sleep(min(delay_s * (1.6 ** i), 3.0))
                continue
            raise
    raise last  # pragma: no cover


def _make_run_dir(prefix: str) -> Path:
    """Create a run directory under project temp base (NOT system %TEMP%)."""
    run_dir = TEMP_BASE / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _cleanup_run_dir(run_dir: Path) -> None:
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception:
        pass

def _parse_excels_to_db_bytes(excel_files, sheet: str | int | None, *, keep_debug: bool) -> Tuple[bytes, Optional[Path]]:
    """
    Ritorna:
      - bytes del barca_db.csv
      - path della cartella debug (se keep_debug=True) altrimenti None
    """
    debug_dir: Optional[Path] = None

    run_dir = _make_run_dir("barca_run")
    try:
        inputs_dir = run_dir / "inputs"
        temp_convert_dir = run_dir / "temp_convert"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        temp_convert_dir.mkdir(parents=True, exist_ok=True)

        excel_paths = _write_uploads(excel_files, inputs_dir)

        frames = []
        for p in excel_paths:
            df = _retry(lambda: parse_situazione_articoli_excel(
                p,
                sheet=sheet if sheet not in ("", None) else 0,
                temp_convert_dir=temp_convert_dir,
            ))
            frames.append(df)

        db = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        db_bytes = db.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        if keep_debug:
            debug_dir = PROJECT_ROOT / "debug_runs" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            debug_dir.mkdir(parents=True, exist_ok=True)
            # copia input e temp (solo per debug)
            shutil.copytree(inputs_dir, debug_dir / "inputs", dirs_exist_ok=True)
            # salva db
            (debug_dir / "barca_db.csv").write_bytes(db_bytes)

        return db_bytes, debug_dir
    finally:
        if not keep_debug:
            _cleanup_run_dir(run_dir)

def _generate_cards_zip(db_bytes: bytes, codes_csv_files, *,
                        pasted_codes: List[str],
                        extra_codes: List[str],
                        filters_enabled: bool,
                        order_by: str,
                        min_vend_pct: float,
                        min_ven: float,
                        min_con: float,
                        only_with_image: bool,
                        only_in_stores: List[str],
                        exclude_stores: List[str],
                        filter_supplier: str,
                        filter_reparto: str,
                        filter_categoria: str,
                        filter_season: str,
                        keep_debug: bool,
                        progress_cb=None,
                        status_cb=None) -> Tuple[bytes, Optional[Path], dict]:
    """
    Produce zip bytes dei JPG + (opzionale) cartella debug + stats dict
    """
    debug_dir: Optional[Path] = None
    stats = {"total_codes": 0, "rendered": 0, "missing_images": 0}

    run_dir = _make_run_dir("barca_cards")
    try:
        out_cards = run_dir / "cards"
        out_cards.mkdir(parents=True, exist_ok=True)

        # Carica db da bytes (no file persistente)
        db_df = pd.read_csv(io.BytesIO(db_bytes), dtype=str, keep_default_na=False, encoding_errors="replace")
        articles = load_articles_from_barca_db(db_df)

        # Carica codici da una o più liste + incolla + ricerca
        codes_all: List[str] = []

        # 1) CSV caricati (tipicamente report 'Analisi Articoli' → parser robusto)
        for up in (codes_csv_files or []):
            csv_path = _write_single_upload(up, run_dir / "inputs" / up.name)
            codes_all.extend(load_codes_csv(csv_path))

        # 2) Codici incollati (estrazione regex)
        if pasted_codes:
            codes_all.extend([str(c).strip().upper() for c in pasted_codes if str(c).strip()])

        # 3) Codici extra da ricerca DB
        if extra_codes:
            codes_all.extend([str(c).strip().upper() for c in extra_codes if str(c).strip()])

        # de-dup preservando ordine
        seen = set()
        codes: List[str] = []
        for c in codes_all:
            if not c:
                continue
            if c in seen:
                continue
            seen.add(c)
            codes.append(c)

        stats["total_codes"] = len(codes)

        # Pre-calcola vend%: (VEN/CON)*100 (su totali)
        def vend_pct(a) -> float:
            try:
                con = float(a.con or 0)
                ven = float(a.ven or 0)
                if con <= 0:
                    return 0.0
                return (ven / con) * 100.0
            except Exception:
                return 0.0

        # Ordinamenti supportati
        def sort_key(a):
            if order_by == "%VEND":
                return vend_pct(a)
            if order_by == "VEN":
                return float(a.ven or 0)
            if order_by == "CON":
                return float(a.con or 0)
            if order_by == "GIA":
                return float(a.gia or 0)
            return a.code

        # Filtri meta (semplici: contains, case-insensitive)
        fs = (filter_supplier or "").strip().lower()
        fr = (filter_reparto or "").strip().lower()
        fc = (filter_categoria or "").strip().lower()
        fse = (filter_season or "").strip().lower()

        # Filtri negozi
        only_in = {s.strip().upper() for s in (only_in_stores or []) if s.strip()}
        excl = {s.strip().upper() for s in (exclude_stores or []) if s.strip()}

        def store_pass(a) -> bool:
            if not a.stores:
                return not only_in
            stores = set(a.stores.keys())
            if excl and stores.intersection(excl):
                return False
            if only_in:
                return bool(stores.intersection(only_in))
            return True

        # Risolvi Article per ogni code
        # - se filtri disattivati: ordine originale del DB
        # - se filtri attivi: filtri + ordinamento scelto
        resolved = []
        if not filters_enabled:
            want = set(codes)
            seen_codes = set()
            # ordine DB: prima occorrenza di ogni articolo nel CSV
            if "articolo" in db_df.columns:
                for raw in db_df["articolo"].astype(str).tolist():
                    c = raw.strip().upper().replace(" ", "")
                    if not c or c not in want or c in seen_codes:
                        continue
                    a = articles.get(c)
                    if a is None:
                        continue
                    resolved.append(a)
                    seen_codes.add(c)
            else:
                # fallback: ordine lista codici
                for c in codes:
                    a = articles.get(c)
                    if a is not None:
                        resolved.append(a)
        else:
            for c in codes:
                a = articles.get(c)
                if a is None:
                    continue
                if not store_pass(a):
                    continue
                if fs and fs not in (a.supplier or "").lower():
                    continue
                if fr and fr not in (a.reparto or "").lower():
                    continue
                if fc and fc not in (a.categoria or "").lower():
                    continue
                if fse and fse not in (a.season or "").lower():
                    continue
                if vend_pct(a) < min_vend_pct:
                    continue
                if float(a.ven or 0) < min_ven:
                    continue
                if float(a.con or 0) < min_con:
                    continue
                resolved.append(a)

            resolved.sort(key=sort_key, reverse=True if order_by != "CODE" else False)

        missing_report_lines: List[str] = []
        error_report_lines: List[str] = []

        total = max(len(resolved), 1)
        for idx, a in enumerate(resolved, start=1):
            if status_cb:
                try:
                    status_cb(f"{idx}/{len(resolved)} – {a.code}")
                except Exception:
                    pass
            if progress_cb:
                try:
                    progress_cb((idx - 1) / total, stats)
                except Exception:
                    pass

            try:
                img_bytes, err = fetch_image_bytes(a.code)
            except Exception as e:
                img_bytes, err = None, f"fetch_error:{type(e).__name__}:{e}"

            if (not img_bytes) and (filters_enabled and only_with_image):
                stats["missing_images"] += 1
                missing_report_lines.append(f"{a.code}\t{err or 'no_image'}")
                continue

            if not img_bytes:
                stats["missing_images"] += 1
                missing_report_lines.append(f"{a.code}\t{err or 'no_image'}")

            try:
                card = render_card(a, img_bytes)
                out_name = f"{idx:04d}_{a.code.replace('/','_')}.jpg"
                out_path = out_cards / out_name
                card.save(out_path, "JPEG", quality=95, subsampling=0, optimize=True)
                stats["rendered"] += 1
            except Exception as e:
                # errore silenzioso: log e continua
                error_report_lines.append(f"{a.code}\t{type(e).__name__}\t{e}")
                continue

        if progress_cb:
            try:
                progress_cb(1.0, stats)
            except Exception:
                pass

        # report missing
        (out_cards / "_missing_images.txt").write_text("\n".join(missing_report_lines), encoding="utf-8")
        (out_cards / "_errors.txt").write_text("\n".join(error_report_lines), encoding="utf-8")

        zip_bytes = _zip_folder(out_cards)

        if keep_debug:
            debug_dir = PROJECT_ROOT / "debug_runs" / f"cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "barca_db.csv").write_bytes(db_bytes)
            # salva liste caricate
            lists_dir = debug_dir / "lists"
            lists_dir.mkdir(parents=True, exist_ok=True)
            for up in codes_csv_files:
                (lists_dir / up.name).write_bytes(up.getbuffer())
            # salva output
            shutil.copytree(out_cards, debug_dir / "cards", dirs_exist_ok=True)

        return zip_bytes, debug_dir, stats
    finally:
        if not keep_debug:
            _cleanup_run_dir(run_dir)


# ---------------- UI ----------------
with st.sidebar:
    st.header("Input")

    st.subheader("1) Excel stagione (drag & drop)")
    excel_files = st.file_uploader("Carica uno o più Excel (.xlsx / .xls)", type=["xlsx", "xls"], accept_multiple_files=True)
    sheet = st.text_input("Sheet (index o nome)", value="0", help="Default: 0 (prima sheet). Puoi scrivere anche un nome.")

    st.subheader("2) Liste codici (CSV)")
    codes_lists = st.file_uploader("Carica una o più liste codici (.csv)", type=["csv"], accept_multiple_files=True)

    st.subheader("(Opzionale) Avvio rapido")
    auto_run = st.checkbox("Auto-run quando DB e liste sono pronti", value=False,
                           help="Se attivo: dopo ‘Genera DB’ e con liste caricate, parte in automatico la generazione ZIP.")

    with st.expander("Debug & Temp", expanded=False):
        keep_debug = st.checkbox("Debug: conserva i file di run (altrimenti tutto in temp e si elimina)", value=False)
        col_tmp1, col_tmp2 = st.columns([1,1])
        with col_tmp1:
            if st.button("Pulisci temp", help="Cancella vecchie cartelle barca_run_* / barca_cards_* (best-effort)."):
                n = _purge_old_temp_runs(base=TEMP_BASE, older_than_hours=0, also_system_temp=True)
                st.success(f"Temp pulito (cartelle eliminate: {n}).")
        with col_tmp2:
            st.caption(f"Temp base: {TEMP_BASE.name}")
st.divider()

# ---- FILTRI / OPZIONI (principali, in schermata) ----
st.subheader("Opzioni catalogo")

# ---- FILTRI & ORDINAMENTI (collassabile) ----
# Default: tutto disattivato, tendina chiusa (ordine originale DB).
filters_enabled = st.session_state.get("filters_enabled", False)

with st.expander("Filtri e ordinamenti (opzionale)", expanded=False):
    filters_enabled = st.checkbox(
        "Attiva filtri e ordinamenti",
        value=filters_enabled,
        key="filters_enabled",
        help="Se disattivo: nessun filtro / nessun ordinamento → ordine originale del DB.",
    )

    if not filters_enabled:
        st.info("Modalità: **ordine originale del DB**")
    else:
        st.success("Modalità: **filtri attivi**")

    opt1, opt2, opt3, opt4 = st.columns([1.2, 1.2, 1.2, 1.2], gap="medium")
    with opt1:
        order_by = st.selectbox(
            "Ordina per",
            ["%VEND", "VEN", "CON", "GIAC", "CODE"],
            index=0,
            disabled=not filters_enabled,
        )
        only_with_image = st.checkbox(
            "Solo articoli con immagine trovata",
            value=False,
            disabled=not filters_enabled,
            help="Esclude gli articoli che non trovano nessuna foto.",
        )
    with opt2:
        min_vend_pct = st.slider(
            "Min %VEND (VEN/CON)",
            0.0, 200.0, 0.0, 1.0,
            disabled=not filters_enabled,
        )
        min_ven = st.number_input(
            "Min VEN",
            min_value=0.0,
            value=0.0,
            step=1.0,
            disabled=not filters_enabled,
        )
    with opt3:
        min_con = st.number_input(
            "Min CON",
            min_value=0.0,
            value=0.0,
            step=1.0,
            disabled=not filters_enabled,
        )
        filter_season = st.text_input(
            "Filtro stagione (contiene)",
            value="",
            disabled=not filters_enabled,
        )
    with opt4:
        filter_supplier = st.text_input(
            "Filtro fornitore (contiene)",
            value="",
            disabled=not filters_enabled,
        )
        filter_reparto = st.text_input(
            "Filtro reparto (contiene)",
            value="",
            disabled=not filters_enabled,
        )
        filter_categoria = st.text_input(
            "Filtro categoria (contiene)",
            value="",
            disabled=not filters_enabled,
        )

    st.caption("Tip: i filtri ‘contiene’ non sono case-sensitive. Esempio: ‘donna’, ‘uomo’, ‘barca’, ‘25I’.")

    store_col1, store_col2 = st.columns(2, gap="medium")
    with store_col1:
        only_in_stores_raw = st.text_input(
            "Solo questi negozi (codici separati da virgola)",
            value="",
            help="Esempio: AR, M4, SPW. Se vuoto = tutti.",
            disabled=not filters_enabled,
        )
    with store_col2:
        exclude_stores_raw = st.text_input(
            "Escludi questi negozi (codici separati da virgola)",
            value="",
            help="Esempio: XX per escludere il totale, o negozi specifici.",
            disabled=not filters_enabled,
        )

# Se filtri disattivi, settiamo valori di default “neutri”
if not filters_enabled:
    order_by = "CODE"
    only_with_image = False
    min_vend_pct = 0.0
    min_ven = 0.0
    min_con = 0.0
    filter_season = ""
    filter_supplier = ""
    filter_reparto = ""
    filter_categoria = ""
    only_in_stores_raw = ""
    exclude_stores_raw = ""

def _split_codes(s: str) -> List[str]:
    return [x.strip().upper() for x in (s or "").split(",") if x.strip()]

only_in_stores = _split_codes(only_in_stores_raw)
exclude_stores = _split_codes(exclude_stores_raw)

colA, colB = st.columns(2, gap="large")

with colA:
    st.subheader("A) Genera DB (barca_db.csv) dagli Excel")
    if st.button("Genera barca_db.csv", type="primary", disabled=not excel_files):
        try:
            db_bytes, dbg = _parse_excels_to_db_bytes(excel_files, sheet, keep_debug=keep_debug)
            st.session_state["db_bytes"] = db_bytes
            # reset cached search df (new DB)
            st.session_state["db_search_df"] = None
            st.success("DB generato ✅")
            st.download_button("Scarica barca_db.csv", data=db_bytes, file_name="barca_db.csv", mime="text/csv")
            if dbg:
                st.info(f"Debug run salvata in: {dbg}")
        except Exception as e:
            st.error(f"Errore parse Excel: {type(e).__name__} – {e}")

    if "db_bytes" in st.session_state:
        st.caption("DB in memoria: pronto per generare cards (nessun file persistente se Debug è off).")

with colB:
    st.subheader("B) Genera catalogo JPG (ZIP)")

    # ---- SELEZIONE CODICI (extra) ----
    with st.expander("Selezione codici (opzionale): incolla codici + ricerca nel DB", expanded=False):
        st.caption("Puoi combinare: liste CSV caricate + codici incollati + codici trovati con ricerca nel DB. Tutti i codici hanno '/' e vengono deduplicati.")

        pasted = st.text_area(
            "Incolla codici (uno per riga o separati da spazio/virgola/;)",
            value=st.session_state.get("pasted_codes_text", ""),
            height=120,
            key="pasted_codes_text",
        )

        import re as _re
        _CODE_RE = _re.compile(r"\b\d{1,3}/[A-Z0-9]{2,}\b", _re.IGNORECASE)

        def _extract_codes_from_text(_t: str):
            return [m.group(0).upper() for m in _CODE_RE.finditer(_t or "")]

        pasted_codes = _extract_codes_from_text(pasted)
        if pasted_codes:
            st.success(f"✅ Hai già inserito **{len(pasted_codes)}** codici incollati. Puoi generare lo ZIP subito.")

        # Pulsante rapido: genera ZIP usando i codici già inseriti (opzionale)

        q = st.text_input(
            "Cerca nel DB (codice o descrizione contiene)",
            value=st.session_state.get("db_search_text", ""),
            key="db_search_text",
            help="Esempio: 'sneaker', 'TSAKIRIS', 'stivale'... Aggiunge i codici che matchano.",
        )

        colx1, colx2, colx3 = st.columns([1, 1, 1])
        with colx1:
            add_from_search = st.button("Aggiungi risultati ricerca (opzionale)", use_container_width=True)
        with colx2:
            clear_extra = st.button("Svuota codici extra", use_container_width=True)
        with colx3:
            show_extra = st.checkbox("Mostra anteprima codici extra", value=False)

        if "extra_codes" not in st.session_state:
            st.session_state["extra_codes"] = []

        # search in DB
        if add_from_search:
            if "db_bytes" not in st.session_state:
                st.warning("Prima genera o carica il DB dagli Excel.")
            else:
                try:
                    db_search_df = st.session_state.get("db_search_df")
                    if db_search_df is None:
                        db_search_df = pd.read_csv(
                            io.BytesIO(st.session_state["db_bytes"]),
                            dtype=str,
                            keep_default_na=False,
                            encoding_errors="replace",
                        )
                        db_search_df.columns = [str(c).strip().lower() for c in db_search_df.columns]
                        if "code" not in db_search_df.columns and "articolo" in db_search_df.columns:
                            db_search_df["code"] = db_search_df["articolo"]
                        if "code" in db_search_df.columns:
                            db_search_df["code"] = (
                                db_search_df["code"].astype(str).str.strip().str.upper().str.replace(" ", "", regex=False)
                            )
                        st.session_state["db_search_df"] = db_search_df

                    qq = (q or "").strip()
                    if not qq:
                        st.warning("Inserisci una ricerca.")
                    else:
                        qq_low = qq.lower()
                        cols = [
                            c
                            for c in [
                                "code",
                                "product",
                                "description",
                                "fornitore",
                                "supplier",
                                "reparto",
                                "categoria",
                                "season",
                            ]
                            if c in db_search_df.columns
                        ]
                        mask = None
                        for c in cols:
                            ser = db_search_df[c].astype(str).str.lower().str.contains(qq_low, na=False)
                            mask = ser if mask is None else (mask | ser)
                        hits = db_search_df[mask] if mask is not None else db_search_df.iloc[0:0]
                        found = []
                        if "code" in hits.columns:
                            found = [str(x).strip().upper() for x in hits["code"].tolist()]
                        found = [x for x in found if _CODE_RE.search(x)]

                        before = len(st.session_state["extra_codes"])
                        st.session_state["extra_codes"] = list(dict.fromkeys(st.session_state["extra_codes"] + found))
                        st.success(
                            f"Aggiunti {len(st.session_state['extra_codes']) - before} codici dalla ricerca (trovati: {len(found)})."
                        )
                except Exception as e:
                    st.error(f"Errore ricerca DB: {type(e).__name__} – {e}")

        if clear_extra:
            st.session_state["extra_codes"] = []
            st.success("Codici extra svuotati.")

        if show_extra:
            st.write(st.session_state["extra_codes"][:200])
            if len(st.session_state["extra_codes"]) > 200:
                st.caption(f"... +{len(st.session_state['extra_codes']) - 200} altri")
    pasted_codes_now = []
    try:
        import re as _re
        _CODE_RE2 = _re.compile(r"\b\d{1,3}/[A-Z0-9]{2,}\b", _re.IGNORECASE)
        pasted_codes_now = [m.group(0).upper() for m in _CODE_RE2.finditer(st.session_state.get("pasted_codes_text","") or "")]
    except Exception:
        pasted_codes_now = []
    extra_codes_now = st.session_state.get("extra_codes", []) or []
    ready = ("db_bytes" in st.session_state) and (bool(codes_lists) or bool(pasted_codes_now) or bool(extra_codes_now))

    run_btn = st.button("Genera ZIP JPG", type="primary", disabled=not ready)
    if (auto_run and ready) or run_btn or st.session_state.pop('force_generate_zip', False):
        try:
            prog = st.progress(0.0)
            status = st.empty()

            def _p(frac, stats):
                prog.progress(min(max(float(frac), 0.0), 1.0))
                status.info(
                    f"Generazione… cards: {stats.get('rendered',0)} | missing img: {stats.get('missing_images',0)}"
                )

            def _s(msg: str):
                status.info(msg)

            zip_bytes, dbg, stats = _generate_cards_zip(
                st.session_state["db_bytes"], codes_lists,
                pasted_codes=pasted_codes_now,
                extra_codes=extra_codes_now,
                filters_enabled=filters_enabled,
                order_by=order_by,
                min_vend_pct=min_vend_pct,
                min_ven=min_ven,
                min_con=min_con,
                only_with_image=only_with_image,
                only_in_stores=only_in_stores,
                exclude_stores=exclude_stores,
                filter_supplier=filter_supplier,
                filter_reparto=filter_reparto,
                filter_categoria=filter_categoria,
                filter_season=filter_season,
                keep_debug=keep_debug,
                progress_cb=_p,
                status_cb=_s,
            )
            st.session_state["cards_zip"] = zip_bytes
            st.session_state["cards_stats"] = stats
            prog.progress(1.0)
            status.success(
                f"Finito ✅  (cards: {stats.get('rendered',0)} | missing img: {stats.get('missing_images',0)} | codici: {stats.get('total_codes',0)})"
            )
            st.success("Catalogo generato ✅")
            if dbg:
                st.info(f"Debug run salvata in: {dbg}")
        except Exception as e:
            st.error(f"Errore generazione cards: {type(e).__name__} – {e}")

    if "cards_zip" in st.session_state:
        stats = st.session_state.get("cards_stats", {})
        st.write(f"Codici in lista: **{stats.get('total_codes', 0)}**  |  "
                 f"Cards create: **{stats.get('rendered', 0)}**  |  "
                 f"Immagini mancanti: **{stats.get('missing_images', 0)}**")
        st.download_button("Scarica ZIP JPG", data=st.session_state["cards_zip"],
                           file_name="barca_catalog_cards.zip", mime="application/zip")

st.divider()
st.caption("Nota: se Debug è disattivo, input/output vengono gestiti in cartelle temporanee e cancellati subito dopo la generazione.")