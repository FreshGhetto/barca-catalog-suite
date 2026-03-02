import os
import re
import io
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple
from urllib.parse import urlparse, urlunparse

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# CONFIG
# ============================================================

INPUT_CSV = r"C:\PythonEnvs\_Envs\ml_env\LAB\Barca Product Image Automation\data\clean_TSAKIRIS.csv"
CSV_SEP = ","
CSV_ENCODING = "utf-8-sig"

OUT_DIR = r"output_images"
SUPPLIER_NAME = "TSAKIRIS"

# --- FORMATO: A6 @ 300dpi (perfetto per 4 su A4)
CANVAS_W = 1240
CANVAS_H = 1748

# Suddivisione verticale:
# - foto grande sopra
# - box info sotto
PHOTO_H = 1120

# Margini / spessori
MARGIN = 40
BORDER_W = 6
INFO_BORDER_W = 8

# Qualità output JPG
JPG_QUALITY = 95
JPG_SUBSAMPLING = 0  # 0 = migliore qualità

# NON confondere VEN con VEND: usiamo VEND e NON stampiamo VEN
PRINT_CON = True
PRINT_GIA = True

SORT_BY = "valore_netto"   # oppure None
SORT_DESC = True

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

HTTP_TIMEOUT = 20
RETRY = 2
SLEEP_BETWEEN = 0.05

# Se xl_5 non esiste prova anche queste viste
PREFER_XL_ORDER = (5, 2, 1, 3, 4, 6, 7, 8, 9)

# Se True: nel box foto scrive anche il motivo del missing
SHOW_MISSING_REASON_ON_CARD = True


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class Item:
    code: str
    product: str
    con: Optional[int]
    gia: Optional[int]
    prz_acq: Optional[float]
    prz_vend: Optional[float]
    valore_netto: Optional[float]
    sconto_pct: Optional[int] = None
    image_url: Optional[str] = None
    image_bytes: Optional[bytes] = None
    image_err: Optional[str] = None  # <-- FIX: memorizza motivo mancanza


# ============================================================
# HELPERS
# ============================================================

def safe_int(x) -> Optional[int]:
    try:
        if pd.isna(x): return None
        s = str(x).strip()
        if not s: return None
        return int(float(s.replace(",", ".")))
    except Exception:
        return None

def safe_float(x) -> Optional[float]:
    try:
        if pd.isna(x): return None
        s = str(x).strip()
        if not s: return None
        return float(s.replace(",", "."))
    except Exception:
        return None

def code_to_media_prefix(code: str) -> str:
    return code.strip().replace("/", "_")

def strip_query(url: str) -> str:
    pu = urlparse(url)
    return urlunparse((pu.scheme, pu.netloc, pu.path, "", "", ""))

def decache_magento(url: str) -> str:
    url = url.replace("\\/", "/")
    url = strip_query(url)
    url = re.sub(r"(/media/catalog/product)/cache/[^/]+/", r"\1/", url)
    return url

def is_image_response(resp: requests.Response) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return "image/" in ctype

def is_barca_placeholder(img_bytes: bytes) -> bool:
    # placeholder molto uniforme => varianza bassa
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        small = im.resize((90, 90))
        px = list(small.getdata())
        gray = [(r + g + b) // 3 for r, g, b in px]
        mean = sum(gray) / len(gray)
        var = sum((x - mean) ** 2 for x in gray) / len(gray)
        return var < 180
    except Exception:
        return False

def download_bytes(session: requests.Session, url: str) -> Optional[bytes]:
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
        "Referer": "https://www.barcastores.com/"
    }
    for _ in range(RETRY + 1):
        try:
            r = session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code == 200 and r.content and is_image_response(r):
                return r.content
        except Exception:
            pass
        time.sleep(0.2)
    return None

def build_candidate_image_urls(code: str, xl_num: int) -> List[str]:
    prefix = code_to_media_prefix(code)
    filename = f"{prefix}-xl_{xl_num}.jpg"
    filename_alt1 = f"{prefix}-xl_{xl_num}_1.jpg"
    filename_alt2 = f"{prefix}-xl_{xl_num}_2.jpg"

    bases = [
        "https://www.barcastores.com/media/",
        "https://www.barcastores.com/media/catalog/product/",
        "https://www.barcastores.com/media/catalog/product/cache/",
        "https://www.barcastores.com/media/catalog/product/cache/1/",
        "https://www.barcastores.com/media/catalog/product/cache/2/",
        "https://www.barcastores.com/media/catalog/product/cache/3/",
    ]

    cands = []
    for base in bases:
        cands.append(decache_magento(base + filename))
        cands.append(decache_magento(base + filename_alt1))
        cands.append(decache_magento(base + filename_alt2))

        a = prefix[0].lower()
        b2 = prefix[1].lower() if len(prefix) > 1 else "x"
        cands.append(decache_magento(f"{base}{a}/{b2}/{filename}"))
        cands.append(decache_magento(f"{base}{a}/{b2}/{filename_alt1}"))
        cands.append(decache_magento(f"{base}{a}/{b2}/{filename_alt2}"))

    out = []
    seen = set()
    for u in cands:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def fetch_best_image_for_code(session: requests.Session, code: str) -> Tuple[Optional[str], Optional[bytes], Optional[str]]:
    """
    Ritorna: (url, bytes, err_reason)
    err_reason è sempre compilato se non trova nulla.
    """
    last_err = "no_direct_xl_image_found"
    for xl in PREFER_XL_ORDER:
        for u in build_candidate_image_urls(code, xl):
            b = download_bytes(session, u)
            if not b:
                last_err = "download_failed_or_not_image"
                continue
            if is_barca_placeholder(b):
                last_err = "placeholder_detected"
                continue
            return u, b, None
    return None, None, last_err


# ============================================================
# RENDER (NO UPSCALE)
# ============================================================

def load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\segoeui.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()

# Font più grandi e leggibili per A6
FONT_H1 = load_font(62)   # codice / rank
FONT_H2 = load_font(40)   # descrizione / prezzi
FONT_TXT = load_font(42)  # CON / GIA
FONT_MISS = load_font(28) # motivo missing

def paste_no_upscale(base: Image.Image, img: Image.Image, box: Tuple[int, int, int, int]):
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    iw, ih = img.size

    # MAI upscaling
    scale = min(bw / iw, bh / ih, 1.0)
    if scale < 1.0:
        img = img.resize((int(iw * scale), int(ih * scale)), Image.Resampling.LANCZOS)

    px = x1 + (bw - img.size[0]) // 2
    py = y1 + (bh - img.size[1]) // 2
    base.paste(img, (px, py))

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = (text or "").split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def draw_missing_block(d: ImageDraw.ImageDraw, code: str, reason: Optional[str]):
    d.text((MARGIN, MARGIN), "MISSING IMAGE", fill="black", font=FONT_H1)
    d.text((MARGIN, MARGIN + 85), code, fill="black", font=FONT_H2)
    if SHOW_MISSING_REASON_ON_CARD and reason:
        d.text((MARGIN, MARGIN + 140), reason, fill="black", font=FONT_MISS)

def draw_final_jpg(item: Item, rank: int) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    d = ImageDraw.Draw(canvas)

    # bordo esterno
    d.rectangle([BORDER_W, BORDER_W, CANVAS_W - BORDER_W, CANVAS_H - BORDER_W], outline="black", width=BORDER_W)

    # box foto
    photo_box = (MARGIN, MARGIN, CANVAS_W - MARGIN, PHOTO_H)
    if item.image_bytes:
        try:
            im = Image.open(io.BytesIO(item.image_bytes)).convert("RGB")
            paste_no_upscale(canvas, im, photo_box)
        except Exception:
            draw_missing_block(d, item.code, "image_decode_failed")
    else:
        draw_missing_block(d, item.code, item.image_err or "no_image")

    # box info sotto
    info_top = PHOTO_H + 20
    info_box = (MARGIN, info_top, CANVAS_W - MARGIN, CANVAS_H - MARGIN)
    d.rectangle(info_box, outline="black", width=INFO_BORDER_W)

    xL = MARGIN + 22
    xR = CANVAS_W // 2 + 10
    y = info_top + 18

    # riga titolo (rank + codice)
    d.text((xL, y), f"#{rank:03d}   {item.code}", fill="black", font=FONT_H1)
    y += 70

    # descrizione (max 2 righe)
    desc = (item.product or "").strip().upper()
    maxw = (CANVAS_W - 2 * MARGIN - 44)
    lines = wrap_text(d, desc, FONT_H2, maxw)[:2]
    for ln in lines:
        d.text((xL, y), ln, fill="black", font=FONT_H2)
        y += 48
    y += 10

    # sinistra: CON + GIA
    yL = y
    if PRINT_CON and item.con is not None:
        d.text((xL, yL), f"CON {item.con}", fill="black", font=FONT_TXT)
        yL += 58
    if PRINT_GIA and item.gia is not None:
        d.text((xL, yL), f"GIA {item.gia}", fill="black", font=FONT_TXT)
        yL += 58

    # destra: prezzi
    yR = y
    if item.prz_acq is not None:
        d.text((xR, yR), f"ACQ {item.prz_acq:.2f}", fill="black", font=FONT_H2); yR += 48
    if item.prz_vend is not None:
        d.text((xR, yR), f"VEND {item.prz_vend:.2f}", fill="black", font=FONT_H2); yR += 48
    if item.sconto_pct is not None:
        d.text((xR, yR), f"SCONTO {item.sconto_pct}%", fill="black", font=FONT_H2); yR += 48
    if item.valore_netto is not None:
        d.text((xR, yR), f"VALORE NETTO {item.valore_netto:.2f}", fill="black", font=FONT_H2); yR += 48

    return canvas


# ============================================================
# CSV LOADER
# ============================================================

def load_items_clean_csv(path: str) -> List[Item]:
    df = pd.read_csv(path, sep=CSV_SEP, encoding=CSV_ENCODING)

    items: List[Item] = []
    for _, row in df.iterrows():
        code = str(row.get("code", "")).strip()
        if not code:
            continue

        it = Item(
            code=code,
            product=str(row.get("product", "")).strip(),
            con=safe_int(row.get("con")),
            gia=safe_int(row.get("gia")),
            prz_acq=safe_float(row.get("prz_acq")),
            prz_vend=safe_float(row.get("prz_vend")),
            valore_netto=safe_float(row.get("valore_netto")),
        )

        if it.prz_vend is not None and it.prz_acq is not None and it.prz_vend != 0:
            it.sconto_pct = int(round(((it.prz_vend - it.prz_acq) / it.prz_vend) * 100.0))
        else:
            it.sconto_pct = None

        items.append(it)

    if SORT_BY == "valore_netto":
        items.sort(key=lambda x: x.valore_netto if x.valore_netto is not None else -1e18, reverse=SORT_DESC)

    return items


# ============================================================
# MAIN
# ============================================================

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    base_out = os.path.join(OUT_DIR, SUPPLIER_NAME)
    os.makedirs(base_out, exist_ok=True)

    raw_dir = os.path.join(base_out, "_raw")
    os.makedirs(raw_dir, exist_ok=True)

    missing_report = os.path.join(base_out, "_missing_report.txt")

    items = load_items_clean_csv(INPUT_CSV)
    print(f"[INFO] Articoli: {len(items)} | Output: A6 1240x1748 | Metodo: direct xl")

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    missing = []

    for rank, it in enumerate(items, start=1):
        time.sleep(SLEEP_BETWEEN)

        # --- FIX: mai far crashare il loop
        img_url = None
        img_bytes = None
        err = None
        try:
            img_url, img_bytes, err = fetch_best_image_for_code(session, it.code)
        except Exception as e:
            img_url, img_bytes, err = None, None, f"fetch_exception:{type(e).__name__}"

        it.image_url = img_url
        it.image_bytes = img_bytes
        it.image_err = err

        if not img_bytes:
            missing.append((it.code, err or "no_image"))
            print(f"[MISS] {it.code}: {err}")
        else:
            # salva raw
            raw_name = os.path.basename(urlparse(img_url).path) if img_url else it.code.replace("/", "_") + ".jpg"
            raw_path = os.path.join(raw_dir, raw_name)
            try:
                with open(raw_path, "wb") as f:
                    f.write(img_bytes)
            except Exception:
                pass
            print(f"[OK] {it.code} -> {raw_name}")

        # --- FIX: il catalogo si genera SEMPRE, anche senza immagine
        card = draw_final_jpg(it, rank)
        out_path = os.path.join(base_out, f"{rank:03d}_{it.code.replace('/','_')}.jpg")
        card.save(out_path, "JPEG", quality=JPG_QUALITY, subsampling=JPG_SUBSAMPLING, optimize=True)

    if missing:
        with open(missing_report, "w", encoding="utf-8") as f:
            for code, reason in missing:
                f.write(f"{code}\t{reason}\n")
        print(f"[WARN] Missing: {len(missing)} -> {missing_report}")

    print("[DONE] Output:", os.path.abspath(base_out))


if __name__ == "__main__":
    main()
