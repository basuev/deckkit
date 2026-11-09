"""Exercise every catalog action with real Tk and controller events."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import PipePad, fixture

from deckkit import __version__, steam

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipUnless(
    tk is not None and os.environ.get("DISPLAY"), "Needs Tk and X11"
)
class Catalog(unittest.TestCase):
    def test_all_actions_remain_reachable_after_operations(self):
        for size in ((920, 600), (740, 520)):
            with self.subTest(size=size):
                self.check_catalog(size)

    def check_catalog(self, size):
        from deckkit import catalog_ui

        real_tk = tk.Tk
        errors, pads, returned, updates = [], [], [], []
        release = threading.Event()
        state = {}

        def controller(*args):
            pad = PipePad(*args)
            pads.append(pad)
            return pad

        def refresh():
            release.wait(3)
            if state.get("fail"):
                raise RuntimeError("Test update failed.")
            installer.catalog["runtime"] = {"version": "0.2.0"}

        def update_runtime(progress):
            updates.append(True)
            installer.catalog["runtime"] = {"version": __version__}

        def factory(*args, **kwargs):
            root = real_tk(*args, **kwargs)

            def fail(_kind, value, _traceback):
                errors.append(value)
                release.set()
                if pads and not pads[-1].closed:
                    pads[-1].close()
                root.destroy()

            root.report_callback_exception = fail

            def children(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from children(child)

            def buttons():
                return {
                    item.cget("text"): item
                    for item in children(root)
                    if isinstance(item, (tk.Button, tk.Checkbutton))
                    and item.winfo_viewable()
                }

            def wait_for(predicate):
                deadline = time.monotonic() + 3
                while not predicate():
                    if time.monotonic() > deadline:
                        self.fail("Catalog operation did not complete")
                    root.update()
                    time.sleep(0.005)
                root.update()

            def fits():
                root.update_idletasks()
                for item in buttons().values():
                    self.assertGreaterEqual(
                        item.winfo_rootx(), root.winfo_rootx()
                    )
                    self.assertGreaterEqual(
                        item.winfo_rooty(), root.winfo_rooty()
                    )
                    self.assertLessEqual(
                        item.winfo_rootx() + item.winfo_width(),
                        root.winfo_rootx() + root.winfo_width(),
                    )
                    self.assertLessEqual(
                        item.winfo_rooty() + item.winfo_height(),
                        root.winfo_rooty() + root.winfo_height(),
                    )

            def focused(name):
                self.assertEqual(root.focus_get(), buttons()[name], name)

            def check():
                try:
                    root.geometry(f"{size[0]}x{size[1]}+0+0")
                    root.update()
                    buttons()["Open"].focus_force()
                    root.update()
                    pad = pads[-1]
                    fits()
                    self.assertEqual(
                        buttons()["Cyberpunk 2077"].cget("bg"), "#2c3036"
                    )
                    self.assertEqual(
                        buttons()["Cyberpunk 2077"].winfo_y(),
                        buttons()["Hades II"].winfo_y(),
                    )
                    pad.move(dx=1)
                    focused("Remove")
                    pad.move(dy=1)
                    focused("Return to Gaming Mode")
                    pad.accept()
                    self.assertEqual(returned, [True])
                    pad.move(dx=-1)
                    focused("Check for updates")
                    pad.accept()
                    for item in buttons().values():
                        self.assertEqual(str(item.cget("state")), "disabled")
                    release.set()
                    wait_for(lambda: "Update deckkit" in buttons())
                    fits()
                    focused("Check for updates")
                    pad.move(dx=1)
                    focused("Update deckkit")
                    pad.accept()
                    wait_for(lambda: "Update deckkit" not in buttons())
                    self.assertEqual(updates, [True])
                    pad.move(dy=-1)
                    pad.move(dx=1)
                    focused("Remove")
                    pad.accept()
                    wait_for(lambda: "Install" in buttons())
                    focused("Install")
                    pad.move(dy=-1)
                    focused("Cyberpunk 2077")
                    pad.accept()
                    pad.accept()
                    pad.move(dy=1)
                    focused("Install")
                    pad.accept()
                    wait_for(lambda: "Open" in buttons())
                    focused("Open")
                    state["fail"] = True
                    pad.move(dy=1)
                    pad.accept()
                    wait_for(
                        lambda: any(
                            isinstance(item, tk.Label)
                            and item.cget("text") == "Test update failed."
                            for item in children(root)
                        )
                    )
                    focused("Check for updates")
                    fits()
                    root.event_generate("<Tab>")
                    root.update()
                    focused("Return to Gaming Mode")
                    root.event_generate("<Return>")
                    root.update()
                    self.assertEqual(returned, [True, True])
                    pad.move(dy=-1)
                    pad.move(dy=-1)
                    pad.move(dy=-1)
                    focused("Device")
                    pad.move(dx=-1)
                    focused("Games")
                    pad.move(dx=1)
                    pad.accept()
                    fits()
                    self.assertNotIn("Cyberpunk 2077", buttons())
                    self.assertIn("Charge limit", buttons())
                    pad.move(dy=1)
                    pad.move(dx=1)
                    focused("Display profile")
                    pad.accept()
                    focused("Display profile")
                    pad.move(dy=-1)
                    focused("Device")
                    pad.move(dx=1)
                    pad.accept()
                    self.assertIn("Quick notes", buttons())
                    self.assertNotIn("Charge limit", buttons())
                    fits()
                    pad.move(dx=-1)
                    pad.move(dx=-1)
                    pad.accept()
                    focused("Games")
                    self.assertIn("Cyberpunk 2077", buttons())
                    root.event_generate("<Escape>")
                except BaseException as error:
                    fail(type(error), error, None)

            root.after(100, check)
            return root

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(steam, "steam_running", return_value=False),
            patch.object(steam, "game_running", return_value=False),
            patch.object(tk, "Tk", factory),
            patch.object(catalog_ui, "Gamepads", controller),
            patch.object(
                catalog_ui,
                "return_to_gaming",
                side_effect=lambda home: returned.append(True),
            ),
        ):
            data = fixture(Path(directory))
            installer = data["installer"]
            installer.install("cyberpunk2077")
            for package_id, name, category in (
                ("hades2", "Hades II", "games"),
                ("charge-limit", "Charge limit", "device"),
                ("display-profile", "Display profile", "device"),
                ("quick-notes", "Quick notes", "tools"),
            ):
                installer.catalog["packages"].append(
                    {
                        "id": package_id,
                        "name": name,
                        "category": category,
                        "version": "0.1.0",
                        "summary": name,
                        "kind": "application",
                    }
                )
            with (
                patch.object(installer, "refresh", refresh),
                patch.object(installer, "update_runtime", update_runtime),
            ):
                catalog_ui.catalog(installer, "cyberpunk2077")
        self.assertFalse(errors, errors)
