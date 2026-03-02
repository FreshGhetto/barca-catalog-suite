import csv
import re
from pathlib import Path
from collections import Counter

ART_RE = re.compile(r"^(48|49)/[A-Z0-9]+$", re.IGNORECASE)
STORE_RE = re.compile(r"^[A-Z]{1,3}\d{0,2}$|^WEB$|^SPW$|^ME2$|^M4$|^XX$", re.IGNORECASE)

def norm(s: str) -> str:
    return (s or "").strip()

def looks_like_article(cell: str) -> bool:
    return bool(ART_RE.match(norm(cell)))

def looks_like_store(cell: str) -> bool:
    s = norm(cell).upper().replace(" ", "")
    if not s:
        return False
    if s.isdigit():
        return False
    return bool(STORE_RE.match(s))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    p = Path(args.csv)
    if not p.exists():
        raise FileNotFoundError(p)

    total_rows = 0
    data_rows = 0
    headerish_rows = 0

    unique_articles = set()
    store_counter = Counter()

    cleaned = []

    with p.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")

        for row in reader:
            total_rows += 1
            cells = [norm(c) for c in row]

            art_idx = next((i for i,c in enumerate(cells) if looks_like_article(c)), None)
            store_idx = next((i for i,c in enumerate(cells) if looks_like_store(c)), None)

            if art_idx is None or store_idx is None:
                headerish_rows += 1
                continue

            articolo = cells[art_idx].upper()
            neg = cells[store_idx].upper().replace(" ", "")

            def parse_int(x):
                x = norm(x).replace(".", "").replace(",", ".")
                try:
                    v = float(x)
                    if abs(v - round(v)) > 1e-6:
                        return None
                    return int(round(v))
                except:
                    return None

            nums = []
            for c in cells[store_idx+1:store_idx+13]:
                v = parse_int(c)
                if v is None:
                    continue
                if -5000 <= v <= 5000:
                    nums.append(v)
                if len(nums) == 3:
                    break

            giac = nums[0] if len(nums) > 0 else 0
            con  = nums[1] if len(nums) > 1 else 0
            ven  = nums[2] if len(nums) > 2 else 0

            data_rows += 1
            unique_articles.add(articolo)
            store_counter[neg] += 1

            cleaned.append([articolo, neg, giac, con, ven])

    print(f"Righe totali: {total_rows}")
    print(f"Righe dati: {data_rows}")
    print(f"Righe intestazione/rumore: {headerish_rows}")
    print(f"Articoli unici trovati: {len(unique_articles)}")
    print(f"Negozi unici trovati: {len(store_counter)}")

    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        with outp.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["articolo","neg","giac","con","ven"])
            w.writerows(cleaned)
        print(f"CSV pulito salvato in: {outp}")

if __name__ == "__main__":
    main()