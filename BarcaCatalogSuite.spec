# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata, collect_data_files

block_cipher = None

project_root = Path.cwd()

def add_folder_as_datas(folder_name: str):
    """
    Copia ricorsivamente una cartella dentro dist mantenendo la struttura.
    Ritorna una lista di tuple (src_file, dest_folder).
    """
    folder_path = project_root / folder_name
    out = []
    if not folder_path.exists():
        return out

    for root, _, files in os.walk(folder_path):
        root_path = Path(root)
        rel = root_path.relative_to(project_root)   # es: apps\subdir
        dest_dir = str(rel)                         # dove finisce in dist

        for fn in files:
            src_file = str(root_path / fn)
            out.append((src_file, dest_dir))

    return out

# hidden imports utili per streamlit (minimo indispensabile)
hiddenimports = (
    collect_submodules("streamlit")
    + collect_submodules("altair")
    + collect_submodules("PIL")
)

datas = []
for name in ["apps", "src", "vendor", "assets", "legacy", "docs"]:
    datas += add_folder_as_datas(name)

datas += collect_data_files("streamlit", include_py_files=False)

datas += copy_metadata("streamlit")
datas += copy_metadata("altair")
datas += copy_metadata("watchdog")
datas += copy_metadata("Pillow")
datas += collect_data_files("PIL", include_py_files=False)

a = Analysis(
    ["run_app.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["langchain", "streamlit.external.langchain"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BarcaCatalogSuite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # quando vuoi “niente terminale”, metti False
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="BarcaCatalogSuite",
)