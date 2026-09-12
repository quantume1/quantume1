#!/usr/bin/env python3
"""
Render data/contributions.json as the classic 53-week x 7-day calendar.

Rounded boxes on a GitHub-ish green ramp, revealed once with a diagonal
slide-down (CSS keyframes that play on load and then freeze -- no looping
glow), plus a Less->More legend and a stats footer.

If data/contributions.json is missing, an empty calendar is drawn for the
trailing year so the README never shows a broken image before the first sync.

    python scripts/render_heatmap_svg.py      # -> contrib-heatmap.svg
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from svgcheck import write_checked  # noqa: E402
import fontkit  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# none -> brightest. Level 5 is a neon top end for a personal best.
PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353", "#69f0a0"]

BG = "#0d1117"
BORDER = "#21262d"
TEXT = "#7d8590"
TEXT_BRIGHT = "#c9d1d9"
ACCENT = "#39d353"

FONT = fontkit.STACK

WEEKS = 53
PAD_L, PAD_R = 38.0, 20.0
PAD_T = 46.0
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def empty_calendar() -> dict:
    """A zeroed trailing-year calendar, used before the first successful sync."""
    today = dt.date.today()
    # Walk back to the Sunday that starts the 53-week window.
    end_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    start = end_sunday - dt.timedelta(weeks=WEEKS - 1)
    days = []
    d = start
    while d <= today:
        days.append({"date": d.isoformat(), "count": 0, "level": 0})
        d += dt.timedelta(days=1)
    cfg = ROOT / "data" / "profile.json"
    user = None
    if cfg.exists():
        user = json.loads(cfg.read_text()).get("username")

    return {
        "username": user,
        "generated_at": None,
        "stats": {"total": 0, "current_streak": 0, "longest_streak": 0,
                  "max_count": 0, "active_days": 0, "best_day": None},
        "days": days,
        "_placeholder": True,
    }


def grid(days: list[dict]) -> tuple[list[list[dict | None]], dt.date]:
    """Bucket days into (week, weekday) columns, Sunday-first like GitHub."""
    first = dt.date.fromisoformat(days[0]["date"])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    cols: list[list[dict | None]] = [[None] * 7 for _ in range(WEEKS)]
    for day in days:
        d = dt.date.fromisoformat(day["date"])
        week = (d - start).days // 7
        # Keep only the trailing WEEKS columns.
        week -= max(0, ((dt.date.fromisoformat(days[-1]["date"]) - start).days // 7)
                    - (WEEKS - 1))
        if 0 <= week < WEEKS:
            cols[week][(d.weekday() + 1) % 7] = day
    return cols, start


def level_of(day: dict, max_count: int) -> int:
    lvl = int(day.get("level", 0) or 0)
    count = int(day.get("count", 0) or 0)
    # Promote the very best days to the neon top end.
    if max_count > 0 and count >= max(4, 0.8 * max_count):
        return 5
    return max(0, min(4, lvl))


def build(data: dict, width: float, step_w: float, step_d: float,
          static: bool) -> str:
    days = data["days"]
    stats = data.get("stats", {})
    placeholder = data.get("_placeholder", False)
    cols, start = grid(days)
    max_count = int(stats.get("max_count", 0) or 0)

    inner = width - PAD_L - PAD_R
    gap = 3.0
    pitch = (inner + gap) / WEEKS
    cell = pitch - gap
    height = PAD_T + 7 * pitch - gap + 54

    css = f"""
    .lbl {{ fill:{TEXT}; font-size:10px; }}
    .hl  {{ fill:{TEXT_BRIGHT}; font-size:11px; }}
    .acc {{ fill:{ACCENT}; font-size:11px; }}
    .ttl {{ fill:{TEXT_BRIGHT}; font-size:12px; }}
    .d   {{ rx:2.2; ry:2.2; shape-rendering:geometricPrecision; }}
    """
    if not static:
        # translateY only: unlike scale/rotate it does not depend on
        # transform-origin, so it behaves the same in every SVG renderer.
        css += """
    @keyframes drop { from { opacity:0; transform:translateY(-10px); }
                        to { opacity:1; transform:translateY(0); } }
    @keyframes fade { from { opacity:0; } to { opacity:1; } }
    /* animation-fill-mode:backwards, not forwards, and no opacity:0 in the
       base rule. During the delay the element takes the keyframe's from-state
       (hidden); once the animation ends it falls back to its own style, which
       is fully visible. So a renderer that ignores @keyframes entirely shows
       the finished graphic rather than a blank panel. */
    .d    { animation:drop .45s ease-out backwards; }
    .chr  { animation:fade .5s ease-out backwards; }
    """

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="{FONT}" role="img" '
        f'aria-label="GitHub contribution heatmap for the last year">',
        f"<style>{css}</style>",
        f'<rect width="{width:.0f}" height="{height:.0f}" rx="10" fill="{BG}" '
        f'stroke="{BORDER}"/>',
    ]

    def anim(base: str, delay: float) -> str:
        """Class + animation-delay as one attribute pair.

        These must be emitted together -- a second class="chr" alongside an
        existing class attribute is a duplicate-attribute XML parse error,
        and browsers refuse to render the document at all.
        """
        if static:
            return f'class="{base}"'
        return f'class="{base} chr" style="animation-delay:{delay:.2f}s"'

    user = data.get("username") or "github"
    out.append(
        f'<text x="{PAD_L:.1f}" y="24" {anim("ttl", 0.05)}>'
        f'contributions &#183; @{user}</text>'
    )

    # Month labels, emitted when the month changes between columns.
    last_month = None
    for w, col in enumerate(cols):
        day = next((d for d in col if d), None)
        if not day:
            continue
        d = dt.date.fromisoformat(day["date"])
        if d.month != last_month:
            last_month = d.month
            x = PAD_L + w * pitch
            if x < width - PAD_R - 24:
                out.append(f'<text x="{x:.1f}" y="{PAD_T - 6:.1f}" {anim("lbl", 0.1 + w * 0.004)}>{MONTHS[d.month - 1]}</text>')

    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = PAD_T + row * pitch + cell * 0.78
        out.append(f'<text x="6" y="{y:.1f}" {anim("lbl", 0.12)}>{name}</text>')

    # The calendar itself.
    for w, col in enumerate(cols):
        x = PAD_L + w * pitch
        for r in range(7):
            day = col[r]
            if day is None:
                continue
            y = PAD_T + r * pitch
            lvl = level_of(day, max_count)
            delay = 0.18 + w * step_w + r * step_d
            style = "" if static else f' style="animation-delay:{delay:.2f}s"'
            count = day.get("count", 0)
            out.append(
                f'<rect class="d" x="{x:.1f}" y="{y:.1f}" width="{cell:.1f}" '
                f'height="{cell:.1f}" fill="{PALETTE[lvl]}"{style}>'
                f'<title>{count} on {day["date"]}</title></rect>'
            )

    # Footer: stats on the left, Less -> More legend on the right.
    fy = PAD_T + 7 * pitch + 22
    tail = 0.18 + WEEKS * step_w + 6 * step_d + 0.25

    if placeholder:
        line = "awaiting first sync &#183; the daily workflow fills this in"
        out.append(f'<text x="{PAD_L:.1f}" y="{fy:.1f}" {anim("lbl", tail)}>{line}</text>')
    else:
        total = f'{stats.get("total", 0):,}'
        out.append(
            f'<text x="{PAD_L:.1f}" y="{fy:.1f}" {anim("hl", tail)}>'
            f'<tspan class="acc">{total}</tspan> contributions in the last year'
            f'</text>'
        )
        out.append(
            f'<text x="{PAD_L:.1f}" y="{fy + 17:.1f}" {anim("lbl", tail + 0.12)}>'
            f'current streak {stats.get("current_streak", 0)}d &#183; '
            f'longest {stats.get("longest_streak", 0)}d &#183; '
            f'best day {stats.get("max_count", 0)}</text>'
        )

    lx = width - PAD_R - 5 * (cell + 3) - 62
    ly = fy - cell + 2
    out.append(f'<text x="{lx:.1f}" y="{fy:.1f}" {anim("lbl", tail + 0.2)}>Less</text>')
    for i in range(5):
        out.append(
            f'<rect class="d" x="{lx + 30 + i * (cell + 3):.1f}" y="{ly:.1f}" '
            f'width="{cell:.1f}" height="{cell:.1f}" fill="{PALETTE[i]}"'
            + ("" if static else
               f' style="animation-delay:{tail + 0.22 + i * 0.05:.2f}s"')
            + "/>"
        )
    out.append(f'<text x="{lx + 34 + 5 * (cell + 3):.1f}" y="{fy:.1f}" {anim("lbl", tail + 0.5)}>More</text>')

    out.append("</svg>")
    css = fontkit.face_css(fontkit.text_chars(out))
    if css:
        out.insert(1, f"<style>{css}</style>")
    return "\n".join(out)


def main() -> int:
    import os
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--data", default=str(ROOT / "data" / "stats.json"))
    ap.add_argument("-o", "--out", default=str(ROOT / "contrib-heatmap.svg"))
    ap.add_argument("--width", type=float, default=860.0)
    ap.add_argument("--step-week", type=float, default=0.012)
    ap.add_argument("--step-day", type=float, default=0.030)
    ap.add_argument("--static", action="store_true")
    args = ap.parse_args()

    src = pathlib.Path(args.data)
    if not src.exists():
        # Older layout, before fetch_stats.py replaced fetch_contributions.py.
        legacy = ROOT / "data" / "contributions.json"
        if legacy.exists():
            src = legacy
    if src.exists():
        data = json.loads(src.read_text())
        print(f"render_heatmap_svg: {len(data['days'])} days from {src}")
    else:
        data = empty_calendar()
        print("render_heatmap_svg: no data file yet, drawing an empty calendar")

    svg = build(data, args.width, args.step_week, args.step_day,
                args.static or os.environ.get("STATIC") == "1")
    write_checked(args.out, svg)
    print(f"  wrote      : {args.out} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
