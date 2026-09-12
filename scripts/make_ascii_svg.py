#!/usr/bin/env python3
"""
Stage 2 of the portrait pipeline: grayscale plate -> self-typing ASCII SVG.

The prepped image is downsampled to a character grid and each cell's brightness
picks a glyph from a density ramp -- sparse glyphs for bright areas, dense ones
for dark. Two choices keep it clean rather than noisy:

  * Monochrome. One fill colour. Per-character rainbow colouring is exactly
    what makes most ASCII portraits look like static.
  * High contrast. A washed-out background maps to the space glyph, so only
    the subject prints.

Each row lives inside a horizontal clip that wipes left-to-right with a block
cursor riding the wipe edge, staggered top to bottom. The portrait prints once
and freezes -- no looping. It is SMIL inside the SVG, so GitHub plays it.

    python scripts/make_ascii_svg.py          # -> ascii-portrait.svg
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from svgcheck import write_checked  # noqa: E402
import fontkit  # noqa: E402

# Bright (sparse) -> dark (dense). The leading space clears the background
# to nothing, which is what keeps the portrait floating rather than boxed.
RAMP = " .`:-=+*cs#%@"

# Terminal ground. Embedded SVGs cannot see the reader's GitHub theme, so the
# art carries its own dark background and reads identically in light and dark.
BG = "#0d1117"
FG = "#c9d1d9"
CURSOR = "#39d353"

FONT_SIZE = 12.0
# The grid's advance width. An embedded subset guarantees this is what the
# reader's browser actually uses, rather than whatever its "monospace" is.
CELL_W = FONT_SIZE * fontkit.ADVANCE_EM
CELL_H = FONT_SIZE * 1.05
FONT_STACK = fontkit.STACK


def autocrop(gray: np.ndarray, threshold: int = 246, pad: int = 6) -> np.ndarray:
    """Trim the blank margin so the subject fills the character grid."""
    subject = gray < threshold
    if not subject.any():
        return gray
    rows = np.where(subject.any(axis=1))[0]
    cols = np.where(subject.any(axis=0))[0]
    y0, y1 = max(rows[0] - pad, 0), min(rows[-1] + pad + 1, gray.shape[0])
    x0, x1 = max(cols[0] - pad, 0), min(cols[-1] + pad + 1, gray.shape[1])
    return gray[y0:y1, x0:x1]


def to_rows(img_path: pathlib.Path, cols: int, rows: int | None,
            invert: bool, no_crop: bool,
            black_point: float = 0.02, white_point: float = 0.96) -> list[str]:
    gray = np.array(Image.open(img_path).convert("L"))
    if not no_crop:
        gray = autocrop(gray)

    if rows is None:
        # Character cells are taller than they are wide, so the row count has
        # to be scaled by the cell aspect or the face comes out stretched.
        aspect = gray.shape[0] / gray.shape[1]
        rows = max(1, int(round(cols * aspect * (CELL_W / CELL_H))))

    small = np.array(
        Image.fromarray(gray).resize((cols, rows), Image.Resampling.LANCZOS),
        dtype=np.float32,
    ) / 255.0

    # Levels. Pulling the white point below 1.0 snaps the near-white
    # background to pure white so it lands on the space glyph -- without it
    # a backdrop that is merely light stipples the whole portrait with dots.
    span = max(white_point - black_point, 1e-6)
    small = np.clip((small - black_point) / span, 0.0, 1.0)

    if invert:
        small = 1.0 - small

    # Bright pixels -> index 0 (space); dark pixels -> the densest glyph.
    idx = np.clip(((1.0 - small) * (len(RAMP) - 1)).round().astype(int),
                  0, len(RAMP) - 1)
    return ["".join(RAMP[i] for i in row) for row in idx]


def build_svg(text_rows: list[str], stagger: float, row_dur: float,
              static: bool) -> str:
    cols = max((len(r) for r in text_rows), default=0)
    width = round(cols * CELL_W + 24, 2)
    height = round(len(text_rows) * CELL_H + 24, 2)

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="{FONT_STACK}" role="img" '
        f'aria-label="ASCII art portrait rendered as terminal text">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        f'<g font-size="{FONT_SIZE}" fill="{FG}" '
        f'style="white-space:pre" xml:space="preserve">',
    ]

    for i, raw in enumerate(text_rows):
        trimmed = raw.rstrip()
        if not trimmed:
            continue

        # Leading blanks become an x offset rather than leading spaces in the
        # element. textLength with lengthAdjust="spacing" redistributes width
        # across the glyphs it is given, so a row that still carries its
        # indent as spaces gets a different per-character advance than one
        # that does not -- which shears the portrait row by row.
        body = trimmed.lstrip()
        indent = len(trimmed) - len(body)
        x = round(12 + indent * CELL_W, 2)
        run = round(len(body) * CELL_W, 2)
        end = round(x + run, 2)

        y = round(12 + (i + 1) * CELL_H, 2)
        begin = round(i * stagger, 3)

        if static:
            out.append(
                f'<text x="{x}" y="{y}" textLength="{run}" '
                f'lengthAdjust="spacing">{escape(body)}</text>'
            )
            continue

        # The wipe always starts at the left margin so every row reveals in
        # step, even though the glyphs themselves begin further in.
        clip = f"w{i}"
        out.append(
            f'<clipPath id="{clip}">'
            # The clip rect's base width is the FULL row, so a renderer that
            # ignores SMIL shows the finished portrait instead of clipping
            # every row away to nothing.
            #
            # SMIL has no animation-fill-mode:backwards, though: before its
            # begin time an <animate> leaves the base value showing, which
            # would flash the whole portrait and then blink it out row by row.
            # The <set> collapses the row to 0 at t=0 and holds it; the
            # <animate> is later in document order, so it takes over the
            # attribute once it begins and freezes at full width.
            f'<rect x="12" y="{round(y - CELL_H, 2)}" '
            f'height="{round(CELL_H + 4, 2)}" width="{round(end - 12, 2)}">'
            f'<set attributeName="width" to="0" begin="0s"/>'
            f'<animate attributeName="width" from="0" to="{round(end - 12, 2)}" '
            f'begin="{begin}s" dur="{row_dur}s" fill="freeze"/>'
            f'</rect></clipPath>'
        )
        out.append(
            f'<text x="{x}" y="{y}" textLength="{run}" lengthAdjust="spacing" '
            f'clip-path="url(#{clip})">{escape(body)}</text>'
        )
        # Block cursor riding the wipe edge, gone once the row has printed.
        out.append(
            f'<rect y="{round(y - CELL_H + 2.5, 2)}" width="{round(CELL_W, 2)}" '
            f'height="{round(CELL_H - 2, 2)}" fill="{CURSOR}" opacity="0">'
            f'<animate attributeName="x" from="12" to="{end}" '
            f'begin="{begin}s" dur="{row_dur}s" fill="freeze"/>'
            f'<animate attributeName="opacity" values="0;1;1;0" '
            f'keyTimes="0;0.01;0.92;1" begin="{begin}s" dur="{row_dur}s" '
            f'fill="freeze"/>'
            f'</rect>'
        )

    out.append("</g></svg>")
    # The ramp is 13 glyphs, so the embedded face costs about 1 KB.
    css = fontkit.face_css("".join(text_rows))
    if css:
        out.insert(1, f"<style>{css}</style>")
    return "\n".join(out)


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--image", default=str(root / "source-prepped.png"))
    ap.add_argument("-o", "--out", default=str(root / "ascii-portrait.svg"))
    ap.add_argument("--cols", type=int, default=100)
    ap.add_argument("--rows", type=int, default=None,
                    help="default: derived from the image aspect ratio")
    ap.add_argument("--stagger", type=float, default=0.045,
                    help="seconds between consecutive row reveals")
    ap.add_argument("--row-dur", type=float, default=0.5,
                    help="seconds for one row to wipe in")
    ap.add_argument("--invert", action="store_true",
                    help="flip the ramp (for light-background terminals)")
    ap.add_argument("--black-point", type=float, default=0.02,
                    help="tones at or below this fraction go fully dark")
    ap.add_argument("--white-point", type=float, default=0.96,
                    help="tones at or above this fraction go fully blank")
    ap.add_argument("--no-crop", action="store_true")
    ap.add_argument("--static", action="store_true",
                    help="emit a frozen frame (also via STATIC=1)")
    ap.add_argument("--print-text", action="store_true",
                    help="dump the ASCII to stdout to eyeball the tuning")
    args = ap.parse_args()

    import os
    static = args.static or os.environ.get("STATIC") == "1"

    img = pathlib.Path(args.image)
    if not img.exists():
        print(f"error: no prepped image at {img}", file=sys.stderr)
        print("Run scripts/prep_photo.py first.", file=sys.stderr)
        return 1

    rows = to_rows(img, args.cols, args.rows, args.invert, args.no_crop,
                   args.black_point, args.white_point)
    if args.print_text:
        print("\n".join(rows))

    svg = build_svg(rows, args.stagger, args.row_dur, static)
    write_checked(args.out, svg)
    print(f"make_ascii_svg: wrote {args.out} "
          f"({args.cols}x{len(rows)} chars, {len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
