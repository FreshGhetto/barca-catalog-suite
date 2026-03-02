# BARCA – Catalog Suite (riordinato)

Obiettivo: un unico progetto pulito per:
1) **Parsing Excel di stagione** (report “Situazione Articoli per Negozio”) → `barca_db.csv`
2) **Generazione catalogo JPG** con foto + KPI + tabella taglie
3) **Export ZIP** dei JPG + report `missing_codes.csv` / `image_errors.csv`

> Nota: la cartella `vendor/parse_season_excel` contiene **copiati 1:1** i file che già funzionano.
> Non sono stati modificati (servono per il parse degli Excel).

---

## Struttura progetto

- `apps/streamlit_app.py` → app Streamlit nuova (drag&drop multipli, filtri, export zip)
- `src/barca_catalog/` → moduli nuovi, ordinati (loader DB, renderer card, wrapper immagini…)
- `vendor/parse_season_excel/` → i tuoi script funzionanti di parse Excel (NON TOCCATI)
- `legacy/` → file presi dal progetto vecchio (non necessari all’app nuova, ma usati per il fetch immagini)

---

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Avvio app:

```bash
streamlit run apps/streamlit_app.py
```

---

## Importante: fetch immagini

Il file legacy `legacy/barca_image_fetcher.py` dipende da `legacy/barca_catalog_generator.py`.

In questo ZIP ho messo **un placeholder** (`legacy/barca_catalog_generator.py`) che ti chiede di incollare il file vero dal progetto vecchio.

✅ Per far funzionare il download immagini:
- sostituisci `legacy/barca_catalog_generator.py` con la tua versione funzionante (o incolla dentro la logica corretta)

---

## Workflow consigliato

1) Tab/Step A: trascina 1+ Excel di stagione → genera `barca_db.csv`
2) Step B: trascina una o più liste codici (CSV) → genera JPG
3) Seleziona ordinamento e filtri (es. `%VEN`, `VEN`, ecc.) → scarica ZIP

---

## Idee utili già pronte (filtri/ordinamenti)

- ordinamento per `%VEN`, `VEN`, `CON`, `GIAC`, `Codice`
- filtro minimo su `VEN` e `CON`
- opzione “solo con immagine trovata”

Se vuoi, la prossima iterazione può aggiungere:
- **bucket per fasce %VEN** (Top seller / Medio / Lento)
- export aggiuntivo CSV “catalog_index.csv” con KPI e metadati
- template card per Uomo/Donna, branding, QR code, ecc.

---

## Quick start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run apps\streamlit_app.py
```

## Portable EXE (Windows)

See `docs/BUILD.md`.
