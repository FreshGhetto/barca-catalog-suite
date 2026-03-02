import re
import io
from typing import List, Dict, Optional, Tuple
import pandas as pd

# -------------------------
# Encoding / line utilities
# -------------------------

def decode_best_effort(data: bytes) -> str:
    for enc in ["utf-8", "utf-8-sig", "cp1252", "latin1"]:
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("latin1", errors="replace")


def iter_balanced_lines(text: str):
    """
    Unisce righe finché il numero di virgolette non è pari.
    Utile quando l'export ha newline dentro ai campi.
    """
    buf = ""
    for line in text.splitlines():
        buf = buf + ("\n" if buf else "") + line
        if buf.count('"') % 2 == 0:
            yield buf
            buf = ""
    if buf:
        yield buf


def extract_quoted_fields(line: str) -> List[str]:
    # CSV "strano" con tutto tra virgolette: estrae i campi "..."
    return re.findall(r'"([^"]*)"', line)


# -------------------------
# Heuristics / parsing
# -------------------------

# Es: 59/0642CTM, 10/ABC123, 9/XX
_CODE_RE = re.compile(r'^\d{1,3}/[A-Z0-9]{2,}', re.IGNORECASE)

# Reparto/Categoria nel report Barca tipicamente sono: "SD  SCARPE DONNA", "ST  STIVALE TACCO"
_REPARTO_RE = re.compile(r'^[A-Z]{1,3}\s{1,}\S', re.IGNORECASE)

def _looks_like_reparto_or_categoria(x: str) -> bool:
    s = (x or "").strip()
    if not s:
        return False
    # IMPORTANTISSIMO: deve iniziare con lettere (non numeri), altrimenti scambiamo fornitori tipo "908 R GROUP"
    if s[0].isdigit():
        return False
    return bool(_REPARTO_RE.match(s))


def _looks_like_supplier(x: str) -> bool:
    s = (x or "").strip()
    if not s:
        return False
    # sigle societarie comuni
    if re.search(r'\bS\.?R\.?L\.?\b|\bS\.?P\.?A\.?\b|\bS\.?A\.?S\.?\b|\bS\.?N\.?C\.?\b', s, re.IGNORECASE):
        return True
    # molti fornitori iniziano con un codice numerico + nome
    if re.match(r'^\d+\s+\S', s):
        return True
    # fallback: stringa abbastanza lunga e non numero puro
    if len(s) >= 6 and not s.isdigit():
        return True
    return False


def _find_articolo_label_idx(text: str) -> Optional[int]:
    """
    Trova l'indice del campo che contiene il label 'ARTICOLO' nell'intestazione del report.
    Gestisce varianti tipo "Articolo", "ARTICOLO ", "COD. ARTICOLO", ecc.
    """
    for line in iter_balanced_lines(text):
        f = extract_quoted_fields(line)
        if not f:
            continue
        for i, v in enumerate(f):
            up = (v or "").strip().upper()
            if up == "ARTICOLO" or "ARTICOLO" in up:
                return i
    return None


def _try_read_already_clean_csv(data: bytes) -> Optional[pd.DataFrame]:
    """
    Se l'utente carica già un CSV pulito (con header code/product/...), lo riconosce e lo restituisce.
    """
    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception:
        return None

    cols = {c.strip().lower() for c in df.columns}
    must = {"code", "product", "consegnate", "vendute", "giacenza"}
    if not must.issubset(cols):
        return None

    # normalizza nomi colonne e tipi
    rename = {c: c.strip() for c in df.columns}
    df = df.rename(columns=rename)

    for c in ["ordinato", "consegnate", "vendute", "giacenza"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    for c in ["perc_venduto", "perc_venduto_calc", "prz_acq", "prz_vend", "valore_netto"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def clean_anart_report_bytes(data: bytes, strict: bool = True, debug: bool = False) -> pd.DataFrame:
    """
    Parser robusto per export 'ANALISI ARTICOLI' (report impaginato) Barca.

    Output:
      reparto, categoria, fornitore, code, product,
      ordinato, consegnate, vendute, giacenza,
      perc_venduto (letta dal report),
      perc_venduto_calc (controllo),
      prz_acq, prz_vend, valore_netto
    """
    # 0) se è già un csv pulito, non riparsare
    already = _try_read_already_clean_csv(data)
    if already is not None:
        return already

    text = decode_best_effort(data)
    art_label_idx = _find_articolo_label_idx(text)  # può essere None: ok

    last_reparto = ""
    last_categoria = ""
    last_fornitore = ""

    out: List[Dict] = []
    skipped: List[Tuple[str, List[str]]] = []

    def process_fields(fields: List[str]):
        nonlocal last_reparto, last_categoria, last_fornitore, out, skipped

        if not fields:
            return

        # Se abbiamo art_label_idx ed il campo corrisponde ad "ARTICOLO", prendiamo la coda dopo il label.
        # Altrimenti lavoriamo su tutti i campi (fallback).
        after = fields
        if art_label_idx is not None and len(fields) > art_label_idx:
            if (fields[art_label_idx] or "").strip().upper() == "ARTICOLO":
                after = fields[art_label_idx + 1:]
            else:
                return

        # 1) trova il campo articolo (primo campo che inizia con codice)
        art_rel = None
        art_full = None
        for k, field in enumerate(after[:30]):
            s = (field or "").strip()
            if not s:
                continue
            m = re.match(r'^(\d{1,3}/[A-Z0-9]{2,})\b', s, re.IGNORECASE)
            if m:
                art_rel = k
                art_full = s
                break

        if art_rel is None or art_full is None:
            if art_label_idx is not None:
                skipped.append(("no_article", after))
            return

        ctx = after[:art_rel]

        # 2) stato contesto
        reparto = last_reparto
        categoria = last_categoria
        fornitore = last_fornitore

        # reparto/categoria: tipicamente i primi 2 campi "SD ...", "ST ..."
        repcat = [c.strip() for c in ctx if _looks_like_reparto_or_categoria(c)]
        if repcat:
            if len(repcat) >= 1:
                reparto = repcat[0]
            if len(repcat) >= 2:
                categoria = repcat[1]
            last_reparto, last_categoria = reparto, categoria

        # fornitore: ultimo candidato nel contesto
        sup_candidates = [c.strip() for c in ctx if _looks_like_supplier(c)]
        if sup_candidates:
            fornitore = sup_candidates[-1]
            last_fornitore = fornitore

        # 3) code + descr (nel report stanno nello stesso campo)
        m = re.match(r'^(\d{1,3}/[A-Z0-9]{2,})\s*(.*)$', art_full.strip(), re.IGNORECASE)
        code = m.group(1).strip() if m else art_full.split()[0].strip()
        descr = (m.group(2) if m else " ".join(art_full.split()[1:])).strip()

        # 4) numeri dopo l'articolo
        rest = after[art_rel + 1:]

        num_positions: List[Tuple[int, float]] = []
        pct_idx = None
        for i, field in enumerate(rest):
            s = (field or "").strip()
            if not s:
                continue
            if s == "%":
                if pct_idx is None:
                    pct_idx = i
                continue
            s2 = s.replace(",", ".")
            if re.fullmatch(r"-?\d+(\.\d+)?", s2):
                try:
                    num_positions.append((i, float(s2)))
                except Exception:
                    pass

        qty_block: List[float] = []
        post_block: List[float] = []

        if pct_idx is not None:
            nums_before = [v for (i, v) in num_positions if i < pct_idx]
            nums_after = [v for (i, v) in num_positions if i > pct_idx]
            # nel report: ordinato, consegnate, vendute, giacenza, perc
            if len(nums_before) >= 5:
                qty_block = nums_before[-5:]
            post_block = nums_after[:6]
        else:
            nums = [v for (_, v) in num_positions[:12]]
            if len(nums) >= 5:
                qty_block = nums[:5]
                post_block = nums[5:]

        if len(qty_block) < 4:
            if art_label_idx is not None:
                skipped.append(("few_nums", after))
            return

        ordinato = int(qty_block[0]) if len(qty_block) > 0 else 0
        consegnate = int(qty_block[1]) if len(qty_block) > 1 else 0
        vendute = int(qty_block[2]) if len(qty_block) > 2 else 0
        giacenza = int(qty_block[3]) if len(qty_block) > 3 else 0
        perc_venduto = float(qty_block[4]) if len(qty_block) > 4 else None

        prz_acq = float(post_block[0]) if len(post_block) > 0 else None
        prz_vend = float(post_block[1]) if len(post_block) > 1 else None
        valore_netto = float(post_block[2]) if len(post_block) > 2 else None

        perc_calc = None
        if consegnate and consegnate > 0:
            perc_calc = round((vendute / consegnate) * 100, 2)

        out.append({
            "reparto": reparto,
            "categoria": categoria,
            "fornitore": fornitore,
            "code": code,
            "product": descr if descr else None,
            "ordinato": ordinato,
            "consegnate": consegnate,
            "vendute": vendute,
            "giacenza": giacenza,
            "perc_venduto": perc_venduto,
            "perc_venduto_calc": perc_calc,
            "prz_acq": prz_acq,
            "prz_vend": prz_vend,
            "valore_netto": valore_netto,
        })

    for line in iter_balanced_lines(text):
        f = extract_quoted_fields(line)
        if f:
            process_fields(f)
        else:
            raw = line.strip()
            if not raw:
                continue
            for sep in [",", ";", "\t"]:
                if sep in raw:
                    parts = [p.strip().strip('"') for p in raw.split(sep)]
                    if any(_CODE_RE.match((p.split()[0] if p.split() else "")) for p in parts if p):
                        process_fields(parts)
                    break

    df = pd.DataFrame(out)

    if df.empty:
        if strict:
            raise ValueError("Non sono riuscito a estrarre righe articolo dal CSV/report.")
        return df

    # Fallback product: se manca descrizione, usa il codice (ma solo in quel caso)
    df["product"] = df["product"].fillna(df["code"])

    # Dedup
    df = df.drop_duplicates(subset=["code", "fornitore", "reparto", "categoria", "consegnate", "vendute", "giacenza"], keep="first")

    # Validazione codici attesi
    expected_codes = set(re.findall(_CODE_RE, text))
    extracted_codes = set(df["code"].astype(str).str.strip().str.upper())
    if expected_codes:
        expected_codes_up = {c.strip().upper() for c in expected_codes}
        missing = sorted(expected_codes_up - extracted_codes)
        if strict and missing:
            sample = ", ".join(missing[:15])
            raise ValueError(f"Mancano {len(missing)} codici articolo nell'output. Esempi: {sample}")

    if debug:
        print(f"[DEBUG] Extracted rows: {len(df)}; Suppliers: {df['fornitore'].nunique()}")

    return df


def clean_anart_report_path(path: str, strict: bool = True, debug: bool = False) -> pd.DataFrame:
    with open(path, "rb") as f:
        return clean_anart_report_bytes(f.read(), strict=strict, debug=debug)
