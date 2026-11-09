"""Controller interface for explicit package operations."""

import queue
import subprocess
import threading
import tkinter as tk
from tkinter import font as tkfont

from . import __version__
from .input import Gamepads
from .paths import external_environment
from .steam import return_to_gaming
from .ui import (
    BG,
    FG,
    FONT,
    MUTED,
    Scrollbar,
    button,
    label,
    selection_images,
    window,
    wordmark,
)

CATEGORIES = {"games": "Games", "device": "Device", "tools": "Tools"}
COLUMNS = 3


def catalog(installer, initial=None):
    root = window("deckkit", height=600)
    header = tk.Frame(root, bg=BG)
    header.grid(row=0, column=0, sticky="w", padx=34, pady=(18, 12))
    logo = wordmark(header)
    logo.configure(borderwidth=0, padx=0, pady=0)
    app_version = label(header, f"v{__version__}", 14)
    app_version.configure(fg=MUTED, borderwidth=0, padx=0, pady=0)
    version_font = tkfont.Font(root=root, font=app_version.cget("font"))
    logo.grid(
        row=0,
        column=0,
        sticky="w",
        pady=(0, version_font.metrics("descent")),
    )
    app_version.grid(row=0, column=1, sticky="s", padx=(12, 0))
    sections = tk.Frame(root, bg=BG)
    sections.grid(row=1, column=0, sticky="ew", padx=34, pady=(0, 10))
    library = tk.Frame(root, bg=BG)
    library.grid(row=2, column=0, sticky="nsew", padx=34)
    library.columnconfigure(0, weight=1)
    library.rowconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)
    canvas = tk.Canvas(library, bg=BG, height=200, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar = Scrollbar(library, canvas.yview)
    scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
    canvas.configure(yscrollcommand=scrollbar.set)
    listing = tk.Frame(canvas, bg=BG)
    listing_id = canvas.create_window(0, 0, window=listing, anchor="nw")
    canvas.bind(
        "<Configure>",
        lambda event: canvas.itemconfigure(listing_id, width=event.width),
    )
    listing.bind(
        "<Configure>",
        lambda _: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    details = tk.Frame(root, bg=BG)
    details.grid(row=3, column=0, sticky="ew", padx=34, pady=(10, 0))
    details.columnconfigure(0, weight=1)
    summary = label(details, "", 22)
    summary.grid(row=0, column=0, sticky="ew")
    version = label(details, "", 20)
    version.configure(fg=MUTED)
    version.grid(row=1, column=0, sticky="w", pady=(6, 0))
    details.bind(
        "<Configure>",
        lambda event: summary.configure(wraplength=max(1, event.width)),
    )
    actions = tk.Frame(root, bg=BG)
    actions.grid(row=4, column=0, sticky="ew", padx=34, pady=(10, 0))
    actions.columnconfigure((0, 1), weight=1, uniform="actions")
    status = label(root, "", 21, wraplength=660)
    footer = tk.Frame(root, bg=BG)
    footer.grid(row=6, column=0, sticky="ew", padx=34, pady=(12, 18))
    indicators = selection_images(root)
    messages = queue.Queue()
    entries = installer.packages()
    index = next(
        (i for i, entry in enumerate(entries) if entry["id"] == initial), 0
    )
    state = {
        "busy": False,
        "closed": False,
        "index": index,
        "category": entries[index].get("category", "games"),
        "chosen": set(),
        "focus": None,
        "controls": [],
        "close_pending": False,
        "poll_timer": None,
        "focus_timer": None,
    }

    def close():
        if state["busy"]:
            state["close_pending"] = True
            return
        state["closed"] = True
        pads.close()
        for name in ("poll_timer", "focus_timer"):
            if state[name] is not None:
                root.after_cancel(state[name])
        root.destroy()

    def operation(call, completed):
        if state["busy"]:
            return
        state["busy"] = True
        set_status("")
        render()

        def work():
            try:
                result = call(lambda text: messages.put(("progress", text)))
                messages.put(("done", (result, completed)))
            except Exception as failure:
                messages.put(("error", str(failure)))

        threading.Thread(target=work, daemon=False).start()

    def targets():
        return (
            [entry for entry in entries if entry["id"] in state["chosen"]]
            if state["chosen"]
            else [entries[state["index"]]]
        )

    def change_packages(remove=False):
        selected = targets()
        if remove:
            selected = [
                entry
                for entry in selected
                if installer.load_receipt(entry["id"])
            ]
        verb = "removed" if remove else "installed"
        completed = (
            selected[0]["name"]
            if len(selected) == 1
            else f"{len(selected)} packages"
        ) + f" {verb}."

        def call(progress):
            preserved = []
            changed = []
            for position, entry in enumerate(selected, 1):
                progress(f"{entry['name']} ({position}/{len(selected)})")
                try:
                    if remove:
                        result = installer.remove(entry["id"], progress)
                    else:
                        result = installer.install(
                            entry["id"], allow_restart=True, progress=progress
                        )
                except Exception as failure:
                    raise RuntimeError(
                        f"{entry['name']}: {failure} "
                        f"{len(changed)} of {len(selected)} {verb}."
                    ) from failure
                changed.append(entry["id"])
                messages.put(("changed", entry["id"]))
                preserved.extend(result.get("preserved", []))
            return {"changed": changed, "preserved": preserved}

        operation(call, completed)

    def open_package():
        entry = entries[state["index"]]
        receipt = installer.load_receipt(entry["id"])
        if entry["kind"] == "cyberpunk2077":
            subprocess.Popen(
                ["steam", "-applaunch", "1091500"], env=external_environment()
            )
        else:
            base = installer.paths.packages / entry["id"]
            target = (base / receipt["manifest"]["entrypoint"]).resolve()
            if base.resolve() not in target.parents:
                raise ValueError("Invalid application entry point")
            subprocess.Popen(
                [str(target)], cwd=base, env=external_environment()
            )
        close()

    def categories():
        return [
            category
            for category in CATEGORIES
            if any(e.get("category", "games") == category for e in entries)
        ]

    def visible_entries():
        return [
            i
            for i, entry in enumerate(entries)
            if entry.get("category", "games") == state["category"]
        ]

    def select_category(category):
        state["category"] = category
        state["index"] = visible_entries()[0]
        state["focus"] = (0, categories().index(category))
        canvas.yview_moveto(0)
        render()

    def toggle(index, item):
        package_id = entries[index]["id"]
        if package_id in state["chosen"]:
            state["chosen"].remove(package_id)
        else:
            state["chosen"].add(package_id)
        item.configure(image=indicators[package_id in state["chosen"]])
        state["index"] = index
        render_details()

    def reveal(item):
        if item.master != listing:
            return
        top, height = item.winfo_y(), item.winfo_height()
        view_top = canvas.canvasy(0)
        view_height = canvas.winfo_height()
        total = max(1, listing.winfo_height())
        if top < view_top:
            canvas.yview_moveto(top / total)
        elif top + height > view_top + view_height:
            canvas.yview_moveto((top + height - view_height) / total)

    def highlight():
        focused = root.focus_get()
        for row, controls in enumerate(state["controls"]):
            for col, item in enumerate(controls):
                if focused == item:
                    state["focus"] = row, col
                    reveal(item)
                item.configure(
                    highlightbackground=FG if focused == item else BG
                )

    def focus():
        row, col = state["focus"]
        row = min(row, len(state["controls"]) - 1)
        controls = state["controls"][row]
        col = min(col, len(controls) - 1)
        state["focus"] = row, col
        controls[col].focus_set()
        reveal(controls[col])

    def bind_controls():
        for controls in state["controls"]:
            for item in controls:
                item.configure(state="disabled" if state["busy"] else "normal")
                item.bind("<FocusIn>", lambda _: highlight())
                item.bind("<FocusOut>", lambda _: highlight())

    def render_details():
        entry = entries[state["index"]]
        receipt = installer.load_receipt(entry["id"])
        summary.configure(text=entry["summary"])
        version.configure(
            text=("Installed " + receipt["version"])
            if receipt
            else ("Version " + entry["version"])
        )
        selected = targets()
        if state["chosen"]:
            commands = [
                (f"Install selected ({len(selected)})", change_packages)
            ]
            installed = sum(
                installer.load_receipt(e["id"]) is not None for e in selected
            )
            if installed:
                commands.append(
                    (
                        f"Remove selected ({installed})",
                        lambda: change_packages(True),
                    )
                )
        elif not receipt:
            name = (
                "Install and restart Steam"
                if not (installer.paths.state / "integration.json").exists()
                else "Install"
            )
            commands = [(name, change_packages)]
        elif receipt["version"] != entry["version"]:
            commands = [
                ("Update", change_packages),
                ("Remove", lambda: change_packages(True)),
            ]
        else:
            commands = [
                ("Open", open_package),
                ("Remove", lambda: change_packages(True)),
            ]
        for widget in actions.winfo_children():
            widget.destroy()
        controls = []
        for col, (name, call) in enumerate(commands):
            item = button(actions, name, call, col == 0, highlightthickness=2)
            item.bind(
                "<Configure>",
                lambda event, control=item: control.configure(
                    wraplength=max(1, event.width - 24)
                ),
            )
            item.grid(
                row=0,
                column=col,
                sticky="ew",
                padx=((0, 9) if col == 0 else (9, 0))
                if len(commands) == 2
                else 0,
                columnspan=2 if len(commands) == 1 else 1,
            )
            controls.append(item)
        state["controls"][-2] = controls
        bind_controls()

    def render():
        for parent in (sections, listing):
            for widget in parent.winfo_children():
                widget.destroy()
        state["controls"] = []
        category_buttons = []
        available = categories()
        for col, category in enumerate(available):
            sections.columnconfigure(col, weight=1, uniform="categories")
            item = button(
                sections,
                CATEGORIES[category],
                lambda c=category: select_category(c),
                category == state["category"],
                highlightthickness=2,
            )
            item.configure(height=0, pady=8, font=(FONT, -22, "bold"))
            item.grid(
                row=0,
                column=col,
                sticky="ew",
                padx=(0, 8) if col < len(available) - 1 else 0,
            )
            category_buttons.append(item)
        state["controls"].append(category_buttons)
        visible = visible_entries()
        for col in range(COLUMNS):
            listing.columnconfigure(col, weight=1, uniform="packages")
        for offset, index in enumerate(visible):
            row, col = divmod(offset, COLUMNS)
            if col == 0:
                state["controls"].append([])
            entry = entries[index]
            item = button(listing, entry["name"], None, highlightthickness=2)
            item.configure(
                command=lambda i=index, control=item: toggle(i, control),
                font=(FONT, -22),
                height=0,
                anchor="w",
                padx=12,
                image=indicators[entry["id"] in state["chosen"]],
                compound="left",
                justify="left",
            )
            item.bind(
                "<Configure>",
                lambda event, control=item: control.configure(
                    wraplength=max(1, event.width - 68)
                ),
            )
            item.grid(
                row=row,
                column=col,
                sticky="nsew",
                pady=(0, 8),
                padx=(0, 8) if col < COLUMNS - 1 else 0,
            )
            state["controls"][-1].append(item)
        footer_buttons = [refresh_button]
        runtime = installer.catalog.get("runtime", {})
        if runtime.get("version", __version__) != __version__:
            footer_buttons.append(runtime_button)
        else:
            runtime_button.grid_remove()
        if initial:
            footer_buttons.append(return_button)
        for col in range(3):
            footer.columnconfigure(col, weight=0, minsize=0, uniform="")
        for col, item in enumerate(footer_buttons):
            footer.columnconfigure(col, weight=1, uniform="footer")
            item.configure(font=(FONT, -21))
            item.bind(
                "<Configure>",
                lambda event, control=item: control.configure(
                    wraplength=max(1, event.width - 24)
                ),
            )
            item.grid(
                row=0,
                column=col,
                sticky="ew",
                padx=(0, 8) if col < len(footer_buttons) - 1 else 0,
            )
        state["controls"] += [[], footer_buttons]
        render_details()
        if state["focus"] is None:
            state["focus"] = len(state["controls"]) - 2, 0
        if not state["busy"]:
            if state["focus_timer"] is not None:
                root.after_cancel(state["focus_timer"])
            state["focus_timer"] = root.after_idle(focus)

    def navigate(dx=0, dy=0):
        if state["busy"]:
            return "break"
        row, col = state["focus"]
        row = max(0, min(len(state["controls"]) - 1, row + dy))
        col = max(0, min(len(state["controls"][row]) - 1, col + dx))
        state["focus"] = row, col
        focus()
        return "break"

    def confirm():
        focused = root.focus_get()
        if not state["busy"] and isinstance(
            focused, (tk.Button, tk.Checkbutton)
        ):
            focused.invoke()
        return "break"

    def refresh():
        def call(progress):
            progress("Checking for updates")
            installer.refresh()

        operation(call, "Update check complete.")

    def set_status(text):
        status.configure(text=text, fg=FG)
        if text:
            status.grid(row=5, column=0, sticky="ew", padx=34, pady=(8, 0))
        else:
            status.grid_remove()

    refresh_button = button(
        footer, "Check for updates", refresh, highlightthickness=2
    )
    return_button = button(
        footer,
        "Return to Gaming Mode",
        lambda: return_to_gaming(installer.paths.home),
        highlightthickness=2,
    )
    runtime_button = button(
        footer,
        "Update deckkit",
        lambda: operation(
            installer.update_runtime, "deckkit updated. Reopen the catalog."
        ),
        highlightthickness=2,
    )

    def poll():
        if state["closed"]:
            return
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == "progress":
                    set_status(value)
                    continue
                if kind == "changed":
                    state["chosen"].discard(value)
                    continue
                state["busy"] = False
                if kind == "error":
                    set_status(value)
                else:
                    result, completed = value
                    entries[:] = installer.packages()
                    if isinstance(result, dict):
                        state["chosen"].difference_update(
                            result.get("changed", [])
                        )
                        if result.get("preserved"):
                            completed += (
                                " Changes made outside deckkit were kept."
                            )
                    set_status(completed)
                render()
                if state["close_pending"]:
                    close()
                    return
        except queue.Empty:
            pass
        state["poll_timer"] = root.after(50, poll)

    root.bind("<Left>", lambda _: navigate(-1, 0))
    root.bind("<Right>", lambda _: navigate(1, 0))
    root.bind("<Up>", lambda _: navigate(0, -1))
    root.bind("<Down>", lambda _: navigate(0, 1))
    root.bind("<Return>", lambda _: confirm())
    root.bind("<Escape>", lambda _: close())
    root.bind("<Button-4>", lambda _: canvas.yview_scroll(-1, "units"))
    root.bind("<Button-5>", lambda _: canvas.yview_scroll(1, "units"))
    root.bind(
        "<MouseWheel>",
        lambda event: canvas.yview_scroll(
            -1 if event.delta > 0 else 1, "units"
        ),
    )
    root.protocol("WM_DELETE_WINDOW", close)
    pads = Gamepads(root, navigate, confirm, close)
    render()
    state["poll_timer"] = root.after(50, poll)
    root.mainloop()
