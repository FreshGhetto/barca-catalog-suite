from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class StoreRow:
    store: str
    giac: float = 0.0
    con: float = 0.0
    ven: float = 0.0
    perc_ven: float = 0.0
    sizes: Dict[int, float] = field(default_factory=dict)

@dataclass
class Article:
    code: str
    description: str = ""
    color: str = ""
    season: str = ""
    supplier: str = ""
    reparto: str = ""
    categoria: str = ""
    tipologia: str = ""

    giac: float = 0.0
    con: float = 0.0
    ven: float = 0.0
    perc_ven: float = 0.0

    size_totals: Dict[int, float] = field(default_factory=dict)
    stores: Dict[str, StoreRow] = field(default_factory=dict)

    source_files: set[str] = field(default_factory=set)

    def recompute_totals(self) -> None:
        # prefer to compute from stores excluding XX
        stores = [sr for k, sr in self.stores.items() if k.upper() != "XX"]
        self.giac = sum(sr.giac for sr in stores)
        self.con  = sum(sr.con for sr in stores)
        self.ven  = sum(sr.ven for sr in stores)
        self.perc_ven = (self.ven / self.con * 100.0) if self.con else 0.0

        size_totals: Dict[int, float] = {}
        for sr in stores:
            for s, v in sr.sizes.items():
                size_totals[s] = size_totals.get(s, 0.0) + float(v or 0.0)
        self.size_totals = dict(sorted(size_totals.items(), key=lambda x: x[0]))
