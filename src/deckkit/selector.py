"""Pre-launch profile selection and one-shot restoration feedback."""

import tkinter as tk

from . import cyberpunk, profiles
from .input import Gamepads
from .ui import BG, FG, FONT, MUTED, SELECTED, SURFACE, button, label, window


def selector(installer, receipt):
    root = window("Cyberpunk 2077")
    values = list(cyberpunk.selected(receipt))
    rows = [cyberpunk.FPS_LIMITS, cyberpunk.UI_SCALES]
    active, action_index = 2, 1
    accepted = closing = False
    label(root, "Cyberpunk 2077", 32, True).grid(
        row=0, column=0, sticky="w", padx=34, pady=(26, 16)
    )
    labels, buttons = [], [{}, {}]
    names = {
        None: "Uncapped",
        45: "45 FPS",
        100: "Standard",
        150: "150%",
        175: "175%",
    }
    for row, title in enumerate(["Mode", "Interface"]):
        heading = label(root, title, 24, True)
        heading.grid(
            row=1 + row * 2, column=0, sticky="w", padx=34, pady=(8, 10)
        )
        labels.append(heading)
        choices = tk.Frame(root, bg=BG)
        choices.grid(
            row=2 + row * 2, column=0, sticky="nsew", padx=34, pady=(0, 18)
        )
        root.rowconfigure(2 + row * 2, weight=1)
        choices.rowconfigure(0, weight=1)
        choices.columnconfigure(
            tuple(range(len(rows[row]))), weight=1, uniform="choices"
        )
        for col, value in enumerate(rows[row]):
            item = button(
                choices, names[value], lambda r=row, v=value: select(r, v)
            )
            item.configure(font=(FONT, -29, "bold"), highlightthickness=2)
            item.grid(
                row=0,
                column=col,
                sticky="nsew",
                padx=(
                    0 if col == 0 else 8,
                    0 if col == len(rows[row]) - 1 else 8,
                ),
            )
            buttons[row][value] = item
            item.bind("<FocusIn>", lambda _, r=row: focus_choice(r))
    error = label(root, "", 22, wraplength=840)
    actions = tk.Frame(root, bg=BG)
    actions.grid(row=6, column=0, sticky="ew", padx=34, pady=(0, 26))
    actions.columnconfigure((0, 1), weight=1)

    def refresh():
        focused = root.focus_get()
        for row in range(2):
            labels[row].configure(fg=FG if active == row else MUTED)
            for value, item in buttons[row].items():
                selected = value == values[row]
                item.configure(
                    bg=SELECTED if selected else SURFACE,
                    fg="#111318" if selected else FG,
                    activebackground="#cbd0d7" if selected else "#454b55",
                    activeforeground="#111318" if selected else FG,
                    highlightbackground=FG if focused == item else BG,
                )
        for item in action_buttons:
            item.configure(highlightbackground=FG if focused == item else BG)

    def select(row, value):
        values[row] = value
        buttons[row][value].focus_set()
        refresh()

    def focus_choice(row):
        nonlocal active
        active = row
        refresh()

    def focus_action(index):
        nonlocal active, action_index
        active, action_index = 2, index
        refresh()

    def navigate(dx=0, dy=0):
        nonlocal active, action_index
        focused = root.focus_get()
        old_row = active
        active = max(0, min(2, active + dy))
        if active == 2:
            if dx:
                action_index = max(0, min(1, action_index + dx))
            action_buttons[action_index].focus_set()
        else:
            choices = list(buttons[active].values())
            index = (
                choices.index(focused)
                if old_row == active and focused in choices
                else rows[active].index(values[active])
            )
            index = max(0, min(len(choices) - 1, index + dx))
            choices[index].focus_set()
        return "break"

    def activate():
        focused = root.focus_get()
        if isinstance(focused, tk.Button):
            focused.invoke()
        return "break"

    def close():
        nonlocal closing
        if not closing:
            closing = True
            pads.close()
            root.destroy()

    def confirm():
        nonlocal accepted
        if closing:
            return "break"
        try:
            profiles.apply(
                installer,
                receipt["id"],
                values[0],
                values[1],
                steam=True,
                pump=root.update,
            )
        except (OSError, RuntimeError, ValueError, StopIteration) as failure:
            error.configure(text=str(failure), fg="#f5be77")
            error.grid(row=5, column=0, sticky="ew", padx=34, pady=(0, 18))
            return "break"
        accepted = True
        close()
        return "break"

    cancel = button(actions, "Cancel", close, highlightthickness=2)
    cancel.grid(row=0, column=0, sticky="ew", padx=(0, 9))
    play = button(actions, "Play", confirm, True, highlightthickness=2)
    play.grid(row=0, column=1, sticky="ew", padx=(9, 0))
    action_buttons = [cancel, play]
    cancel.bind("<FocusIn>", lambda _: focus_action(0))
    play.bind("<FocusIn>", lambda _: focus_action(1))
    root.bind("<Left>", lambda _: navigate(-1, 0))
    root.bind("<Right>", lambda _: navigate(1, 0))
    root.bind("<Up>", lambda _: navigate(0, -1))
    root.bind("<Down>", lambda _: navigate(0, 1))
    root.bind("<Return>", lambda _: activate())
    root.bind("<Escape>", lambda _: close())
    root.protocol("WM_DELETE_WINDOW", close)
    pads = Gamepads(root, navigate, activate, close)
    root.after_idle(play.focus_set)
    refresh()
    root.mainloop()
    return accepted


def restore_window(installer, job):
    root = window("Cyberpunk 2077", height=480)
    label(root, "Cyberpunk 2077", 32, True).grid(
        row=0, column=0, sticky="w", padx=34, pady=28
    )
    status = label(root, "Restoring Steam settings", 24, wraplength=840)
    status.grid(row=1, column=0, sticky="nsew", padx=34, pady=24)
    root.rowconfigure(1, weight=1)
    accepted = False

    def run():
        nonlocal accepted
        try:
            profiles.restore_display(installer, job, root.update)
            accepted = True
            root.destroy()
        except (OSError, RuntimeError, ValueError, StopIteration) as failure:
            status.configure(text=str(failure), fg="#f5be77")
            button(root, "Retry", run, True).grid(
                row=2, column=0, sticky="ew", padx=34, pady=28
            )

    root.after(300, run)
    root.mainloop()
    return accepted
