#!/usr/bin/env python3
"""
Check every generated SVG before it ships.

Guards the failure modes that are invisible in the markup and only show up
once the README is live:

  * malformed XML (a duplicate attribute makes browsers drop the whole file)
  * a base rule that hides content, so a renderer ignoring the animation
    leaves a blank panel -- opacity:0 inside @keyframes is fine and expected,
    it is only a problem in a base rule
  * any external reference; these load through camo, which fetches nothing
  * a missing embedded font subset

    python scripts/validate_svgs.py
"""
from __future__ import annotations

import pathlib
import re
import sys
import xml.dom.minidom as minidom

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["ascii-portrait.svg", "info-card.svg", "contrib-heatmap.svg",
         "streak.svg", "langs.svg", "year.svg"]


def base_rules(svg: str) -> str:
    """CSS with @keyframes bodies removed, leaving only base rules."""
    return re.sub(r"@keyframes\s+\w+\s*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", svg)


def check(path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    text = path.read_text()

    try:
        doc = minidom.parseString(text)
    except Exception as exc:
        return [f"malformed XML: {exc}"]

    if doc.documentElement.tagName != "svg":
        problems.append("root element is not <svg>")
    if "<script" in text.lower():
        problems.append("contains <script>")

    external = re.findall(r'(?:href|src)\s*=\s*"(?!data:)(?:https?:)?//[^"]+', text)
    if external:
        problems.append(f"external reference: {external[0][:60]}")

    if "@font-face" not in text:
        problems.append("no embedded font subset")

    if re.search(r"opacity:\s*0\s*[;}]", base_rules(text)):
        problems.append("opacity:0 in a base rule -- blanks if animation is skipped")

    if 'width="0"' in base_rules(text) and "<clipPath" in text:
        problems.append("clip rect base width 0 -- blanks if SMIL is skipped")

    return problems


def main() -> int:
    failed = 0
    total = 0
    for name in FILES:
        p = ROOT / name
        if not p.exists():
            print(f"  {name:22s} MISSING")
            failed += 1
            continue
        size = p.stat().st_size
        total += size
        problems = check(p)
        if problems:
            failed += 1
            print(f"  {name:22s} {size:>7,}B  FAIL")
            for msg in problems:
                print(f"      - {msg}")
        else:
            print(f"  {name:22s} {size:>7,}B  ok")

    print(f"\n  total page weight: {total / 1024:.0f} KB")
    if failed:
        print(f"  {failed} file(s) failed", file=sys.stderr)
        return 1
    print("  all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
