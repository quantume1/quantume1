"""Well-formedness guard shared by the SVG generators.

A duplicate attribute or stray '&' makes browsers refuse to render the whole
document -- and the failure is invisible until the README is live. Every
generator parses its own output before writing, so a broken SVG never reaches
the repo.
"""
from __future__ import annotations

import pathlib
import sys
from xml.parsers import expat


def write_checked(path: pathlib.Path | str, svg: str) -> pathlib.Path:
    parser = expat.ParserCreate()
    try:
        parser.Parse(svg, True)
    except expat.ExpatError as exc:
        line = svg.splitlines()[max(0, exc.lineno - 1)] if svg.splitlines() else ""
        print(f"error: generated SVG is not well-formed: {exc}", file=sys.stderr)
        print(f"  line {exc.lineno}: {line[:200]}", file=sys.stderr)
        raise SystemExit(2) from exc

    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path
