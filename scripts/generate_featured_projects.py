"""Render the profile's pinned repositories and current focus into README.md."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from update_readme import FONT, THEMES  # Existing fastfetch palette and font.

USER = "KartikRashmin"
QUERY = """
query($login: String!) {
  user(login: $login) {
    pinnedItems(first: 100) {
      nodes {
        __typename
        ... on Repository {
          name
          nameWithOwner
          description
          url
          primaryLanguage { name }
          stargazerCount
          forkCount
        }
      }
    }
  }
}
"""
CARD_WIDTH = 520
CARD_HEIGHT = 284
MAX_CARDS = 4
TITLE_FONT_SIZE = 18
BODY_FONT_SIZE = 16


@dataclass(frozen=True)
class Repository:
    name: str
    full_name: str
    description: str | None
    url: str
    language: str | None
    stars: int
    forks: int


def fetch_pinned(token: str) -> list[Repository]:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to fetch pinned repositories")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "KartikRashmin-profile-generator",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub GraphQL request failed (HTTP {error.code})") from error
    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {payload['errors']}")
    user = (payload.get("data") or {}).get("user")
    if user is None:
        raise RuntimeError(f"GitHub user {USER} was not found")

    repos = []
    for item in user["pinnedItems"]["nodes"]:
        if item["__typename"] != "Repository":
            continue
        repos.append(
            Repository(
                name=item["name"],
                full_name=item["nameWithOwner"],
                description=item["description"],
                url=item["url"],
                language=(item.get("primaryLanguage") or {}).get("name"),
                stars=item["stargazerCount"],
                forks=item["forkCount"],
            )
        )
        if len(repos) == MAX_CARDS:
            break
    return repos


def filename(repo: Repository, theme: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", repo.full_name.lower()).strip("-")[:60]
    digest = hashlib.sha256(repo.full_name.encode("utf-8")).hexdigest()[:10]
    return f"{slug or 'repo'}-{digest}-{theme}.svg"


def lines(value: str, width: int, limit: int) -> list[str]:
    normalized = " ".join(value.split())
    wrapped = textwrap.wrap(normalized, width=width, break_long_words=True,
                            break_on_hyphens=False) or [""]
    if len(wrapped) > limit:
        wrapped = wrapped[:limit]
        wrapped[-1] = wrapped[-1].rstrip(" .") + "…"
    return wrapped


def render_card(repo: Repository, theme: str) -> str:
    color = THEMES[theme]
    title = lines(repo.full_name, 40, 2)
    description = lines(repo.description or "No description provided.", 47, 6)
    # The SVG is a display-only image. README anchors provide the clickable URL.
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" '
        f'viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" role="img" '
        f'aria-label="{html.escape(repo.full_name, quote=True)} repository card">',
        f'<rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}" '
        f'rx="10" fill="{color["bg"]}" stroke="{color["border"]}"/>',
        f'<g font-family="{html.escape(FONT, quote=True)}">',
        f'<text x="22" y="37" fill="{color["muted"]}" font-size="{TITLE_FONT_SIZE}">&gt; ~/</text>',
    ]
    for index, line in enumerate(title):
        x = 56 if index == 0 else 22
        output.append(
            f'<text x="{x}" y="{37 + index * 22}" fill="{color["value"]}" '
            f'font-size="{TITLE_FONT_SIZE}">{xml_escape(line)}</text>'
        )
    output.append(
        f'<line x1="22" y1="78" x2="498" y2="78" stroke="{color["border"]}"/>'
    )
    for index, line in enumerate(description):
        output.append(
            f'<text x="22" y="{104 + index * 23}" fill="{color["fg"]}" '
            f'font-size="{BODY_FONT_SIZE}">{xml_escape(line)}</text>'
        )

    metadata: list[tuple[str, str]] = []
    if repo.language:
        metadata.append(("lang", repo.language))
    metadata.extend((item, str(value)) for item, value in
                    (("stars", repo.stars), ("forks", repo.forks)))
    x = 22
    for index, (label, value) in enumerate(metadata):
        if index:
            output.append(
                f'<text x="{x}" y="260" fill="{color["muted"]}" '
                f'font-size="{BODY_FONT_SIZE}">·</text>'
            )
            x += 19
        label_text = f"{label}: "
        output.append(
            f'<text x="{x}" y="260" fill="{color["label"]}" '
            f'font-size="{BODY_FONT_SIZE}">{xml_escape(label_text)}</text>'
        )
        x += len(label_text) * BODY_FONT_SIZE * 0.6
        output.append(
            f'<text x="{x:.1f}" y="260" fill="{color["value"]}" '
            f'font-size="{BODY_FONT_SIZE}">{xml_escape(value)}</text>'
        )
        x += len(value) * BODY_FONT_SIZE * 0.6 + 10
    output.extend(("</g>", "</svg>", ""))
    return "\n".join(output)


def render_featured(repos: list[Repository]) -> str:
    if not repos:
        return "No pinned repositories yet."
    cards = []
    for repo in repos:
        url = html.escape(repo.url, quote=True)
        alt = html.escape(f"{repo.full_name} repository card", quote=True)
        light = html.escape(f"assets/featured/{filename(repo, 'light')}", quote=True)
        dark = html.escape(f"assets/featured/{filename(repo, 'dark')}", quote=True)
        cards.append(
            f'<a href="{url}"><picture>'
            f'<source media="(prefers-color-scheme: dark)" srcset="{dark}">'
            f'<source media="(prefers-color-scheme: light)" srcset="{light}">'
            f'<img src="{light}" alt="{alt}" width="49%">'
            f'</picture></a>'
        )
    # Two percentage-width images fit per line without a GitHub-unsupported stylesheet.
    return '<div align="center">\n' + '\n'.join(cards) + '\n</div>'


def render_focus(source: str) -> str:
    content = source.strip("\n")
    if not content.strip():
        raise ValueError("current-focus.txt must not be empty")
    longest = max((len(match.group()) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{content}\n{fence}"


def replace_section(readme: str, name: str, content: str) -> str:
    start = f"<!-- {name}:start -->"
    end = f"<!-- {name}:end -->"
    if readme.count(start) != 1 or readme.count(end) != 1:
        raise ValueError(f"README.md must contain exactly one {name} marker pair")
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    replacement = f"{start}\n{content.rstrip()}\n{end}"
    updated, count = pattern.subn(lambda _: replacement, readme)
    if count != 1:
        raise ValueError(f"README.md has invalid {name} marker order")
    return updated


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def main() -> None:
    repos = fetch_pinned(os.environ.get("GITHUB_TOKEN", ""))
    readme_path = ROOT / "README.md"
    focus_path = ROOT / "current-focus.txt"
    readme = readme_path.read_text(encoding="utf-8")
    updated = replace_section(readme, "featured-projects", render_featured(repos))
    updated = replace_section(updated, "current-focus", render_focus(
        focus_path.read_text(encoding="utf-8")))

    assets = ROOT / "assets" / "featured"
    assets.mkdir(parents=True, exist_ok=True)
    expected = set()
    changed = 0
    for repo in repos:
        for theme in ("dark", "light"):
            path = assets / filename(repo, theme)
            expected.add(path.name)
            changed += write_if_changed(path, render_card(repo, theme))
    for path in assets.glob("*.svg"):
        if path.name not in expected:
            path.unlink()
            changed += 1
    changed += write_if_changed(readme_path, updated)
    print(f"Rendered {len(repos)} pinned repositories; {changed} file(s) changed.")


if __name__ == "__main__":
    main()
