# Code style and boundaries

Prefer a small number of explicit operations with clear ownership. Keep the
installer on demand and the GUI thin. Share application operations between the
CLI and GUI. Do not add a loader, background updater or framework for hypothetical
packages.

Use four spaces in Python, one statement per line and expanded control-flow
blocks. Separate validation, preparation, mutation and persistence with blank
lines. Keep related statements together instead of separating every line.
Use two blank lines between top-level definitions and one between methods.
Aim for 79 columns. Break long calls and data structures by their structure.
Use double-quoted strings and comments that explain constraints and decisions.
Formatting tools cannot decide the logical grouping of statements.

Use concrete names such as `package_id`, `steam_api`, `fps_limit` and `ui_scale`.
An uncapped FPS limit is `None`. Use `deckkit` for the command and module, deckkit
for the application name, and `deckkit-` for owned game files. Retain conventional
short names such as `fd` and loop indices in small scopes. Keep native Steam and
game setting names unchanged at the integration boundary.

Keep file writes atomic and record owned changes before applying them. Preserve
later edits by the user. Migrate known legacy artifacts rather than loading two
copies or maintaining a second implementation. Scope Steam display changes to
Cyberpunk's active app context.

Keep formatting changes separate from behavior changes during development.
Use Ruff only as a development tool. The installed application must not depend
on it. Make targets expose the existing checks and builder without introducing
another build system.
