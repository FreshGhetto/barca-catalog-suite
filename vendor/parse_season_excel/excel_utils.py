from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)

def convert_xls_to_xlsx(xls_path: Path, out_dir: Path) -> Path:
    """
    Convert .xls to .xlsx using LibreOffice (soffice).
    Returns the converted .xlsx path.
    """
    xls_path = Path(xls_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    soffice = which("soffice") or which("soffice.exe")
    if soffice is None:
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                soffice = c
                break

    if soffice is None:
        raise RuntimeError(
            "Impossibile convertire .xls -> .xlsx: LibreOffice (soffice) non trovato.\n"
            "Soluzioni:\n"
            "  1) Installa LibreOffice e riprova, oppure\n"
            "  2) Apri il file in Excel e salvalo come .xlsx.\n"
        )

    # Use a dedicated, writable LibreOffice profile to avoid permission issues (Linux containers / locked profiles)
    profile_dir = out_dir / "_lo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = profile_dir.resolve().as_uri()

    cmd = [
        soffice,
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--norestore",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to",
        "xlsx",
        "--outdir",
        str(out_dir),
        str(xls_path),
    ]
    env = os.environ.copy()
    # make sure HOME is writable in odd environments; on Windows this is ignored
    env.setdefault("HOME", str(profile_dir))

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Conversione LibreOffice fallita (code={proc.returncode}).\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n"
        )

    xlsx_path = out_dir / (xls_path.stem + ".xlsx")
    if not xlsx_path.exists():
        alt = out_dir / (xls_path.stem + ".XLSX")
        if alt.exists():
            xlsx_path = alt
        else:
            raise RuntimeError("Conversione completata ma file .xlsx non trovato nell'output.")
    return xlsx_path
