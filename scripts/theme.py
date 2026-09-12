"""Colours and chrome shared by every generated graphic.

Kept in one place so the four SVGs cannot drift apart. Each graphic paints its
own dark ground: an SVG embedded through <img> cannot see the reader's GitHub
theme, so a single fill colour would vanish in one mode or the other.
"""
from __future__ import annotations

BG = "#0d1117"
BORDER = "#21262d"
TEXT = "#7d8590"
TEXT_BRIGHT = "#c9d1d9"
TITLE = "#58a6ff"
ACCENT = "#39d353"

# none -> brightest. Level 5 is a neon top end for a personal best.
PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353", "#69f0a0"]

# Same ramp the portrait draws with, reused by the year strip.
RAMP = " .`:-=+*cs#%@"


def anim(base: str, delay: float, static: bool) -> str:
    """class + animation-delay as a single attribute pair.

    They have to be emitted together: a second class attribute on the same
    element is a duplicate-attribute XML error and browsers then refuse to
    render the document at all.
    """
    if static:
        return f'class="{base}"'
    return f'class="{base} chr" style="animation-delay:{delay:.2f}s"'


def keyframes(static: bool) -> str:
    """Reveal animation, written so that ignoring it shows the finished state.

    animation-fill-mode is backwards and no rule sets opacity:0, so during the
    delay the element takes the keyframe's from-state and afterwards falls back
    to its own visible style. A renderer that skips @keyframes shows the
    finished graphic rather than a blank panel.
    """
    if static:
        return ""
    return """
    @keyframes rise { from { opacity:0; transform:translateY(-8px); }
                        to { opacity:1; transform:translateY(0); } }
    @keyframes grow { from { opacity:0; transform:scaleX(0); }
                        to { opacity:1; transform:scaleX(1); } }
    .chr  { animation:rise .45s ease-out backwards; }
    .bar  { animation:grow .6s ease-out backwards; transform-origin:left center; }
    """
