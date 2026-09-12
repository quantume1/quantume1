#!/usr/bin/env python3
"""
Draw a stand-in portrait plate so the profile renders before a real photo exists.

This is NOT a substitute for your photo -- it is a procedurally drawn bust
(hair mass, sunglasses, beard, hoodie) that keeps the README complete until
you run the real pipeline:

    python scripts/prep_photo.py source-photo.jpg
    python scripts/make_ascii_svg.py

Writes source-prepped.png in the same grayscale-on-white form prep_photo.py
produces, so make_ascii_svg.py consumes it identically.
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np

W, H = 900, 1000
rng = np.random.default_rng(7)

yy, xx = np.mgrid[0:H, 0:W]


def ellipse(cx, cy, rx, ry, soft=1.0):
    """Soft-edged ellipse mask in [0,1]."""
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    return np.clip((1.0 - d) / max(soft * 0.06, 1e-6), 0.0, 1.0)


def rrect(x0, y0, x1, y1, r, soft=2.0):
    """Soft-edged rounded rectangle mask in [0,1]."""
    cx = np.clip(xx, x0 + r, x1 - r)
    cy = np.clip(yy, y0 + r, y1 - r)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return np.clip((r - d) / max(soft, 1e-6), 0.0, 1.0)


def over(base, mask, value):
    """Alpha-composite a flat tone through a mask."""
    return base * (1 - mask) + value * mask


def build() -> np.ndarray:
    # Pure white, not near-white: anything below the white point prints a
    # glyph, so a 238 backdrop fills the portrait with dot noise.
    img = np.full((H, W), 255.0)

    cx, cy = W * 0.50, H * 0.42            # face centre
    fw, fh = W * 0.225, H * 0.225          # face radii

    # --- neck, then hoodie over it ----------------------------------------
    # Order matters: the hoodie has to paint after the neck, or the neck tone
    # shows through as a light band running down the chest.
    neck = rrect(cx - fw * 0.62, cy + fh * 0.55, cx + fw * 0.62, H * 0.94, 40, soft=18)
    img = over(img, neck, 126.0)
    jaw_shadow = ellipse(cx, cy + fh * 0.95, fw * 0.80, fh * 0.34)
    img = over(img, jaw_shadow, 92.0)

    shoulders = ellipse(cx, H * 1.18, W * 0.60, H * 0.40)
    img = over(img, shoulders, 26.0)
    hood = ellipse(cx, H * 0.97, W * 0.40, H * 0.25)
    img = over(img, hood, 20.0)

    # --- face -------------------------------------------------------------
    face = ellipse(cx, cy, fw, fh, soft=1.6)
    img = over(img, face, 188.0)
    # Directional light from upper-left.
    shade = np.clip((xx - cx) / (fw * 2.1) + (yy - cy) / (fh * 3.4), -1, 1)
    img -= face * np.clip(shade, 0, 1) * 46

    # --- hair -------------------------------------------------------------
    # A tall, wide mass sitting above and around the skull, with noise so the
    # ASCII ramp resolves it as curl texture rather than a flat slab.
    curl = rng.normal(0, 1, (H, W))
    curl = (curl + np.roll(curl, 3, 0) + np.roll(curl, -3, 1)) / 3.0
    hair = ellipse(cx, cy - fh * 0.62, fw * 1.20, fh * 0.86, soft=2.2)
    hair = np.clip(hair - ellipse(cx, cy + fh * 0.30, fw * 0.95, fh * 0.80) * 0.92, 0, 1)
    img = over(img, hair, 34.0)
    img += hair * curl * 22

    sideburn_l = ellipse(cx - fw * 0.88, cy + fh * 0.02, fw * 0.14, fh * 0.34)
    sideburn_r = ellipse(cx + fw * 0.88, cy + fh * 0.02, fw * 0.14, fh * 0.34)
    sideburns = np.clip(sideburn_l + sideburn_r, 0, 1) * face
    img = over(img, sideburns * 0.85, 52.0)

    # --- sunglasses -------------------------------------------------------
    ey = cy - fh * 0.16
    lens_l = ellipse(cx - fw * 0.44, ey, fw * 0.40, fh * 0.24, soft=1.1)
    lens_r = ellipse(cx + fw * 0.44, ey, fw * 0.40, fh * 0.24, soft=1.1)
    lenses = np.clip(lens_l + lens_r, 0, 1)
    img = over(img, lenses, 18.0)
    # Frame + bridge, a touch lighter than the lenses.
    frame = np.clip(ellipse(cx - fw * 0.44, ey, fw * 0.46, fh * 0.29)
                    + ellipse(cx + fw * 0.44, ey, fw * 0.46, fh * 0.29), 0, 1)
    img = over(img, np.clip(frame - lenses, 0, 1), 96.0)
    bridge = rrect(cx - fw * 0.12, ey - fh * 0.05, cx + fw * 0.12, ey + fh * 0.01, 4)
    img = over(img, bridge, 96.0)
    # Specular highlight on the left lens.
    img += lens_l * ellipse(cx - fw * 0.56, ey - fh * 0.10, fw * 0.14, fh * 0.07) * 70

    # --- nose, lips, beard ------------------------------------------------
    img -= ellipse(cx + fw * 0.10, cy + fh * 0.30, fw * 0.15, fh * 0.16) * 34
    nostrils = np.clip(ellipse(cx - fw * 0.13, cy + fh * 0.40, fw * 0.05, fh * 0.035)
                       + ellipse(cx + fw * 0.13, cy + fh * 0.40, fw * 0.05, fh * 0.035), 0, 1)
    img = over(img, nostrils, 74.0)

    beard = ellipse(cx, cy + fh * 0.72, fw * 0.82, fh * 0.50)
    beard = np.clip(beard - ellipse(cx, cy + fh * 0.20, fw * 0.70, fh * 0.36) * 0.85, 0, 1)
    moustache = ellipse(cx, cy + fh * 0.53, fw * 0.34, fh * 0.09)
    beard = np.clip(beard + moustache, 0, 1)
    img = over(img, beard * 0.88, 74.0)
    img += beard * curl * 16

    lips = ellipse(cx, cy + fh * 0.68, fw * 0.26, fh * 0.085)
    img = over(img, lips, 122.0)
    img = over(img, ellipse(cx, cy + fh * 0.68, fw * 0.26, fh * 0.012), 78.0)

    # --- phone held at the bottom edge ------------------------------------
    phone = rrect(cx - W * 0.105, H * 0.925, cx + W * 0.105, H, 18, soft=3)
    img = over(img, phone, 28.0)
    img = over(img, rrect(cx - W * 0.085, H * 0.945, cx - W * 0.035, H * 0.995, 10), 62.0)

    return np.clip(img, 0, 255)


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=str(root / "source-prepped.png"))
    ap.add_argument("--print-text", action="store_true")
    args = ap.parse_args()

    from PIL import Image
    img = build().astype(np.uint8)
    Image.fromarray(img, "L").save(args.out)
    print(f"make_placeholder_photo: wrote {args.out} (stand-in, replace with your photo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
