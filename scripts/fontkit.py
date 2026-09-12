"""
Embed a subset of Liberation Mono into an SVG as a base64 @font-face.

Why bother: the ASCII grid bakes in a character advance of exactly 0.600 em.
Liberation Mono, DejaVu Sans Mono and Noto Sans Mono all measure 0.600 -- but
Consolas, which is what a Windows visitor's "monospace" usually resolves to,
is nearer 0.55. Without an embedded face the portrait's geometry depends on
whoever is looking at it.

An external font URL cannot fix this: these SVGs load through an <img> tag,
and browsers refuse subresource fetches for image documents. A @font-face
whose src is a base64 data: URI does work, because nothing is fetched.

Every SVG therefore carries its own copy, so each one is subset to exactly the
characters it uses -- 13 glyphs for the portrait ramp, a few dozen for the
cards. A full TTF would be ~300 KB per file; these come out around 1-3 KB.

Liberation Mono is SIL OFL 1.1. fonts/LICENSE.txt travels with it.
"""
from __future__ import annotations

import base64
import io
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
REGULAR = FONTS / "LiberationMono-Regular.ttf"
BOLD = FONTS / "LiberationMono-Bold.ttf"

FAMILY = "ProfileMono"
# Advance width the ASCII grid assumes, in em. Liberation Mono is exactly this.
ADVANCE_EM = 0.600

# What to fall back to if the embedded face somehow fails to load.
FALLBACK = ("ui-monospace,'SFMono-Regular',Menlo,Consolas,"
            "'DejaVu Sans Mono','Liberation Mono',monospace")
STACK = f"'{FAMILY}',{FALLBACK}"


class FontUnavailable(RuntimeError):
    """Raised when fonttools or the font files are missing."""


def _subset_b64(path: pathlib.Path, chars: str) -> str:
    try:
        from fontTools.subset import Options, Subsetter
        from fontTools.ttLib import TTFont
    except ImportError as exc:  # pragma: no cover
        raise FontUnavailable("fonttools is not installed") from exc

    if not path.exists():
        raise FontUnavailable(f"missing font file: {path}")

    font = TTFont(str(path))
    opts = Options()
    opts.layout_features = []          # no kerning/ligatures needed in mono
    opts.hinting = False
    opts.notdef_outline = False
    opts.desubroutinize = True
    opts.drop_tables += ["DSIG", "FFTM"]

    sub = Subsetter(options=opts)
    sub.populate(text="".join(sorted(set(chars))))
    sub.subset(font)

    font.flavor = "woff2"              # needs brotli
    buf = io.BytesIO()
    font.save(buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def face_css(regular_chars: str, bold_chars: str = "") -> str:
    """@font-face rules covering exactly the characters passed in.

    Returns "" if the toolchain or font files are unavailable, so a generator
    can always fall back to the plain system-monospace stack rather than fail.
    """
    rules = []
    try:
        if regular_chars.strip():
            b64 = _subset_b64(REGULAR, regular_chars)
            rules.append(
                f"@font-face{{font-family:'{FAMILY}';font-style:normal;"
                f"font-weight:400;src:url(data:font/woff2;base64,{b64}) "
                f"format('woff2');}}"
            )
        if bold_chars.strip():
            b64 = _subset_b64(BOLD, bold_chars)
            rules.append(
                f"@font-face{{font-family:'{FAMILY}';font-style:normal;"
                f"font-weight:700;src:url(data:font/woff2;base64,{b64}) "
                f"format('woff2');}}"
            )
    except FontUnavailable as exc:
        print(f"  font       : not embedded ({exc}); using the system stack")
        return ""

    total = sum(len(r) for r in rules)
    glyphs = len(set(regular_chars) | set(bold_chars))
    print(f"  font       : embedded {len(rules)} face(s), {glyphs} glyphs, "
          f"~{total // 1024} KB base64")
    return "".join(rules)


def text_chars(svg_fragments: "list[str] | str") -> str:
    """Every character that will actually be painted as text in an SVG.

    Scanning the assembled markup rather than tracking strings by hand means a
    glyph can never be rendered without being in the subset -- the failure mode
    that would otherwise show up as one stray character in a fallback font.
    """
    import re

    body = svg_fragments if isinstance(svg_fragments, str) else "".join(svg_fragments)
    found: set[str] = set()
    for chunk in re.findall(r">([^<>]*)<", body):
        chunk = (chunk.replace("&#183;", "·").replace("&amp;", "&")
                      .replace("&lt;", "<").replace("&gt;", ">"))
        found.update(chunk)
    found.discard("\n")
    return "".join(sorted(found))
