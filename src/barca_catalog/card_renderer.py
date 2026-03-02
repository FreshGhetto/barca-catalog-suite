from __future__ import annotations

import io
from typing import Optional, List

from PIL import Image, ImageDraw, ImageFont

from .models import Article


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Carica un font TrueType in modo robusto (Windows/Linux/macOS).

    IMPORTANTISSIMO: se finiamo su ImageFont.load_default(), i caratteri risultano minuscoli.
    """
    candidates = [
        "DejaVuSans.ttf",
        "Arial.ttf",
        "arial.ttf",
        "LiberationSans-Regular.ttf",
    ]

    # percorsi tipici
    extra_paths = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\Calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
    ]

    for p in extra_paths:
        candidates.append(p)

    for name in candidates:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue

    # Fallback (minuscolo). Meglio di niente, ma avvisa visivamente.
    return ImageFont.load_default()



def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    bbox = draw.textbbox((0,0), text, font=font)
    return bbox[2]-bbox[0], bbox[3]-bbox[1]

def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> List[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        t = cur + " " + w
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def render_card(
    article: Article,
    img_bytes: Optional[bytes],
    *,
    # A4 landscape @ 300dpi
    canvas_w: int = 3508,
    canvas_h: int = 2480,
) -> Image.Image:
    """Render A4 orizzontale: foto grande a sinistra + tabella (per negozio) a destra.

    - Negozi in ordine alfabetico
    - Colonne taglie: SOLO quelle presenti (union delle taglie con qty>0 in almeno un negozio)
    """

    img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # ---- layout constants ----
    M = 8
    border = 4
    photo_ratio = 0.40
    photo_w = int((canvas_w - 3 * M) * photo_ratio)
    right_x0 = M + photo_w + M
    right_w = canvas_w - right_x0 - M

    # Outer border
    draw.rectangle((border, border, canvas_w - border, canvas_h - border), outline=(0, 0, 0), width=border)

    # ---- fonts (MAX leggibilità, stampa) ----
    f_h1 = _load_font(96)   # codice   # codice
    f_h2 = _load_font(64)    # descrizione    # descrizione
    f_meta = _load_font(50)  # fornitore/reparto/categoria/tipologia  # fornitore/reparto/categoria/tipologia
    f_tbl_h = _load_font(34) # header tabella # header tabella
    f_tbl = _load_font(30)   # celle tabella   # celle tabella
    f_small = _load_font(46) # KPI / note # etichette KPI / note

    # ---- photo box (left) ----
    photo_box = (M, M, M + photo_w, canvas_h - M)
    draw.rectangle(photo_box, outline=(0, 0, 0), width=3)

    def _paste_contain_no_upscale(prod: Image.Image, box):
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        scale = min(bw / prod.width, bh / prod.height, 1.0)
        nw, nh = int(prod.width * scale), int(prod.height * scale)
        prod2 = prod.resize((nw, nh))
        px = x0 + (bw - nw) // 2
        py = y0 + (bh - nh) // 2
        img.paste(prod2, (px, py))
    def _autocrop_whitespace(prod: Image.Image, *, thr: int = 18, pad: int = 12) -> Image.Image:
        """Ritaglia bordi quasi-bianchi per far 'riempire' meglio la foto (senza deformare)."""
        try:
            p = prod.convert("RGB")
            # mask non-white
            px = p.load()
            w, h = p.size
            minx, miny, maxx, maxy = w, h, -1, -1
            for y in range(h):
                for x in range(w):
                    r, g, b = px[x, y]
                    if (255 - r) > thr or (255 - g) > thr or (255 - b) > thr:
                        if x < minx: minx = x
                        if y < miny: miny = y
                        if x > maxx: maxx = x
                        if y > maxy: maxy = y
            if maxx < 0:
                return prod
            minx = max(minx - pad, 0); miny = max(miny - pad, 0)
            maxx = min(maxx + pad, w - 1); maxy = min(maxy + pad, h - 1)
            return p.crop((minx, miny, maxx + 1, maxy + 1))
        except Exception:
            return prod


    if img_bytes:
        try:
            prod = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            prod = _autocrop_whitespace(prod)
            _paste_contain_no_upscale(prod, photo_box)
        except Exception:
            img_bytes = None

    if not img_bytes:
        draw.text((photo_box[0] + 30, photo_box[1] + 30), "IMMAGINE NON DISPONIBILE", font=f_meta, fill=(60, 60, 60))

    # ---- right panel ----
    right_box = (right_x0, M, canvas_w - M, canvas_h - M)
    draw.rectangle(right_box, outline=(0, 0, 0), width=3)

    rx = right_x0 + 20
    y = M + 14

    # Header meta like report
    header_lines = [
        f"FORNITORE: {article.supplier or ''}",
        f"REPARTO: {article.reparto or ''}",
        f"CATEGORIA: {article.categoria or ''}",
        f"TIPOLOGIA: {article.tipologia or ''}",
    ]
    for ln in header_lines:
        draw.text((rx, y), ln, font=f_meta, fill=(0, 0, 0))
        y += 56

    y += 4
    draw.line((right_x0 + 12, y, canvas_w - M - 12, y), fill=(200, 200, 200), width=3)
    y += 6

    # Code + description
    draw.text((rx, y), f"{article.code}", font=f_h1, fill=(0, 0, 0))
    y += 86
    desc = " • ".join([x for x in [article.description, article.color, article.season] if x])
    for ln in _wrap(draw, desc, f_h2, right_w - 60)[:2]:
        draw.text((rx, y), ln, font=f_h2, fill=(0, 0, 0))
        y += 54

    y += 16

    # KPI row
    kpi = [
        ("GIAC", f"{article.giac:.0f}"),
        ("CON", f"{article.con:.0f}"),
        ("VEN", f"{article.ven:.0f}"),
        ("%VEN", f"{article.perc_ven:.1f}%"),
        ("STORE", f"{len([s for s in article.stores if s.upper() != 'XX'])}"),
    ]
    kx = rx
    kw = (right_w - 60) // len(kpi)
    max_kpi_h = 0
    for i, (k, v) in enumerate(kpi):
        x = kx + i * kw
        # Spaziatura verticale calcolata sui font reali per evitare sovrapposizioni
        lb = draw.textbbox((0, 0), k, font=f_small)
        lh = lb[3] - lb[1]
        vb = draw.textbbox((0, 0), v, font=f_tbl)
        vh = vb[3] - vb[1]
        gap = 10
        draw.text((x, y), k, font=f_small, fill=(80, 80, 80))
        draw.text((x, y + lh + gap), v, font=f_tbl, fill=(0, 0, 0))
        max_kpi_h = max_kpi_h if 'max_kpi_h' in locals() else 0
        max_kpi_h = max(max_kpi_h, lh + gap + vh)
    y += max(96, (max_kpi_h if 'max_kpi_h' in locals() else 96) + 18)

    # ---- Store table (alphabetical) with ONLY present sizes ----
    stores = [sr for code, sr in article.stores.items() if code and code.upper() != "XX"]
    stores.sort(key=lambda sr: (sr.store or ""))

    # sizes present = union of size keys with qty>0
    size_set = set()
    for sr in stores:
        for sz, qty in (sr.sizes or {}).items():
            try:
                if float(qty or 0) > 0:
                    size_set.add(int(sz))
            except Exception:
                continue
    if not size_set:
        # fallback: from totals
        for sz, qty in (article.size_totals or {}).items():
            try:
                if float(qty or 0) > 0:
                    size_set.add(int(sz))
            except Exception:
                continue

    sizes = sorted(size_set)

    # Table columns
    base_cols = ["NEG", "GIAC", "CON", "VEN", "%VEN"]
    size_cols = [str(s) for s in sizes]
    cols = base_cols + size_cols

    # Column widths
    col_w = {"NEG": 90, "GIAC": 90, "CON": 90, "VEN": 90, "%VEN": 110}

    remaining = (right_w - 60) - sum(col_w.values())
    size_w = max(34, int(remaining / max(1, len(size_cols))))
    for c in size_cols:
        col_w[c] = size_w

    # if overflow, shrink size columns
    total_w = sum(col_w[c] for c in cols)
    max_w = right_w - 60
    if total_w > max_w and len(size_cols) > 0:
        size_w = max(28, int((max_w - sum(col_w[c] for c in base_cols)) / len(size_cols)))
        for c in size_cols:
            col_w[c] = size_w

    header_h = 88
    table_x0 = rx
    table_y0 = y
    table_x1 = rx + sum(col_w[c] for c in cols)
    # altezza riga dinamica: tante righe => stringe ma resta leggibile
    available_h = (canvas_h - M - 20) - (table_y0 + header_h)
    n_rows = max(1, len(stores) + 1)  # +TOT
    row_h = int(max(54, min(78, available_h / n_rows)))


    # Header
    draw.rectangle((table_x0, table_y0, table_x1, table_y0 + header_h), outline=(0, 0, 0), width=3)
    cx = table_x0
    for c in cols:
        draw.line((cx, table_y0, cx, table_y0 + header_h), fill=(0, 0, 0), width=3)
        tw, th = _text_size(draw, c, f_tbl_h)
        draw.text((cx + 6, table_y0 + (header_h - th)//2), c, font=f_tbl_h, fill=(0, 0, 0))
        cx += col_w[c]
    draw.line((cx, table_y0, cx, table_y0 + header_h), fill=(0, 0, 0), width=3)

    # Totals
    tot_giac = sum(sr.giac for sr in stores)
    tot_con = sum(sr.con for sr in stores)
    tot_ven = sum(sr.ven for sr in stores)
    tot_pct = (tot_ven / tot_con * 100.0) if tot_con else 0.0
    tot_sizes = {}
    for sr in stores:
        for sz, qty in (sr.sizes or {}).items():
            try:
                sz_i = int(sz)
                tot_sizes[sz_i] = tot_sizes.get(sz_i, 0.0) + float(qty or 0.0)
            except Exception:
                continue

    def _row_values(store: str, giac: float, con: float, ven: float, pct: float, sizes_map):
        vals = {
            "NEG": store,
            "GIAC": f"{giac:.0f}" if giac else "",
            "CON": f"{con:.0f}" if con else "",
            "VEN": f"{ven:.0f}" if ven else "",
            "%VEN": f"{pct:.0f}%",
        }
        for s in sizes:
            q = float((sizes_map or {}).get(s, 0.0) or 0.0)
            vals[str(s)] = f"{q:.0f}" if q else ""
        return vals

    # %VEN per negozio come nel report originale: incidenza delle vendite del negozio
    # sul CON totale dell'articolo.
    all_rows = [
        _row_values(sr.store, sr.giac, sr.con, sr.ven, (sr.ven / tot_con * 100.0) if tot_con else 0.0, sr.sizes)
        for sr in stores
    ]
    all_rows.append(_row_values("TOT", tot_giac, tot_con, tot_ven, tot_pct, tot_sizes))

    cur_y = table_y0 + header_h
    max_y = canvas_h - M - 10

    for row in all_rows:
        draw.rectangle((table_x0, cur_y, table_x1, cur_y + row_h), outline=(0, 0, 0), width=3)
        cx = table_x0
        for c in cols:
            draw.line((cx, cur_y, cx, cur_y + row_h), fill=(0, 0, 0), width=3)
            draw.text((cx + 8, cur_y + max(2, (row_h - 30)//2)), str(row.get(c, "")), font=f_tbl, fill=(0, 0, 0))
            cx += col_w[c]
        draw.line((cx, cur_y, cx, cur_y + row_h), fill=(0, 0, 0), width=3)
        cur_y += row_h

        if cur_y > max_y:
            draw.text((table_x0, max_y - 52), "(tabella troncata: troppi negozi)", font=f_small, fill=(120, 0, 0))
            break

    return img