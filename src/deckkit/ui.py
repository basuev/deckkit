"""Shared Tk widgets, without game or installation operations."""

import tkinter as tk

from .paths import data_root

BG, SURFACE, FG, MUTED, SELECTED = (
    "#17191d",
    "#2c3036",
    "#f1f1f1",
    "#b8bec7",
    "#e4e7ec",
)
FONT = "Cantarell"


def window(title, width=920, height=560):
    root = tk.Tk(className="deckkit")
    root.title(title)
    root.configure(bg=BG)
    root.minsize(740, 480)
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.columnconfigure(0, weight=1)
    return root


def label(parent, text="", size=24, bold=False, **kwargs):
    return tk.Label(
        parent,
        text=text,
        font=(FONT, -size, "bold" if bold else "normal"),
        bg=BG,
        fg=FG,
        anchor="w",
        justify="left",
        **kwargs,
    )


def wordmark(parent):
    image = tk.PhotoImage(
        master=parent, file=str(data_root() / "wordmark.png")
    )
    item = tk.Label(parent, image=image, bg=BG, anchor="w")
    item.image = image
    return item


def button(parent, text, command, primary=False, **kwargs):
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=(FONT, -24, "bold" if primary else "normal"),
        bg=SELECTED if primary else SURFACE,
        fg="#111318" if primary else FG,
        activebackground="#cbd0d7" if primary else "#454b55",
        activeforeground="#111318" if primary else FG,
        relief="flat",
        borderwidth=0,
        highlightbackground=BG,
        highlightcolor=FG,
        height=0,
        pady=12,
        **kwargs,
    )


def selection_images(parent):
    images = []
    for selected in (False, True):
        image = tk.PhotoImage(master=parent, width=32, height=24)
        for rectangle in (
            (2, 2, 22, 4),
            (2, 20, 22, 22),
            (2, 4, 4, 20),
            (20, 4, 22, 20),
        ):
            image.put(MUTED, to=rectangle)
        if selected:
            image.put(FG, to=(7, 7, 17, 17))
        images.append(image)
    return images


class Scrollbar(tk.Canvas):
    def __init__(self, parent, command):
        super().__init__(parent, width=6, bg=BG, highlightthickness=0)
        self.command = command
        self.first, self.last = 0.0, 1.0
        self.offset = 0
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", self.press)
        self.bind("<B1-Motion>", self.drag)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def draw(self):
        self.delete("all")
        if self.last - self.first < 1:
            height = self.winfo_height()
            self.create_rectangle(
                1,
                self.first * height,
                5,
                self.last * height,
                fill=MUTED,
                outline="",
            )

    def press(self, event):
        height = max(1, self.winfo_height())
        if self.first * height <= event.y <= self.last * height:
            self.offset = event.y - self.first * height
        else:
            self.offset = (self.last - self.first) * height / 2
            self.drag(event)

    def drag(self, event):
        fraction = (event.y - self.offset) / max(1, self.winfo_height())
        self.command(
            "moveto", max(0, min(self.first + 1 - self.last, fraction))
        )


def error_window(message):
    root = window("deckkit", height=480)
    wordmark(root).grid(row=0, column=0, sticky="w", padx=34, pady=28)
    label(root, message, 24, wraplength=840).grid(
        row=1, column=0, sticky="nsew", padx=34, pady=24
    )
    root.rowconfigure(1, weight=1)
    button(root, "Close", root.destroy, True).grid(
        row=2, column=0, sticky="ew", padx=34, pady=28
    )
    root.bind("<Return>", lambda _: root.destroy())
    root.bind("<Escape>", lambda _: root.destroy())
    root.mainloop()
