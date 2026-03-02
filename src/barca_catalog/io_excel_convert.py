from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd


def ensure_xlsx(path: Union[str, Path]) -> Path:
    """
    Ensure an Excel file is .xlsx. If input is a legacy .xls, convert it to .xlsx next to it.

    Notes:
    - Conversion preserves *cell values* and sheet names (truncated to 31 chars). Formatting/merges are not preserved,
      which is fine for our value-based parsers.
    - Requires: xlrd (for .xls) and openpyxl (for writing .xlsx).
    """
    p = Path(path)
    if p.suffix.lower() != ".xls":
        return p

    out_path = p.with_suffix(".xlsx")

    # Read all sheets from .xls and write to .xlsx
    xls = pd.ExcelFile(p, engine="xlrd")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
            safe_name = str(sheet)[:31] if sheet else "Sheet1"
            df.to_excel(writer, sheet_name=safe_name, index=False)

    return out_path
