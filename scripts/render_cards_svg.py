#!/usr/bin/env python3
"""
Render the three supporting graphics from data/stats.json.

  streak.svg  — current and longest streak, with their date ranges
  langs.svg   — top languages as a stacked bar, by bytes
  year.svg    — the year at one character per day, using the portrait's ramp

All three share the terminal chrome in theme.py and embed a font subset, so
they sit in the same visual language as the portrait and the heatmap.

    python scripts/render_cards_svg.py           # writes all three
    STATIC=1 python scripts/render_cards_svg.py  # frozen frames
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fontkit  # noqa: E402
import theme  # noqa: E402
from svgcheck import write_checked  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def open_svg(w: float, h: float, label: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.0f} {h:.0f}" font-family="{fontkit.STACK}" '
        f'role="img" aria-label="{escape(label)}">',
        f'<rect width="{w:.0f}" height="{h:.0f}" rx="10" fill="{theme.BG}" '
        f'stroke="{theme.BORDER}"/>',
    ]


def close_svg(out: list[str], static: bool, bold: str = "") -> str:
    out.append("</svg>")
    css = theme.keyframes(static)
    face = fontkit.face_css(fontkit.text_chars(out), bold)
    out.insert(1, f"<style>{face}{css}</style>")
    return "\n".join(out)


def title_row(out: list[str], text: str, x: float, static: bool) -> None:
    out.append(f'<text x="{x:.0f}" y="24" fill="{theme.TITLE}" font-size="12" '
               f'font-weight="700" {theme.anim("", 0.05, static)}>{escape(text)}</text>')
    out.append(f'<line x1="{x:.0f}" y1="34" x2="{x + 10:.0f}" y2="34" '
               f'stroke="{theme.BORDER}"/>')


# ------------------------------------------------------------------ streak


def build_streak(data: dict, w: float, static: bool) -> str:
    s = data.get("stats", {})
    h = 168.0
    pad = 22.0
    out = open_svg(w, h, "Contribution streak summary")
    title_row(out, "streak", pad, static)

    def fmt(iso: str | None) -> str:
        if not iso:
            return "—"
        d = dt.date.fromisoformat(iso)
        return d.strftime("%d %b %Y").lstrip("0")

    cur = s.get("current_streak", 0)
    # 44px bold at 0.600 em advance, plus a space, or the label butts against
    # the digits.
    num_w = len(str(cur)) * 44.0 * fontkit.ADVANCE_EM
    out.append(f'<text x="{pad:.0f}" y="82" fill="{theme.ACCENT}" font-size="44" '
               f'font-weight="700" {theme.anim("", 0.18, static)}>{cur}</text>')
    out.append(f'<text x="{pad + num_w + 10:.0f}" y="78" '
               f'fill="{theme.TEXT}" font-size="13" '
               f'{theme.anim("", 0.24, static)}>day streak</text>')

    since = fmt(s.get("current_streak_from")) if cur else "—"
    out.append(f'<text x="{pad:.0f}" y="104" fill="{theme.TEXT}" font-size="11" '
               f'{theme.anim("", 0.3, static)}>since {escape(since)}</text>')

    rng = s.get("longest_streak_range") or []
    span = f"{fmt(rng[0])} – {fmt(rng[1])}" if len(rng) == 2 else "—"
    out.append(f'<line x1="{pad:.0f}" y1="118" x2="{w - pad:.0f}" y2="118" '
               f'stroke="{theme.BORDER}"/>')
    out.append(f'<text x="{pad:.0f}" y="138" fill="{theme.TEXT_BRIGHT}" font-size="12" '
               f'{theme.anim("", 0.38, static)}>longest '
               f'<tspan fill="{theme.ACCENT}">{s.get("longest_streak", 0)}</tspan> days'
               f'</text>')
    out.append(f'<text x="{pad:.0f}" y="155" fill="{theme.TEXT}" font-size="10.5" '
               f'{theme.anim("", 0.44, static)}>{escape(span)}</text>')

    active = s.get("active_days", 0)
    tracked = s.get("days_tracked", 0) or 1
    out.append(f'<text x="{w - pad:.0f}" y="138" fill="{theme.TEXT_BRIGHT}" '
               f'font-size="12" text-anchor="end" {theme.anim("", 0.5, static)}>'
               f'{active} active days</text>')
    # Integer division renders a real but low percentage as a flat "0%", which
    # reads as a bug rather than as a sparse year.
    pct = 100.0 * active / tracked
    pct_txt = f"{pct:.0f}%" if pct >= 10 else f"{pct:.1f}%"
    out.append(f'<text x="{w - pad:.0f}" y="155" fill="{theme.TEXT}" font-size="10.5" '
               f'text-anchor="end" {theme.anim("", 0.56, static)}>'
               f'{pct_txt} of the year</text>')
    return close_svg(out, static, "streak0123456789")


# --------------------------------------------------------------- languages


def build_langs(data: dict, w: float, static: bool, top: int = 5) -> str:
    langs = (data.get("languages") or [])[:top]
    h = 168.0
    pad = 22.0
    out = open_svg(w, h, "Top languages by bytes of code")
    title_row(out, "languages", pad, static)

    if not langs:
        out.append(f'<text x="{pad:.0f}" y="86" fill="{theme.TEXT}" font-size="11.5" '
                   f'{theme.anim("", 0.2, static)}>no language data — needs the '
                   f'GraphQL path</text>')
        out.append(f'<text x="{pad:.0f}" y="104" fill="{theme.TEXT}" font-size="11.5" '
                   f'{theme.anim("", 0.26, static)}>(runs automatically in '
                   f'Actions)</text>')
        return close_svg(out, static, "languages")

    # Shares are renormalised over the top N, so the bar always fills its track
    # rather than trailing off into unlabelled remainder.
    shown = sum(l["bytes"] for l in langs) or 1
    bar_w = w - 2 * pad
    x = pad
    for i, lang in enumerate(langs):
        seg = bar_w * lang["bytes"] / shown
        out.append(
            f'<rect x="{x:.1f}" y="48" width="{max(seg, 1.5):.1f}" height="10" '
            f'fill="{lang["color"]}" '
            + ("" if static else
               f'class="bar" style="animation-delay:{0.2 + i * 0.07:.2f}s"')
            + "/>")
        x += seg

    for i, lang in enumerate(langs):
        col = i % 2
        row = i // 2
        lx = pad + col * (bar_w / 2)
        ly = 84 + row * 20
        pct = 100.0 * lang["bytes"] / shown
        out.append(f'<circle cx="{lx + 4:.1f}" cy="{ly - 4:.1f}" r="4" '
                   f'fill="{lang["color"]}" {theme.anim("", 0.34 + i * .05, static)}/>')
        out.append(f'<text x="{lx + 14:.1f}" y="{ly:.1f}" fill="{theme.TEXT_BRIGHT}" '
                   f'font-size="11.5" {theme.anim("", 0.36 + i * .05, static)}>'
                   f'{escape(lang["name"])} '
                   f'<tspan fill="{theme.TEXT}">{pct:.1f}%</tspan></text>')

    repos = data.get("repos") or {}
    if repos:
        out.append(f'<text x="{pad:.0f}" y="152" fill="{theme.TEXT}" font-size="10.5" '
                   f'{theme.anim("", 0.66, static)}>'
                   f'{repos.get("public_count", 0)} public repos · '
                   f'{repos.get("stars", 0)} stars</text>')
    return close_svg(out, static, "languages")


# -------------------------------------------------------------- year strip


# Contribution level -> ramp index. Scaling raw counts against the year's
# single busiest day pushes almost every ordinary day to the sparse end and
# the strip reads as noise; the quartile level is what the heatmap already
# uses, and it spreads typical days across the ramp.
LEVEL_GLYPH = [0, 3, 6, 9, 12]


def build_year(data: dict, w: float, static: bool, per_row: int | None = None) -> str:
    days = data.get("days", [])
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    days = [d for d in days if d["date"] <= today]
    max_count = max((d["count"] for d in days), default=0)

    fs = 12.0
    cw = fs * fontkit.ADVANCE_EM
    lh = 17.0
    pad = 22.0
    gutter = 46.0
    if per_row is None:
        per_row = max(20, int((w - 2 * pad - gutter) // cw))
    rows = [days[i:i + per_row] for i in range(0, len(days), per_row)]
    h = 52 + len(rows) * lh + 22

    out = open_svg(w, h, "The year at one character per day")
    title_row(out, "year", pad, static)

    for r, chunk in enumerate(rows):
        y = 56 + r * lh
        # Density picks the glyph, exactly as in the portrait: an empty day is
        # a space, a personal best is the densest character in the ramp.
        glyphs = "".join(
            theme.RAMP[LEVEL_GLYPH[max(0, min(4, int(d.get("level", 0) or 0)))]]
            for d in chunk
        )
        run = len(glyphs) * cw
        if chunk:
            # Label gutter on the left, so every row starts at the same x and
            # the strip reads as one continuous tape.
            out.append(
                f'<text x="{pad:.0f}" y="{y:.1f}" fill="{theme.TEXT}" '
                f'font-size="9.5" {theme.anim("", 0.2 + r * 0.12, static)}>'
                f'{chunk[0]["date"][5:]}</text>')
        out.append(
            f'<text x="{pad + gutter:.0f}" y="{y:.1f}" fill="{theme.ACCENT}" '
            f'font-size="{fs}" textLength="{run:.1f}" lengthAdjust="spacing" '
            f'xml:space="preserve" {theme.anim("", 0.24 + r * 0.12, static)}>'
            f'{escape(glyphs)}</text>')

    out.append(f'<text x="{pad:.0f}" y="{h - 10:.0f}" fill="{theme.TEXT}" '
               f'font-size="10" {theme.anim("", 0.2 + len(rows) * 0.12, static)}>'
               f'one character per day · densest = busiest ({max_count} on a day)</text>')
    return close_svg(out, static, "year")


# ------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--data", default=str(ROOT / "data" / "stats.json"))
    ap.add_argument("--out-dir", default=str(ROOT))
    ap.add_argument("--card-width", type=float, default=425.0)
    ap.add_argument("--strip-width", type=float, default=860.0)
    ap.add_argument("--static", action="store_true")
    args = ap.parse_args()

    static = args.static or os.environ.get("STATIC") == "1"
    src = pathlib.Path(args.data)
    if src.exists():
        data = json.loads(src.read_text())
        print(f"render_cards_svg: {len(data.get('days', []))} days from {src}")
    else:
        print("render_cards_svg: no stats.json yet, drawing empty cards")
        data = {"stats": {}, "languages": [], "repos": {}, "days": []}

    out_dir = pathlib.Path(args.out_dir)
    for name, svg in (
        ("streak.svg", build_streak(data, args.card_width, static)),
        ("langs.svg", build_langs(data, args.card_width, static)),
        ("year.svg", build_year(data, args.strip_width, static)),
    ):
        p = write_checked(out_dir / name, svg)
        print(f"  wrote      : {p.name} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
