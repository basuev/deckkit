# Project instructions

- Use Conventional Commits: `type(module): short description`.

- Read [architecture and product constraints](docs/architecture.md) before changing package lifecycle, Steam integration or public installation behavior.
- Keep the application on demand. Do not add a permanent loader or require Decky.
- Follow [code style and boundaries](docs/style.md) for deckkit source changes.
- Keep user data, experimental exports and device credentials outside Git. `.local/` is private research context and must stay ignored.
- Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` for lifecycle changes.
- Build portable releases with `scripts/build_release.py` in the Ubuntu 22.04 builder. The host system is newer than the supported binary baseline.
- Do not publish or push unless explicitly authorized. This preparation stops before creating a remote repository or uploading release assets.
