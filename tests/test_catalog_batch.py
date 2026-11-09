"""Verify scrolling, cross-category selection and partial batch failures."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import PipePad, fixture

from deckkit import steam

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipUnless(
    tk is not None and os.environ.get("DISPLAY"), "Needs Tk and X11"
)
class CatalogBatch(unittest.TestCase):
    def test_controller_scroll_and_batch(self):
        for size in ((920, 600), (740, 520)):
            with self.subTest(size=size):
                self.check_batch(size)

    def check_batch(self, size):
        from deckkit import catalog_ui

        errors, pads, installed = [], [], {}
        state = {"fail": None}
        real_tk = tk.Tk

        def controller(*args):
            pad = PipePad(*args)
            pads.append(pad)
            return pad

        def install(package_id, **kwargs):
            if package_id == state["fail"]:
                raise RuntimeError("Test download failed.")
            installed[package_id] = {"version": "0.1.0"}
            return {"installed": package_id}

        def factory(*args, **kwargs):
            root = real_tk(*args, **kwargs)

            def fail(_kind, error, _traceback):
                errors.append(error)
                for timer in root.tk.call("after", "info"):
                    root.after_cancel(timer)
                if pads and not pads[-1].closed:
                    pads[-1].close()
                root.destroy()

            root.report_callback_exception = fail

            def children(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from children(child)

            def controls():
                return {
                    item.cget("text"): item
                    for item in children(root)
                    if isinstance(item, tk.Button)
                }

            def wait_for(predicate):
                deadline = time.monotonic() + 3
                while not predicate():
                    if time.monotonic() > deadline:
                        self.fail("Batch did not finish")
                    root.update()
                    time.sleep(0.005)
                root.update()

            def focused(name):
                self.assertEqual(root.focus_get(), controls()[name], name)

            def check():
                try:
                    root.geometry(f"{size[0]}x{size[1]}+0+0")
                    root.update()
                    controls()["Cyberpunk 2077"].focus_force()
                    root.update()
                    pad = pads[-1]
                    title = "Red Dead Redemption 2"
                    long_card = controls()[title]
                    text = tk.Label(
                        root,
                        text=title,
                        font=long_card.cget("font"),
                        wraplength=long_card.cget("wraplength"),
                    )
                    root.update_idletasks()
                    self.assertGreaterEqual(
                        long_card.winfo_height(), text.winfo_reqheight()
                    )
                    text.destroy()
                    pad.accept()
                    self.assertIn("Install selected (1)", controls())
                    for _ in range(4):
                        pad.move(dy=1)
                    focused("Game 12")
                    item = root.focus_get()
                    canvas = next(
                        item
                        for item in children(root)
                        if isinstance(item, tk.Canvas)
                        and item.cget("width") != "6"
                    )
                    self.assertGreater(canvas.yview()[0], 0)
                    self.assertGreaterEqual(
                        item.winfo_rooty(), canvas.winfo_rooty()
                    )
                    self.assertLessEqual(
                        item.winfo_rooty() + item.winfo_height(),
                        canvas.winfo_rooty() + canvas.winfo_height(),
                    )
                    pad.accept()
                    for _ in range(5):
                        pad.move(dy=-1)
                    focused("Games")
                    pad.move(dx=1)
                    pad.accept()
                    focused("Device")
                    pad.move(dy=1)
                    focused("Charge limit")
                    pad.accept()
                    pad.move(dy=1)
                    focused("Install selected (3)")
                    pad.accept()
                    wait_for(
                        lambda: len(installed) == 3 and "Open" in controls()
                    )
                    self.assertEqual(
                        set(installed),
                        {"cyberpunk2077", "game-12", "charge-limit"},
                    )

                    pad.move(dy=-1)
                    pad.move(dy=-1)
                    focused("Games")
                    pad.accept()
                    pad.move(dy=1)
                    pad.move(dx=1)
                    focused("Game 01")
                    pad.accept()
                    for _ in range(3):
                        pad.move(dy=1)
                    pad.move(dx=1)
                    focused("Game 11")
                    pad.accept()
                    pad.move(dy=1)
                    pad.move(dy=1)
                    focused("Install selected (2)")
                    state["fail"] = "game-11"
                    pad.accept()
                    wait_for(
                        lambda: any(
                            isinstance(item, tk.Label)
                            and "1 of 2 installed." in item.cget("text")
                            for item in children(root)
                        )
                    )
                    self.assertIn("game-1", installed)
                    self.assertNotIn("game-11", installed)
                    state["fail"] = None
                    controls()["Install selected (1)"].invoke()
                    wait_for(
                        lambda: "game-11" in installed and "Open" in controls()
                    )
                    root.event_generate("<Escape>")
                except BaseException as error:
                    fail(type(error), error, None)

            root.after(100, check)
            return root

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(tk, "Tk", factory),
            patch.object(catalog_ui, "Gamepads", controller),
            patch.object(steam, "steam_running", return_value=False),
            patch.object(steam, "game_running", return_value=False),
        ):
            installer = fixture(Path(directory))["installer"]
            for i in range(1, 13):
                installer.catalog["packages"].append(
                    {
                        "id": f"game-{i}",
                        "name": "Red Dead Redemption 2"
                        if i == 7
                        else f"Game {i:02}",
                        "category": "games",
                        "summary": "Preview game.",
                        "version": "0.1.0",
                        "kind": "application",
                    }
                )
            installer.catalog["packages"].append(
                {
                    "id": "charge-limit",
                    "name": "Charge limit",
                    "category": "device",
                    "summary": "Preview device setting.",
                    "version": "0.1.0",
                    "kind": "application",
                }
            )
            with (
                patch.object(installer, "install", side_effect=install),
                patch.object(
                    installer, "load_receipt", side_effect=installed.get
                ),
            ):
                catalog_ui.catalog(installer)
        self.assertFalse(errors, errors)
