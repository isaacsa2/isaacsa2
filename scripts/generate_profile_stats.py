#!/usr/bin/env python3
import json
import math
import os
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

USERNAME = os.environ.get("PROFILE_USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER", "isaacsa2")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = Path("assets")
OUT.mkdir(parents=True, exist_ok=True)

COLORS = {
    "Rust": "#dea584", "HTML": "#e34c26", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "Python": "#3572A5", "Java": "#b07219",
    "CSS": "#663399", "Shell": "#89e051", "C": "#555555", "C++": "#f34b7d",
    "Lua": "#000080", "Luau": "#00A2FF", "Go": "#00ADD8", "C#": "#178600",
}

def api(path):
    url = "https://api.github.com" + path
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "isaacsa2-profile-stats",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def graphql(query, variables):
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required for contribution data")

    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "isaacsa2-profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)

    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")

    return payload["data"]

def esc(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def fetch_repos():
    repos = []
    page = 1
    while True:
        batch = api(f"/users/{urllib.parse.quote(USERNAME)}/repos?type=owner&sort=updated&per_page=100&page={page}")
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repos if not r.get("private")]

def fetch_contributions(days=31):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    from_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    to_dt = datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """

    data = graphql(
        query,
        {
            "login": USERNAME,
            "from": from_dt.isoformat().replace("+00:00", "Z"),
            "to": to_dt.isoformat().replace("+00:00", "Z"),
        },
    )

    user = data.get("user")
    if not user:
        raise RuntimeError(f"GitHub user {USERNAME!r} was not found")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    by_date = {}
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            by_date[day["date"]] = int(day["contributionCount"])

    series = []
    cursor = start
    while cursor <= today:
        key = cursor.isoformat()
        series.append((cursor, by_date.get(key, 0)))
        cursor += timedelta(days=1)

    return series, int(calendar["totalContributions"])

def stats_svg(profile, repos):
    stars = sum(r.get("stargazers_count", 0) for r in repos)
    forks = sum(r.get("forks_count", 0) for r in repos)
    followers = profile.get("followers", 0)
    public_repos = profile.get("public_repos", len(repos))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="420" height="170" viewBox="0 0 420 170">
  <rect x="0.5" y="0.5" width="419" height="169" rx="10" fill="#0d1117" stroke="#30363d"/>
  <text x="24" y="34" fill="#58a6ff" font-family="Segoe UI, Ubuntu, sans-serif" font-size="17" font-weight="600">{esc(profile.get("name") or USERNAME)}'s GitHub Stats</text>
  <g font-family="Segoe UI, Ubuntu, sans-serif" font-size="14">
    <text x="24" y="72" fill="#8b949e">Public repositories</text><text x="230" y="72" fill="#c9d1d9" font-weight="600">{public_repos}</text>
    <text x="24" y="100" fill="#8b949e">Stars</text><text x="230" y="100" fill="#c9d1d9" font-weight="600">{stars}</text>
    <text x="24" y="128" fill="#8b949e">Followers</text><text x="230" y="128" fill="#c9d1d9" font-weight="600">{followers}</text>
  </g>
  <text x="24" y="153" fill="#6e7681" font-family="Segoe UI, Ubuntu, sans-serif" font-size="11">Generated in-repo · {forks} forks · refreshed daily</text>
</svg>
'''

def languages_svg(repos):
    totals = Counter()
    for repo in repos:
        if repo.get("archived"):
            continue
        try:
            langs = api(f"/repos/{repo['full_name']}/languages")
        except Exception:
            continue
        totals.update(langs)

    top = totals.most_common(5)
    total_bytes = sum(v for _, v in top) or 1
    x, width = 24.0, 372.0
    rects, labels = [], []
    label_positions = [(29, 116), (150, 116), (271, 116), (29, 140), (150, 140)]

    for i, (name, value) in enumerate(top):
        frac = value / total_bytes
        w = width * frac
        color = COLORS.get(name, "#8b949e")
        rects.append(f'<rect x="{x:.2f}" y="82" width="{w:.2f}" height="10" fill="{color}"/>')
        lx, ly = label_positions[i]
        pct = 100 * value / total_bytes
        labels.append(
            f'<circle cx="{lx}" cy="{ly-5}" r="5" fill="{color}"/>'
            f'<text x="{lx+13}" y="{ly}" fill="#c9d1d9" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">{esc(name)} {pct:.1f}%</text>'
        )
        x += w

    if not top:
        labels = ['<text x="24" y="118" fill="#8b949e" font-family="Segoe UI, Ubuntu, sans-serif" font-size="13">No language data available yet.</text>']

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="420" height="170" viewBox="0 0 420 170">
  <rect x="0.5" y="0.5" width="419" height="169" rx="10" fill="#0d1117" stroke="#30363d"/>
  <text x="24" y="34" fill="#58a6ff" font-family="Segoe UI, Ubuntu, sans-serif" font-size="17" font-weight="600">Top Languages</text>
  <text x="24" y="60" fill="#8b949e" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">Public, non-archived repositories · by bytes</text>
  <rect x="24" y="82" width="372" height="10" rx="5" fill="#21262d"/>
  {''.join(rects)}
  {''.join(labels)}
  <text x="271" y="140" fill="#6e7681" font-family="Segoe UI, Ubuntu, sans-serif" font-size="10">refreshed daily</text>
</svg>
'''

def activity_svg(series, total):
    width, height = 900, 260
    left, right, top, bottom = 56, 24, 64, 44
    chart_w = width - left - right
    chart_h = height - top - bottom

    counts = [count for _, count in series]
    max_count = max(counts or [0])
    scale_max = max(4, int(math.ceil(max_count / 5.0) * 5))

    points = []
    circles = []
    for i, (day, count) in enumerate(series):
        x = left + (chart_w * i / max(1, len(series) - 1))
        y = top + chart_h - (chart_h * count / scale_max)
        points.append((x, y))
        circles.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.8" fill="#58a6ff">'
            f'<title>{day.strftime("%Y-%m-%d")}: {count} contributions</title></circle>'
        )

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    if points:
        area = f"M {points[0][0]:.2f},{top + chart_h:.2f} L " + " L ".join(
            f"{x:.2f},{y:.2f}" for x, y in points
        ) + f" L {points[-1][0]:.2f},{top + chart_h:.2f} Z"
    else:
        area = ""

    grid = []
    for tick in range(5):
        value = scale_max * tick / 4
        y = top + chart_h - chart_h * tick / 4
        grid.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#21262d" stroke-width="1"/>')
        grid.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" fill="#6e7681" font-family="Segoe UI, Ubuntu, sans-serif" font-size="10">{int(round(value))}</text>')

    labels = []
    for i in range(0, len(series), 5):
        day = series[i][0]
        x = left + (chart_w * i / max(1, len(series) - 1))
        labels.append(
            f'<text x="{x:.2f}" y="{height-18}" text-anchor="middle" fill="#6e7681" '
            f'font-family="Segoe UI, Ubuntu, sans-serif" font-size="10">{day.strftime("%d %b")}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" fill="#0d1117" stroke="#30363d"/>
  <text x="24" y="31" fill="#58a6ff" font-family="Segoe UI, Ubuntu, sans-serif" font-size="17" font-weight="600">Contribution Activity</text>
  <text x="24" y="50" fill="#8b949e" font-family="Segoe UI, Ubuntu, sans-serif" font-size="11">Last 31 days · {total} contributions · generated in-repo</text>
  {''.join(grid)}
  <path d="{area}" fill="#58a6ff" fill-opacity="0.12"/>
  <polyline points="{polyline}" fill="none" stroke="#58a6ff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  {''.join(circles)}
  {''.join(labels)}
</svg>
'''

def main():
    profile = api(f"/users/{urllib.parse.quote(USERNAME)}")
    repos = fetch_repos()

    (OUT / "github-stats.svg").write_text(stats_svg(profile, repos), encoding="utf-8")
    (OUT / "top-languages.svg").write_text(languages_svg(repos), encoding="utf-8")

    try:
        series, total = fetch_contributions()
        (OUT / "activity-graph.svg").write_text(activity_svg(series, total), encoding="utf-8")
    except Exception as exc:
        print(f"warning: could not refresh contribution activity graph: {exc}")
        if not (OUT / "activity-graph.svg").exists():
            raise

if __name__ == "__main__":
    main()
