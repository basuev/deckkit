"""Exercise controller navigation and persistence in a real Tk event loop."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import PipePad, fixture

from deckkit import cyberpunk, profiles, steam

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipUnless(
    tk is not None and os.environ.get("DISPLAY"), "Needs Tk and X11"
)
class Selector(unittest.TestCase):
    def test_play_persists_selection_after_reopening(self):
        for size in ((920, 560), (740, 520)):
            with self.subTest(size=size):
                self.check_dialog(size, cancel=False)

    def test_cancel_keeps_previous_selection(self):
        for size in ((920, 560), (740, 520)):
            with self.subTest(size=size):
                self.check_dialog(size, cancel=True)

    def check_dialog(self, size, cancel):
        from deckkit import selector

        real_tk = tk.Tk
        errors = []
        state = {}

        def controller(*args):
            pad = PipePad(*args)
            state["pad"] = pad
            return pad

        def factory(*args, **kwargs):
            root = real_tk(*args, **kwargs)

            def fail(_kind, value, _traceback):
                errors.append(value)
                root.destroy()

            root.report_callback_exception = fail

            def check():
                try:
                    root.geometry(f"{size[0]}x{size[1]}+0+0")
                    root.update_idletasks()

                    def children(parent):
                        for child in parent.winfo_children():
                            yield child
                            yield from children(child)

                    buttons = {
                        child.cget("text"): child
                        for child in children(root)
                        if isinstance(child, tk.Button)
                    }
                    self.assertEqual(
                        set(buttons),
                        {
                            "Uncapped",
                            "45 FPS",
                            "Standard",
                            "150%",
                            "175%",
                            "Play",
                            "Cancel",
                        },
                    )
                    for button in buttons.values():
                        self.assertTrue(button.winfo_viewable())
                        self.assertLessEqual(
                            button.winfo_rooty() + button.winfo_height(),
                            root.winfo_rooty() + root.winfo_height(),
                        )

                    buttons["Play"].focus_force()
                    root.update()
                    pad = state["pad"]

                    if state.get("reopened"):
                        expected = (45, 175) if cancel else (None, 150)
                        self.assertEqual(
                            cyberpunk.selected(state["receipt"]), expected
                        )
                        for name in (
                            ("45 FPS", "175%")
                            if cancel
                            else ("Uncapped", "150%")
                        ):
                            self.assertEqual(
                                buttons[name].cget("bg"), "#e4e7ec"
                            )
                        pad.move(-1, 0)
                        pad.accept()
                        return

                    self.assertEqual(buttons["45 FPS"].cget("bg"), "#e4e7ec")
                    pad.move(dy=-1)
                    pad.send(3, 0, -24000)
                    pad.send(3, 0, -28000)
                    self.assertEqual(root.focus_get(), buttons["150%"])
                    pad.send(3, 0, 0)
                    pad.accept()

                    pad.move(dy=-1)
                    pad.move(dx=-1)
                    pad.accept()
                    self.assertEqual(
                        cyberpunk.selected(state["receipt"]), (45, 175)
                    )

                    pad.move(dy=1)
                    pad.move(dy=1)
                    if cancel:
                        pad.move(dx=-1)
                    self.assertEqual(
                        root.focus_get(),
                        buttons["Cancel" if cancel else "Play"],
                    )
                    pad.accept()
                except BaseException as error:
                    errors.append(error)
                    state["pad"].close()
                    root.destroy()

            root.after(100, check)
            return root

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(steam, "steam_running", return_value=False),
            patch.object(steam, "game_running", return_value=False),
            patch.object(tk, "Tk", factory),
            patch.object(selector, "Gamepads", controller),
        ):
            data = fixture(Path(directory))
            installer = data["installer"]
            installer.install("cyberpunk2077")
            profiles.apply(installer, "cyberpunk2077", 45, 175)
            state["receipt"] = installer.load_receipt("cyberpunk2077")
            before = data["settings"].read_bytes()

            self.assertEqual(
                selector.selector(installer, state["receipt"]), not cancel
            )
            self.assertFalse(errors, errors)
            if cancel:
                self.assertEqual(data["settings"].read_bytes(), before)

            state["reopened"] = True
            self.assertFalse(selector.selector(installer, state["receipt"]))
            self.assertFalse(errors, errors)
