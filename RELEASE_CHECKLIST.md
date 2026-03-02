# Release checklist

- [ ] Run the app locally (Streamlit) and generate a test ZIP.
- [ ] Build portable (PyInstaller onedir) and test on a clean Windows machine.
- [ ] Zip `dist/BarcaCatalogSuite/` and verify it runs by double click.
- [ ] Tag release: `git tag vX.Y.Z` then `git push --tags`
- [ ] Create GitHub Release and attach the portable zip (or use Actions artifacts).
- [ ] (Optional) Build installer via Inno Setup using `installer/inno_setup.iss`.
