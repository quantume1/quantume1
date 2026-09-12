#!/usr/bin/env python3
"""
Collect profile stats, preferring the GraphQL API and falling back to scraping.

Two paths, same output file:

  * GraphQL (when a token is present). Typed and stable, and the only way to
    get language bytes and repo counts. Inside Actions the built-in
    GITHUB_TOKEN is enough -- no personal access token required.
  * HTML scrape of https://github.com/users/<user>/contributions (no auth).
    Used when there is no token, and as a fallback if GraphQL fails, so a bad
    query or an API outage degrades the data rather than blanking the graph.

On private contributions: the calendar on your profile page can include them
if you have opted in, but the Actions token sees only what any signed-in user
sees, so the GraphQL totals are public-only. Set a PROFILE_TOKEN secret to a
PAT with read:user if you want private contributions counted.

Determinism matters here -- this runs nightly and commits its output:

  * the window is pinned to whole UTC days, so two runs on the same date
    bucket days into identical weeks instead of shifting by a fraction
  * repositories are filtered to privacy: PUBLIC, so the numbers do not
    depend on whose token ran the query

    python scripts/fetch_stats.py
    python scripts/fetch_stats.py --selftest    # parser check, no network
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
from collections import defaultdict

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRAPE_URL = "https://github.com/users/{user}/contributions"
GRAPHQL_URL = "https://api.github.com/graphql"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; profile-art/1.0)",
    "Accept": "text/html,application/xhtml+xml",
    "X-Requested-With": "XMLHttpRequest",
}

LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
    repositories(
      first: 100
      privacy: PUBLIC
      ownerAffiliations: OWNER
      isFork: false
      orderBy: { field: PUSHED_AT, direction: DESC }
    ) {
      totalCount
      nodes {
        name
        stargazerCount
        primaryLanguage { name color }
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


# ----------------------------------------------------------------- helpers


def load_username(explicit: str | None) -> str:
    if explicit:
        return explicit
    cfg = ROOT / "data" / "profile.json"
    if cfg.exists():
        user = json.loads(cfg.read_text()).get("username")
        if user:
            return user
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if owner:
        return owner
    raise SystemExit("error: no username; set data/profile.json or pass --user")


def window(today: dt.date | None = None) -> tuple[str, str]:
    """A 365-day window pinned to whole UTC days.

    Left to default, contributionsCollection measures back from the moment of
    the request, so two runs minutes apart split days across different weeks
    and the rendered graph shifts -- producing a commit every night that
    encodes nothing but the clock.
    """
    today = today or dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=364)
    return f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z"


# ---------------------------------------------------------------- graphql


def parse_graphql(payload: dict) -> dict:
    """Turn a GraphQL response into days + languages + repo totals."""
    user = payload["data"]["user"]
    if user is None:
        raise ValueError("GraphQL returned no such user")

    coll = user["contributionsCollection"]
    cal = coll["contributionCalendar"]

    days: list[dict] = []
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            days.append({
                "date": day["date"],
                "count": int(day["contributionCount"]),
                "level": LEVELS.get(day.get("contributionLevel", "NONE"), 0),
            })
    days.sort(key=lambda d: d["date"])

    repos = user.get("repositories") or {}
    nodes = repos.get("nodes") or []

    by_bytes: dict[str, int] = defaultdict(int)
    colours: dict[str, str] = {}
    by_repo: dict[str, int] = defaultdict(int)
    stars = 0

    for repo in nodes:
        stars += int(repo.get("stargazerCount") or 0)
        primary = repo.get("primaryLanguage")
        if primary and primary.get("name"):
            by_repo[primary["name"]] += 1
            if primary.get("color"):
                colours[primary["name"]] = primary["color"]
        for edge in ((repo.get("languages") or {}).get("edges") or []):
            node = edge.get("node") or {}
            name = node.get("name")
            if not name:
                continue
            by_bytes[name] += int(edge.get("size") or 0)
            if node.get("color"):
                colours.setdefault(name, node["color"])

    total_bytes = sum(by_bytes.values())
    languages = [
        {
            "name": name,
            "bytes": size,
            "share": round(size / total_bytes, 5) if total_bytes else 0.0,
            "repos": by_repo.get(name, 0),
            "color": colours.get(name) or "#8b949e",
        }
        for name, size in sorted(by_bytes.items(), key=lambda kv: -kv[1])
    ]

    return {
        "days": days,
        "reported_total": int(cal["totalContributions"]),
        "languages": languages,
        "repos": {
            "public_count": int(repos.get("totalCount") or 0),
            "stars": stars,
            "sampled": len(nodes),
        },
        "breakdown": {
            "commits": coll.get("totalCommitContributions", 0),
            "pull_requests": coll.get("totalPullRequestContributions", 0),
            "issues": coll.get("totalIssueContributions", 0),
            "reviews": coll.get("totalPullRequestReviewContributions", 0),
            "restricted": coll.get("restrictedContributionsCount", 0),
        },
    }


def fetch_graphql(user: str, token: str, timeout: int) -> dict:
    frm, to = window()
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": QUERY, "variables": {"login": user, "from": frm, "to": to}},
        headers={"Authorization": f"bearer {token}",
                 "User-Agent": "profile-art/1.0"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return parse_graphql(payload)


# ----------------------------------------------------------------- scrape


def parse_scrape(html: str) -> dict:
    """Pull one record per day out of the public calendar markup.

    GitHub has changed this markup more than once (<rect data-count> in the
    old SVG calendar, <td data-level> plus a sibling <tool-tip> today), so we
    read whatever is present and fall through the options.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    tips = {t.get("for"): t.get_text(" ", strip=True)
            for t in soup.find_all("tool-tip") if t.get("for")}

    days: list[dict] = []
    for cell in soup.select("[data-date]"):
        date = cell.get("data-date")
        if not date:
            continue
        count = cell.get("data-count")
        if count is None:
            text = tips.get(cell.get("id", ""), "") or cell.get_text(" ", strip=True)
            m = re.search(r"([\d,]+)\s+contribution", text)
            if m:
                count = m.group(1).replace(",", "")
            elif re.search(r"\bNo contributions\b", text, re.I):
                count = "0"
        try:
            count_i = int(str(count).replace(",", ""))
        except (TypeError, ValueError):
            count_i = 0
        try:
            level_i = int(cell.get("data-level"))
        except (TypeError, ValueError):
            level_i = 0 if count_i == 0 else min(4, 1 + count_i // 6)
        days.append({"date": date, "count": count_i, "level": level_i})

    days.sort(key=lambda d: d["date"])
    m = re.search(r"([\d,]+)\s+contributions?\s+in\s+the\s+last\s+year", html)
    return {
        "days": days,
        "reported_total": int(m.group(1).replace(",", "")) if m else None,
        "languages": [],
        "repos": {},
        "breakdown": {},
    }


def fetch_scrape(user: str, timeout: int) -> dict:
    url = SCRAPE_URL.format(user=user)
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")
    parsed = parse_scrape(resp.text)
    if not parsed["days"]:
        raise RuntimeError("parsed zero day cells -- GitHub markup may have changed")
    return parsed


# ------------------------------------------------------------------ stats


def derive_stats(days: list[dict], reported_total: int | None) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    past = [d for d in days if d["date"] <= today]
    total = sum(d["count"] for d in past)

    longest = run = 0
    longest_end = run_start = None
    longest_range = None
    for d in past:
        if d["count"] > 0:
            run = run + 1 if run else 1
            run_start = run_start or d["date"]
            if run > longest:
                longest, longest_range = run, (run_start, d["date"])
        else:
            run, run_start = 0, None

    # Current streak counts back from today; a still-empty today does not
    # break a streak that is otherwise alive through yesterday.
    current, current_from = 0, None
    for d in reversed(past):
        if d["count"] > 0:
            current += 1
            current_from = d["date"]
        elif d["date"] == today:
            continue
        else:
            break

    best = max(past, key=lambda d: d["count"], default=None)
    months: dict[str, int] = defaultdict(int)
    for d in past:
        months[d["date"][:7]] += d["count"]

    return {
        "total": reported_total if reported_total is not None else total,
        "total_scraped": total,
        "days_tracked": len(past),
        "active_days": sum(1 for d in past if d["count"] > 0),
        "current_streak": current,
        "current_streak_from": current_from,
        "longest_streak": longest,
        "longest_streak_range": longest_range,
        "best_day": best,
        "max_count": best["count"] if best else 0,
        "average": round(total / len(past), 2) if past else 0.0,
        "months": dict(sorted(months.items())),
    }


# --------------------------------------------------------------- selftest


FIXTURE = {
    "data": {
        "user": {
            "contributionsCollection": {
                "totalCommitContributions": 40,
                "totalPullRequestContributions": 5,
                "totalIssueContributions": 2,
                "totalPullRequestReviewContributions": 3,
                "restrictedContributionsCount": 7,
                "contributionCalendar": {
                    "totalContributions": 57,
                    "weeks": [
                        {"contributionDays": [
                            {"date": "2024-01-07", "contributionCount": 0,
                             "contributionLevel": "NONE"},
                            {"date": "2024-01-08", "contributionCount": 3,
                             "contributionLevel": "SECOND_QUARTILE"},
                        ]},
                        {"contributionDays": [
                            {"date": "2024-01-09", "contributionCount": 9,
                             "contributionLevel": "FOURTH_QUARTILE"},
                        ]},
                    ],
                },
            },
            "repositories": {
                "totalCount": 12,
                "nodes": [
                    {"name": "a", "stargazerCount": 4,
                     "primaryLanguage": {"name": "Python", "color": "#3572A5"},
                     "languages": {"edges": [
                         {"size": 8000, "node": {"name": "Python", "color": "#3572A5"}},
                         {"size": 2000, "node": {"name": "Shell", "color": "#89e051"}},
                     ]}},
                    {"name": "b", "stargazerCount": 1,
                     "primaryLanguage": None,
                     "languages": {"edges": [
                         {"size": 5000, "node": {"name": "Python", "color": "#3572A5"}},
                     ]}},
                ],
            },
        }
    }
}


def selftest() -> int:
    p = parse_graphql(FIXTURE)
    assert [d["date"] for d in p["days"]] == ["2024-01-07", "2024-01-08", "2024-01-09"], p["days"]
    assert [d["level"] for d in p["days"]] == [0, 2, 4], p["days"]
    assert p["reported_total"] == 57
    assert p["repos"] == {"public_count": 12, "stars": 5, "sampled": 2}, p["repos"]
    langs = {l["name"]: l for l in p["languages"]}
    assert langs["Python"]["bytes"] == 13000, langs
    assert langs["Python"]["repos"] == 1, langs
    assert p["languages"][0]["name"] == "Python", "sorted by bytes desc"
    # share is rounded to 5dp on write, so compare at that precision.
    assert abs(langs["Shell"]["share"] - 2000 / 15000) < 1e-5, langs

    s = derive_stats([
        {"date": "2024-01-01", "count": 1, "level": 1},
        {"date": "2024-01-02", "count": 2, "level": 1},
        {"date": "2024-01-03", "count": 0, "level": 0},
        {"date": "2024-01-04", "count": 5, "level": 2},
    ], None)
    assert s["longest_streak"] == 2, s
    assert s["longest_streak_range"] == ("2024-01-01", "2024-01-02"), s
    assert s["max_count"] == 5 and s["active_days"] == 3, s

    frm, to = window(dt.date(2025, 3, 10))
    assert frm == "2024-03-11T00:00:00Z" and to == "2025-03-10T23:59:59Z", (frm, to)

    print("selftest: OK (graphql parse, language aggregation, streaks, window)")
    return 0


# ------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-u", "--user", default=None)
    ap.add_argument("-o", "--out", default=str(ROOT / "data" / "stats.json"))
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--no-graphql", action="store_true", help="force the scrape path")
    ap.add_argument("--require-graphql", action="store_true",
                    help="fail instead of falling back to scraping")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    user = load_username(args.user)
    # PROFILE_TOKEN lets you supply a PAT with read:user for private counts.
    token = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")

    parsed, source = None, None
    if token and not args.no_graphql:
        try:
            print(f"fetch_stats: GraphQL for @{user}")
            parsed, source = fetch_graphql(user, token, args.timeout), "graphql"
        except Exception as exc:
            if args.require_graphql:
                print(f"error: GraphQL failed: {exc}", file=sys.stderr)
                return 1
            print(f"  warning: GraphQL failed ({exc}); falling back to scraping",
                  file=sys.stderr)
    elif not token:
        print("fetch_stats: no token, using the public scrape path")

    if parsed is None:
        try:
            parsed, source = fetch_scrape(user, args.timeout), "scrape"
        except Exception as exc:
            print(f"error: scrape failed too: {exc}", file=sys.stderr)
            return 1

    days = parsed["days"]
    payload = {
        "username": user,
        "source": source,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "range": {"from": days[0]["date"], "to": days[-1]["date"]},
        "stats": derive_stats(days, parsed["reported_total"]),
        "languages": parsed["languages"],
        "repos": parsed["repos"],
        "breakdown": parsed["breakdown"],
        "days": days,
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    s = payload["stats"]
    print(f"  source     : {source}")
    print(f"  days       : {len(days)} ({days[0]['date']} -> {days[-1]['date']})")
    print(f"  total      : {s['total']}")
    print(f"  streak     : current {s['current_streak']}, longest {s['longest_streak']}")
    print(f"  languages  : {len(payload['languages'])}")
    print(f"  wrote      : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
