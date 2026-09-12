#!/usr/bin/env python3
"""
Hand-author the neofetch-style info card.

Looks like the output of `neofetch`: a title bar, a rule, then colour-coded
key/value rows, and the palette strip neofetch always prints at the bottom.
Each line fades and slides in on a short stagger, so the panel reads as
printing next to the portrait.

Content lives in data/profile.json -- edit that, not this file. Keep the
story here and the numbers in the heatmap: the graph already covers your
GitHub stats, so the card is for what numbers cannot say.

    python scripts/make_info_card.py            # -> info-card.svg
    STATIC=1 python scripts/make_info_card.py   # frozen frame for previewing
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from svgcheck import write_checked  # noqa: E402
import fontkit  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

BG = "#0d1117"
BORDER = "#21262d"
KEY = "#39d353"
VALUE = "#c9d1d9"
DIM = "#7d8590"
TITLE = "#58a6ff"
DOTS = ("#ff5f56", "#ffbd2e", "#27c93f")
PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641",
           "#39d353", "#69f0a0", "#58a6ff", "#c9d1d9"]

FONT = fontkit.STACK

FONT_SIZE = 13.0
LINE_H = 23.0
PAD_X = 20.0
CHAR_W = FONT_SIZE * fontkit.ADVANCE_EM


def build(cfg: dict, width: float, stagger: float, static: bool) -> str:
    card = cfg.get("card", {})
    title = card.get("title") or f'{cfg.get("username", "user")}@github'
    rows = [(str(k), str(v)) for k, v in card.get("rows", [])]

    key_w = max((len(k) for k, _ in rows), default=4)
    top = 62.0
    height = top + len(rows) * LINE_H + 58

    css = f"""
    text {{ font-size:{FONT_SIZE}px; }}
    .k {{ fill:{KEY}; }}
    .v {{ fill:{VALUE}; }}
    .d {{ fill:{DIM}; }}
    .t {{ fill:{TITLE}; font-weight:600; }}
    """
    if not static:
        # translateX only -- independent of transform-origin, so it renders
        # the same everywhere without needing transform-box support.
        css += """
    @keyframes in { from { opacity:0; transform:translateX(-8px); }
                      to { opacity:1; transform:translateX(0); } }
    /* backwards, so that a renderer ignoring @keyframes shows the finished
       card instead of an empty panel. See render_heatmap_svg.py. */
    .a { animation:in .42s ease-out backwards; }
    """

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="{FONT}" role="img" '
        f'aria-label="Terminal-style profile info card">',
        f"<style>{css}</style>",
        f'<rect width="{width:.0f}" height="{height:.0f}" rx="10" fill="{BG}" '
        f'stroke="{BORDER}"/>',
    ]

    def a(delay: float, extra: str = "") -> str:
        cls = extra.strip()
        if static:
            return f' class="{cls}"' if cls else ""
        return f' class="{(cls + " a").strip()}" style="animation-delay:{delay:.2f}s"'

    # Window chrome.
    for i, colour in enumerate(DOTS):
        out.append(f'<circle cx="{PAD_X + i * 18:.0f}" cy="22" r="5.5" '
                   f'fill="{colour}"{a(0.04 + i * 0.05)}/>')
    out.append(f'<text x="{PAD_X + 68:.0f}" y="26"{a(0.2, "t")}>{escape(title)}</text>')
    out.append(f'<line x1="{PAD_X:.0f}" y1="40" x2="{width - PAD_X:.0f}" y2="40" '
               f'stroke="{BORDER}"{a(0.26)}/>')

    # Key / value rows, keys padded to a fixed column so values line up.
    for i, (key, value) in enumerate(rows):
        y = top + i * LINE_H
        delay = 0.34 + i * stagger
        vx = PAD_X + (key_w + 3) * CHAR_W
        out.append(
            f'<text x="{PAD_X:.0f}" y="{y:.1f}"{a(delay)} xml:space="preserve">'
            f'<tspan class="k">{escape(key)}</tspan>'
            f'<tspan class="d">{escape(" " * (key_w - len(key)))} : </tspan>'
            f'</text>'
        )
        out.append(f'<text x="{vx:.1f}" y="{y:.1f}"{a(delay + 0.04, "v")}>'
                   f'{escape(value)}</text>')

    # neofetch always signs off with a palette strip.
    py = top + len(rows) * LINE_H + 14
    tail = 0.34 + len(rows) * stagger + 0.1
    for i, colour in enumerate(PALETTE):
        out.append(f'<rect x="{PAD_X + i * 22:.0f}" y="{py:.1f}" width="18" '
                   f'height="10" rx="2" fill="{colour}"'
                   f'{a(tail + i * 0.04)}/>')

    out.append("</svg>")
    # Only the title is bold, so the 700 subset stays tiny.
    css = fontkit.face_css(fontkit.text_chars(out), title)
    if css:
        out.insert(1, f"<style>{css}</style>")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=str(ROOT / "data" / "profile.json"))
    ap.add_argument("-o", "--out", default=str(ROOT / "info-card.svg"))
    ap.add_argument("--width", type=float, default=560.0)
    ap.add_argument("--stagger", type=float, default=0.1)
    ap.add_argument("--static", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(pathlib.Path(args.config).read_text())
    svg = build(cfg, args.width, args.stagger,
                args.static or os.environ.get("STATIC") == "1")
    write_checked(args.out, svg)
    print(f"make_info_card: wrote {args.out} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
