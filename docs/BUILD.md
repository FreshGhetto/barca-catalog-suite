# Build & Release (Windows)

## 1) Run (developer mode)
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run apps\streamlit_app.py
```

## 2) Portable EXE (recommended first)
Install PyInstaller:
```powershell
pip install pyinstaller
```

Build **onedir** (most reliable with Streamlit):
```powershell
pyinstaller --noconfirm --clean --onedir --name BarcaCatalogSuite run_app.py
```

Output:
- `dist\BarcaCatalogSuite\BarcaCatalogSuite.exe`

Portable package:
- Zip the whole folder `dist\BarcaCatalogSuite\` and share it.

## 3) (Optional) One-file EXE
Sometimes works, sometimes heavy with Streamlit:
```powershell
pyinstaller --noconfirm --clean --onefile --name BarcaCatalogSuite run_app.py
```

## 4) GitHub Releases
Recommended approach:
- Tag a version: `git tag v1.0.0` then `git push --tags`
- A GitHub Action can build and attach the portable zip to the Release (see `.github/workflows/windows-build.yml`).
