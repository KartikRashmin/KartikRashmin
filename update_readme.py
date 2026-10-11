"""Generates a colored, fastfetch-style profile card as SVG (dark + light).

Output: assets/fastfetch-dark.svg and assets/fastfetch-light.svg
Optional: put your own ASCII art in a file called ascii.txt next to this script.
Optional: set a STATS_TOKEN secret (classic PAT: repo + read:user) to include
private repos in the stats. Without it, only public data is counted.
"""
import os, json, time, urllib.request
from datetime import date, datetime, timedelta
from itertools import zip_longest
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

USER = "KartikRashmin"
DOB = date(2005, 9, 26)
W = 64      # width (in characters) of the info column
GAP = 3     # spaces between ASCII art and info column

# ---- lines-of-code filtering (tune these if the number looks inflated) ----
LOC_SKIP_FORKS = True          # ignore forked repos
LOC_EXCLUDE_REPOS = set()      # repo names to ignore, e.g. {"mc-assets", "old-dump"}
LOC_MAX_COMMIT_LINES = 20000   # ignore single commits larger than this (vendor/generated dumps)
TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN", "")

# ---- SVG look ----
FONT_SIZE = 14
LINE_H = 20
CHAR_W = 8.45           # ~real glyph width; textLength in render() locks spacing to this
PAD_X, PAD_Y = 28, 26
FONT = "'SFMono-Regular','Consolas','Liberation Mono','Menlo','DejaVu Sans Mono',monospace"

THEMES = {
    "dark": dict(bg="#161b22", border="#30363d", fg="#c9d1d9", muted="#6e7681",
                 label="#ffa657", value="#79c0ff", add="#3fb950", dele="#f85149"),
    "light": dict(bg="#f6f8fa", border="#d0d7de", fg="#24292f", muted="#8c959f",
                  label="#bc4c00", value="#0550ae", add="#1a7f37", dele="#cf222e"),
}

DEFAULT_ART = [
    r"     .--.     ",
    r"    |o_o |    ",
    r"    |:_/ |    ",
    r"   //   \ \   ",
    r"  (|     | )  ",
    r" /'\_   _/`\  ",
    r" \___)=(___/  ",
]


def load_art():
    p = Path("ascii.txt")
    if p.exists():
        lines = [l.expandtabs(4).rstrip() for l in p.read_text(encoding="utf-8").splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            return lines
    return DEFAULT_ART


def today_ist():
    # GitHub runners use UTC; use IST so the uptime rolls over at local midnight
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def uptime(today):
    y = today.year - DOB.year
    m = today.month - DOB.month
    d = today.day - DOB.day
    if d < 0:
        m -= 1
        d += (today.replace(day=1) - timedelta(days=1)).day
    if m < 0:
        y -= 1
        m += 12
    return f"{y} years, {m} months, {d} days"


# ---------------- GitHub API ----------------
def api(path):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def gql(query, variables=None, retries=3):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.github.com/graphql", data=body,
                headers={"Authorization": f"Bearer {TOKEN}",
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as r:
                data = json.load(r)
            if "errors" in data:
                raise RuntimeError(data["errors"])
            return data["data"]
        except Exception as e:  # retry on flaky 502s / timeouts
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


USER_Q = """
query($login: String!) {
  user(login: $login) {
    id
    followers { totalCount }
    repositories(ownerAffiliations: [OWNER]) { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
  }
}"""

REPOS_Q = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      pageInfo { hasNextPage endCursor }
      nodes { name isFork owner { login } }
    }
  }
}"""

HISTORY_Q = """
query($owner: String!, $name: String!, $uid: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $uid}) {
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions }
          }
        }
      }
    }
  }
}"""


def loc_stats(uid):
    """Lines added / deleted across the user's own commits, with junk filtered out."""
    repos, cursor = [], None
    while True:
        d = gql(REPOS_Q, {"login": USER, "cursor": cursor})["user"]["repositories"]
        for n in d["nodes"]:
            if LOC_SKIP_FORKS and n["isFork"]:
                continue
            if n["name"] in LOC_EXCLUDE_REPOS:
                continue
            repos.append((n["owner"]["login"], n["name"]))
        if not d["pageInfo"]["hasNextPage"]:
            break
        cursor = d["pageInfo"]["endCursor"]

    adds = dels = 0
    breakdown = []
    for owner, name in repos:
        ra = rd = skipped = 0
        cursor = None
        while True:
            r = gql(HISTORY_Q, {"owner": owner, "name": name, "uid": uid, "cursor": cursor})
            ref = r["repository"]["defaultBranchRef"]
            if not ref:  # empty repo
                break
            h = ref["target"]["history"]
            for n in h["nodes"]:
                if n["additions"] + n["deletions"] > LOC_MAX_COMMIT_LINES:
                    skipped += 1
                    continue
                ra += n["additions"]
                rd += n["deletions"]
            if not h["pageInfo"]["hasNextPage"]:
                break
            cursor = h["pageInfo"]["endCursor"]
        adds += ra
        dels += rd
        breakdown.append((ra + rd, f"{owner}/{name}", ra, rd, skipped))

    # Shows in the Actions log: find the repo that is inflating your total
    print("Lines of code per repo (largest first):")
    for _, full, ra, rd, sk in sorted(breakdown, reverse=True):
        note = f"   [skipped {sk} huge commits]" if sk else ""
        print(f"  {full}: +{ra:,} / -{rd:,}{note}")
    return adds, dels


def stats():
    s = {"repos": None, "stars": None, "followers": None, "commits": None,
         "contributed": None, "loc": None}

    u = api(f"/users/{USER}")
    s["repos"], s["followers"] = u["public_repos"], u["followers"]

    stars, page = 0, 1
    while True:
        repos = api(f"/users/{USER}/repos?per_page=100&page={page}")
        if not repos:
            break
        stars += sum(r["stargazers_count"] for r in repos)
        page += 1
    s["stars"] = stars

    s["commits"] = api(f"/search/commits?q=author:{USER}")["total_count"]

    # GraphQL-based stats: never let a failure here break the whole card
    try:
        ud = gql(USER_Q, {"login": USER})["user"]
        s["repos"] = ud["repositories"]["totalCount"]
        s["followers"] = ud["followers"]["totalCount"]
        s["contributed"] = ud["repositoriesContributedTo"]["totalCount"]
        s["loc"] = loc_stats(ud["id"])
    except Exception as e:
        print(f"warning: GraphQL stats unavailable: {e}")
    return s


# ---------------- line builders ----------------
# Every line is a list of (text, color_role) segments.
def _len(segs):
    return sum(len(t) for t, _ in segs)


def _v(value):
    return [(value, "value")] if isinstance(value, str) else value


def row(label, value):
    v = _v(value)
    dots = max(W - 5 - len(label) - _len(v), 3)
    return [(". ", "muted"), (label + ":", "label"),
            (" " + "." * dots + " ", "muted")] + v


def head(title):
    # the "rule" segment is drawn as a real continuous line in render()
    return [(f"- {title} ", "fg"), ("-" * max(W - len(title) - 3, 3), "rule")]


def pair(l1, v1, l2, v2, wr=24):
    v1, v2 = _v(v1), _v(v2)
    wl = W - 3 - wr
    d1 = max(wl - 5 - len(l1) - _len(v1), 3)
    d2 = max(wr - 3 - len(l2) - _len(v2), 3)
    return ([(". ", "muted"), (l1 + ":", "label"), (" " + "." * d1 + " ", "muted")] + v1
            + [(" | ", "muted"), (l2 + ":", "label"), (" " + "." * d2 + " ", "muted")] + v2)


def build_info():
    s = stats()

    repos_val = [(str(s["repos"]), "value")]
    if s["contributed"] is not None:
        repos_val += [(" ", "muted"), ("{Contributed:", "label"),
                      (" ", "muted"), (f"{s['contributed']}" + "}", "value")]

    lines = [
        head(f"{USER}@github"),
        row("OS", "Windows 11, Fedora Linux"),
        row("Uptime", uptime(today_ist())),
        row("Host", "Student @ Vidyavardhini College Of Engineering"),
        row("IDE", "VSCode, IntelliJ"),
        [(".", "muted")],
        row("Languages.Programming", "Java, Python, JS, C"),
        row("Languages.Computer", "HTML, CSS, JSON, LaTeX, YAML"),
        row("Languages.Real", "English, Hindi, Marathi"),
        [(".", "muted")],
        row("Hobbies.Software", "Minecraft Modding, iOS Jailbreaking"),
        row("Hobbies.Hardware", "Painting, Music"),
        [],
        head("Contact"),
        row("Email.Personal", "kartikrashmin@gmail.com"),
        row("Email.Work", "connect@kartikrashmin.me"),
        row("LinkedIn", "in/kartikrashmin"),
        row("LeetCode", "u/KartikRashmin"),
        [],
        head("GitHub Stats"),
        pair("Repos", repos_val, "Stars", str(s["stars"])),
        pair("Commits", f"{s['commits']:,}", "Followers", str(s["followers"])),
    ]

    if s["loc"] is not None:
        adds, dels = s["loc"]
        lines.append(row("Lines of Code on GitHub", [
            (f"{adds - dels:,}", "value"), (" ( ", "muted"),
            (f"{adds:,}++", "add"), (", ", "muted"),
            (f"{dels:,}--", "dele"), (" )", "muted"),
        ]))
    return lines


# ---------------- SVG rendering ----------------
def nb(text):
    """Escape for XML and use non-breaking spaces so alignment survives every renderer."""
    return escape(text).replace(" ", "\u00a0")


def render(art, info, theme):
    c = THEMES[theme]
    art_w = max(len(a) for a in art)
    # center short art vertically next to the info column
    art = [""] * max(0, (len(info) - len(art)) // 2) + list(art)
    rows = list(zip_longest(art, info, fillvalue=None))
    info_x = PAD_X + (art_w + GAP) * CHAR_W
    info_cols = max([W] + [_len(l) for l in info])
    width = int(info_x + info_cols * CHAR_W + PAD_X)
    height = len(rows) * LINE_H + 2 * PAD_Y - 6

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="fastfetch profile card">',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" '
        f'fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<g font-family="{FONT}" font-size="{FONT_SIZE}">',
    ]
    for i, (a, segs) in enumerate(rows):
        y = PAD_Y + i * LINE_H + FONT_SIZE
        if a and a.strip():
            out.append(
                f'<text x="{PAD_X}" y="{y}" fill="{c["fg"]}" '
                f'textLength="{len(a) * CHAR_W:.1f}" lengthAdjust="spacing">{nb(a)}</text>'
            )
        if segs:
            parts, rules, col = [], [], 0
            for text, role in segs:
                if role == "rule":
                    x1 = info_x + col * CHAR_W + 1
                    x2 = info_x + (col + len(text)) * CHAR_W - 1
                    ly = y - 4.5
                    rules.append(
                        f'<line x1="{x1:.1f}" y1="{ly:.1f}" x2="{x2:.1f}" y2="{ly:.1f}" '
                        f'stroke="{c["fg"]}" stroke-width="1.3" stroke-linecap="round"/>'
                    )
                    parts.append(f'<tspan>{nb(text)}</tspan>')  # invisible spacer
                else:
                    parts.append(f'<tspan fill="{c[role]}">{nb(text)}</tspan>')
                col += len(text)
            out.extend(rules)
            out.append(
                f'<text x="{info_x:.1f}" y="{y}" textLength="{col * CHAR_W:.1f}" '
                f'lengthAdjust="spacing">{"".join(parts)}</text>'
            )
    out += ["</g>", "</svg>"]
    return "\n".join(out)


def main():
    art = load_art()
    info = build_info()
    Path("assets").mkdir(exist_ok=True)
    for theme in THEMES:
        Path(f"assets/fastfetch-{theme}.svg").write_text(
            render(art, info, theme), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
