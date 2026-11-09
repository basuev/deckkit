"""Export the editable gridmark as a wide, flat wordmark."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "assets/branding/deckkit.gridmark.json"
    cells = {
        tuple(map(int, key.split(":")))
        for key in json.loads(source.read_text())["document"]["cells"]
    }
    left = min(x for x, y in cells)
    top = min(y for x, y in cells)
    right = max(x for x, y in cells)
    bottom = max(y for x, y in cells)
    width, height = (right - left + 1) * 7, (bottom - top + 1) * 4
    paths = []
    for y in range(top, bottom + 1):
        x = left
        while x <= right:
            if (x, y) not in cells:
                x += 1
                continue
            start = x
            x += 1
            while (x, y) in cells:
                x += 1
            run_width = (x - start) * 7
            paths.append(
                f"M{(start - left) * 7},{(y - top) * 4}"
                f"h{run_width}v4h-{run_width}z"
            )
    svg = ROOT / "assets/branding/deckkit.svg"
    svg.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<path fill="#f1f1f1" d="{"".join(paths)}"/></svg>\n'
    )
    subprocess.run(
        ["rsvg-convert", "-o", str(ROOT / "assets/wordmark.png"), str(svg)],
        check=True,
    )


if __name__ == "__main__":
    main()
