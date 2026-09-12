#!/usr/bin/env python3
"""
Stage 1 of the portrait pipeline: photo -> clean grayscale plate.

A flatly-lit face converts to a dark, unreadable ASCII blob. Three steps fix it:

  1. Isolate the subject      (rembg if installed, else a border flood-fill)
  2. Boost local contrast     (OpenCV CLAHE if installed, else a numpy CLAHE)
  3. Composite onto pure white so the background lands on the blank end of the
     ASCII ramp -- white becomes spaces, and only the subject prints.

Run this once per photo:

    python scripts/prep_photo.py source-photo.jpg

Writes source-prepped.png next to the repo root.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageOps

# Optional accelerators -- both are detected, never required.
try:
    import cv2
except ImportError:
    cv2 = None
try:
    from rembg import remove as rembg_remove
except ImportError:
    rembg_remove = None


# ----------------------------------------------------------------- background


def cut_out_subject(img: Image.Image, tolerance: int) -> Image.Image:
    """Return RGBA with the background made transparent."""
    if rembg_remove is not None:
        print("  background : rembg")
        return rembg_remove(img.convert("RGBA"))

    # Fallback: flood-fill inward from every border pixel. Works well for the
    # seamless studio backdrops that portraits are usually shot against.
    print("  background : border flood-fill (install rembg for a cleaner cut)")
    rgba = img.convert("RGBA")
    w, h = rgba.size
    flat = rgba.convert("RGB")
    px = np.array(flat, dtype=np.int16)

    # The backdrop colour is whatever dominates the border. Seeding from every
    # border pixel is wrong whenever the subject reaches an edge: on a bust
    # shot the bottom corners are shoulder, not backdrop, and a fill started
    # there floods the whole garment and erases it.
    border = np.concatenate([px[0, :], px[-1, :], px[:, 0], px[:, -1]])
    backdrop = np.median(border, axis=0)

    # Sentinel colour that cannot collide with real pixel data.
    sentinel = (1, 254, 1)
    candidates = (
        [(x, 0) for x in range(0, w, 8)]
        + [(x, h - 1) for x in range(0, w, 8)]
        + [(0, y) for y in range(0, h, 8)]
        + [(w - 1, y) for y in range(0, h, 8)]
    )
    seeded = 0
    for sx, sy in candidates:
        here = px[sy, sx]
        if np.abs(here - backdrop).max() > tolerance:
            continue          # this edge pixel is subject, not backdrop
        if flat.getpixel((sx, sy)) == sentinel:
            continue          # already swallowed by an earlier fill
        ImageDraw.floodfill(flat, (sx, sy), sentinel, thresh=tolerance)
        seeded += 1
    print(f"             backdrop rgb {tuple(int(v) for v in backdrop)}, "
          f"{seeded}/{len(candidates)} edge seeds used")

    mask = np.array(flat) == np.array(sentinel, dtype=np.uint8)
    background = mask.all(axis=2)
    alpha = np.array(rgba)[:, :, 3]
    alpha[background] = 0
    out = np.dstack([np.array(rgba)[:, :, :3], alpha])
    return Image.fromarray(out, "RGBA")


# ------------------------------------------------------------------- contrast


def clahe_numpy(gray: np.ndarray, clip_limit: float = 2.0, tiles: int = 8) -> np.ndarray:
    """Contrast-limited adaptive histogram equalisation, pure numpy.

    Builds a clipped-histogram lookup table per tile, then bilinearly
    interpolates between the four nearest tile LUTs for every pixel -- which is
    what stops the tiling from showing up as visible seams.
    """
    h, w = gray.shape
    ty, tx = max(1, h // tiles), max(1, w // tiles)
    luts = np.zeros((tiles, tiles, 256), dtype=np.float32)

    for i in range(tiles):
        for j in range(tiles):
            y0, y1 = i * ty, (i + 1) * ty if i < tiles - 1 else h
            x0, x1 = j * tx, (j + 1) * tx if j < tiles - 1 else w
            tile = gray[y0:y1, x0:x1]
            hist = np.bincount(tile.ravel(), minlength=256).astype(np.float32)
            # Clip tall bins and redistribute the excess evenly.
            limit = max(1.0, clip_limit * tile.size / 256.0)
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = np.cumsum(hist)
            cdf = (cdf - cdf[0]) / max(cdf[-1] - cdf[0], 1e-6)
            luts[i, j] = cdf * 255.0

    # Tile-space coordinate of every pixel, offset to tile centres.
    yy = np.clip(np.arange(h, dtype=np.float32) / ty - 0.5, 0, tiles - 1)
    xx = np.clip(np.arange(w, dtype=np.float32) / tx - 0.5, 0, tiles - 1)
    i0 = np.floor(yy).astype(int)
    j0 = np.floor(xx).astype(int)
    i1 = np.minimum(i0 + 1, tiles - 1)
    j1 = np.minimum(j0 + 1, tiles - 1)
    wy = (yy - i0)[:, None]
    wx = (xx - j0)[None, :]

    g = gray
    tl = luts[i0[:, None], j0[None, :], g]
    tr = luts[i0[:, None], j1[None, :], g]
    bl = luts[i1[:, None], j0[None, :], g]
    br = luts[i1[:, None], j1[None, :], g]
    out = (
        tl * (1 - wy) * (1 - wx)
        + tr * (1 - wy) * wx
        + bl * wy * (1 - wx)
        + br * wy * wx
    )
    return np.clip(out, 0, 255).astype(np.uint8)


def boost_contrast(gray: np.ndarray, clip_limit: float,
                   strength: float) -> np.ndarray:
    """CLAHE, blended back toward the original by `strength`.

    On its own CLAHE wrecks large flat dark areas: a tile that is almost
    entirely black has only a sliver of variation, and equalising it stretches
    that sliver across the full range -- which turns a black hoodie into a
    white one. Blending back toward the original luma keeps the global
    tonality while still lifting local detail in the face.
    """
    if cv2 is not None:
        print(f"  contrast   : OpenCV CLAHE (strength {strength})")
        eq = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8)).apply(gray)
    else:
        print(f"  contrast   : numpy CLAHE (strength {strength})")
        eq = clahe_numpy(gray, clip_limit=clip_limit)

    s = float(np.clip(strength, 0.0, 1.0))
    blended = gray.astype(np.float32) * (1.0 - s) + eq.astype(np.float32) * s
    return np.clip(blended, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------- main


def prep(
    src: pathlib.Path,
    dst: pathlib.Path,
    clip_limit: float = 2.0,
    strength: float = 0.55,
    tolerance: int = 32,
    keep_background: bool = False,
    gamma: float = 1.0,
    background: str = "white",
) -> None:
    img = ImageOps.exif_transpose(Image.open(src))
    print(f"  source     : {src} ({img.width}x{img.height})")

    rgba = img.convert("RGBA") if keep_background else cut_out_subject(img, tolerance)

    arr = np.array(rgba, dtype=np.float32)
    rgb, alpha = arr[:, :, :3], arr[:, :, 3:4] / 255.0

    # Luma before compositing, so the white background cannot skew the
    # histogram that CLAHE is about to equalise.
    luma = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2])
    boosted = boost_contrast(luma.astype(np.uint8), clip_limit,
                             strength).astype(np.float32)

    if gamma != 1.0:
        boosted = 255.0 * np.power(np.clip(boosted / 255.0, 0, 1), gamma)
        print(f"  gamma      : {gamma}")

    # Alpha-over a flat ground. Which ground depends on how the ASCII will be
    # read: on white (with the default ramp) the dark features become the ink,
    # giving a negative/line-drawing look; on black (with --invert) glyph
    # density tracks emitted light, so the portrait reads like the photo on a
    # dark terminal. Either way the ground itself maps to the blank glyph.
    ground = 0.0 if background == "black" else 255.0
    composited = boosted * alpha[:, :, 0] + ground * (1.0 - alpha[:, :, 0])
    out = Image.fromarray(np.clip(composited, 0, 255).astype(np.uint8), "L")
    out.save(dst)
    print(f"  wrote      : {dst} ({out.width}x{out.height})")


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", nargs="?", default=str(root / "source-photo.jpg"),
                    help="input photo (default: source-photo.jpg)")
    ap.add_argument("-o", "--out", default=str(root / "source-prepped.png"))
    ap.add_argument("--clip-limit", type=float, default=2.0,
                    help="CLAHE clip limit; raise for flatter photos (default 2.0)")
    ap.add_argument("--strength", type=float, default=0.55,
                    help="how far to blend toward the CLAHE result, 0-1. "
                         "Lower it if large dark areas wash out (default 0.55)")
    ap.add_argument("--tolerance", type=int, default=32,
                    help="flood-fill tolerance when rembg is absent (default 32)")
    ap.add_argument("--keep-background", action="store_true",
                    help="skip subject isolation entirely")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help=">1 darkens midtones, <1 lightens them (default 1.0)")
    ap.add_argument("--background", choices=("white", "black"), default="white",
                    help="ground to composite onto. Use black together with "
                         "make_ascii_svg.py --invert for a dark terminal")
    args = ap.parse_args()

    src = pathlib.Path(args.photo)
    if not src.exists():
        print(f"error: no such photo: {src}", file=sys.stderr)
        print("Drop your photo in the repo root as source-photo.jpg, or pass a path.",
              file=sys.stderr)
        return 1

    print("prep_photo")
    prep(src, pathlib.Path(args.out), args.clip_limit, args.strength,
         args.tolerance, args.keep_background, args.gamma, args.background)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
