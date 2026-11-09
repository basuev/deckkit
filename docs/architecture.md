# Architecture and product constraints

deckkit manages independent Steam Deck tools through an on-demand installer and
catalog. Its first package configures Cyberpunk 2077. The catalog and launcher
finish their work before gameplay. Keep this model as the package collection
grows. Do not introduce a resident loader, updater or Decky dependency.

The current UI uses Python/Tk and ships with its own runtime. The package format
is independent of the graphical implementation. CLI and GUI operations share the
same installation and profile logic.

## Installation and Steam integration

Installation lives in the user's home directory so normal SteamOS image updates
preserve its files. Compatibility with future Steam client and game versions is
a separate concern.

The first Desktop install closes Steam gracefully before editing text VDF and
registering the catalog shortcut. Later operations use the running Steam client
API for launch options. Never overwrite a live client's entire config.

The per-game launcher wraps the existing `%command%` expression and preserves
other environment flags and game arguments. PyInstaller changes the library
search environment. Restore it before handing execution to Steam/Proton so the
bundled libraries do not leak into the game.

Current QAM settings use the local Steam CEF endpoint and
`SteamClient.Settings.SetSetting`. The older
`SteamClient.System.Perf.UpdateSettings` can report its own FPS limiter disabled
while the unified Gamescope limiter remains active. It must not replace the
current adapter. Protobuf field IDs were checked against the installed client's
serializer. This is not an official stable API.

Apply display and power settings only while the Cyberpunk launch window owns app
ID 1091500. The legacy Perf state subscription verifies that context, but does
not set power controls. CLI profile configuration edits game files only.
`launch --no-ui` applies saved choices inside the normal Steam app context.

Removal restores game files and config deltas immediately. If Steam settings
were changed, a one-shot launch restores their original values in Cyberpunk's
app context and removes its own launch hook. This keeps changes out of the
catalog's or another game's profile without a gameplay watcher.

## Ownership and updates

Receipts record original values and hashes of package writes. Removal restores
only owned values that still match the package's last write. Preserve later
edits by the user or another tool. A snapshot field the package never wrote is
not owned and must not be restored. Flush receipts before committing changes.

A failed package operation restores the immediately preceding installation,
including edits made since the first installation. A batch runs independent
package transactions sequentially. Completed packages remain installed if a
later operation fails. Report the failed package and completed count, then keep
only unfinished selections checked for retry.

Runtime and package downloads use versioned assets and SHA-256 checks. The
Desktop bootstrap embeds the exact runtime URL and hash. Bundles are ordinary
tar.gz archives with relative internal symlinks preserved. Include the licenses
of the libraries actually bundled by the Ubuntu 22.04 build.

HTTPS uses the host CA bundle at `/etc/ssl/certs/ca-certificates.crt`, with
`SSL_CERT_FILE` honored when set. The bundled Ubuntu OpenSSL defaults use paths
that are absent on SteamOS. Share the explicit verified context between catalog
requests and archive downloads. Do not disable certificate verification.

Recognized earlier `codex-deck-ui.archive` and `codex-performance.ini` files are
adopted once and removed, preserving their selected profile. Modified legacy
files remain user-owned. The same rollback snapshot covers old and new paths.
Do not nest the earlier launcher inside the new launch wrapper.

## Cyberpunk package

The retained OLED profile uses Low graphics, 1024x768 output and FSR 2 Performance.
Both FPS choices use 90 Hz, game VSync off, Steam's limiter disabled, the stock
15 W APU budget and VKD3D queue bound 2. `45 FPS` uses the game's limiter.
`Uncapped` disables it. Disable a previous manual TDP ceiling instead of imposing
a lower power budget.

An earlier 10 W profile developed severe lag during prolonged gameplay despite
its built-in benchmark result. Removing that ceiling restored smoothness. A
12 W check also felt worse. Retain stock 15 W. Do not advertise battery savings
or sustained gameplay FPS from benchmark results alone. Input-to-screen latency
has not been externally measured.

The UI archives enlarge selected HUD, main/pause menus, action hints and loading
progress groups. Standard removes our archive. Preserve native accessibility
preferences. Inventory, map, progression and many full-screen/modal contexts keep
their original layout. Native tooltip controllers can override static dimensions
and wrapping. Enlarged long descriptions and video previews overflowed the
viewport, so broader full-screen adaptation is outside the retained scope.

Personal Steam Input layouts and camera preferences are outside this package.
Preserve them. Native game files use the `deckkit-` prefix.

## Interface

Use English labels, monochrome surfaces and large controls. The lowercase pixel
wordmark has wide, flat glyphs with inter-letter spacing removed. Preserve its
approved geometry. Keep the editable Gridmark source and deterministic SVG/PNG
export. No runtime drawing or typography dependency is needed.

The catalog groups packages by scope: `games` for game-specific packages,
`device` for shared device settings and `tools` for independent utilities. QoL
belongs to the relevant scope rather than a separate overlapping category.
Omit empty categories. Only Cyberpunk is distributed in the initial release.
Development mocks illustrate the future collection without shipping fake tools.

Selections persist across categories. Keep checked packages distinct from focus.
Scroll focused cards into view for keyboard and controller navigation. Card
height follows wrapped text, with equal heights within each row.

The pre-launch selector always shows Play and Cancel. A activates the focused
control. Selecting a profile does not launch the game. Play applies the choices
and launches it. D-pad, sticks, keyboard and pointer reach the same controls.
Do not add redundant control instructions or shortcut reminders.

Backend values are `fps_limit=None` or `fps_limit=45`, with a separate `ui_scale`.
Read selection from the actual game settings and archive rather than a duplicate
mode cache. Both the selector and CLI call `profiles.apply`.

`install.py` owns package transactions, `runtime.py` owns runtime replacement and
`catalog.py` owns catalog loading. Shared Tk widgets live in `ui.py`, separate
from the catalog and selector screens. Source and frozen bundles use the same
asset layout. `src/deckkit` is the maintained application implementation.

## Validation scope

The local release was exercised on a physical OLED Deck with pinned download,
Desktop installation, Gaming Mode catalog and launch selection, cancellation,
removal, one-shot Steam restoration and reinstallation. All six FPS/UI choices
were checked against real game files. Original save hashes, personal Steam Input
layouts and unrelated game settings were preserved. Manual startup was also
confirmed. This establishes integration, not sustained gameplay performance.

The development preview uses the real Tk screens with disposable fixtures and a
simulated Steam transport. Keep it outside the installed runtime. It must not
contact Steam or the network and cannot replace real device validation.
