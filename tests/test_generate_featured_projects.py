import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from scripts import generate_featured_projects as generator


class FeaturedProjectsTests(unittest.TestCase):
    def test_fetch_preserves_pin_order_and_includes_organization_repositories(self):
        def repository(owner, name):
            return {
                "__typename": "Repository", "name": name,
                "nameWithOwner": f"{owner}/{name}", "description": None,
                "url": f"https://github.com/{owner}/{name}",
                "primaryLanguage": None, "stargazerCount": 0, "forkCount": 0,
            }

        payload = {"data": {"user": {"pinnedItems": {"nodes": [
            repository("team", "one"), {"__typename": "Gist"},
            repository("person", "two"), repository("team", "three"),
            repository("person", "four"), repository("person", "five"),
        ]}}}}
        response = io.BytesIO(json.dumps(payload).encode())
        with patch.object(generator.urllib.request, "urlopen", return_value=response):
            repos = generator.fetch_pinned("test-token")
        self.assertEqual([repo.full_name for repo in repos], [
            "team/one", "person/two", "team/three", "person/four"])

    def test_svg_and_markup_escape_unusual_content(self):
        repo = generator.Repository(
            name='a&<"', full_name='team/a&<"',
            description='A & <test> "quote"\nwith emoji 🐍 ' * 30,
            url='https://github.com/team/a%26%3C%22?x="&y=1',
            language=None, stars=3, forks=1,
        )
        svg = generator.render_card(repo, "dark")
        root = ElementTree.fromstring(svg)
        self.assertEqual(root.attrib["aria-label"], 'team/a&<" repository card')
        self.assertIn("No", generator.render_card(generator.Repository(
            "a", "team/a", None, "https://github.com/team/a", None, 0, 0), "light"))
        self.assertNotIn("lang:", svg)
        self.assertLessEqual(svg.count('font-size="12">'), 9)
        markup = generator.render_featured([repo])
        self.assertIn('href="https://github.com/team/a%26%3C%22?x=&quot;&amp;y=1"', markup)
        self.assertIn("(prefers-color-scheme: dark)", markup)
        self.assertIn("(prefers-color-scheme: light)", markup)
        self.assertIn('width="49%"', markup)
        self.assertNotEqual(generator.filename(repo, "dark"), generator.filename(
            generator.Repository("a", "other/a", None, "", None, 0, 0), "dark"))

    def test_no_pins_and_section_boundaries(self):
        self.assertEqual(generator.render_featured([]), "No pinned repositories yet.")
        source = "before\n<!-- featured-projects:start -->\nold\n<!-- featured-projects:end -->\nafter\n"
        output = generator.replace_section(source, "featured-projects", "new")
        self.assertEqual(output, source.replace("old", "new"))
        with self.assertRaises(ValueError):
            generator.replace_section("missing", "featured-projects", "new")

    def test_main_is_idempotent_and_removes_only_stale_featured_assets(self):
        repo = generator.Repository("one", "team/one", "Description", "https://github.com/team/one", "Python", 2, 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "before\n<!-- featured-projects:start -->\n<!-- featured-projects:end -->\n"
                "middle\n<!-- current-focus:start -->\n<!-- current-focus:end -->\nafter\n")
            (root / "current-focus.txt").write_text("Building: a < b & c\n")
            assets = root / "assets" / "featured"
            assets.mkdir(parents=True)
            (assets / "stale.svg").write_text("old")
            (root / "assets" / "unrelated.svg").write_text("keep")
            with patch.object(generator, "ROOT", root), patch.object(generator, "fetch_pinned", return_value=[repo]):
                with redirect_stdout(io.StringIO()) as first:
                    generator.main()
                snapshot = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
                with redirect_stdout(io.StringIO()) as second:
                    generator.main()
                repeated = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(snapshot, repeated)
            self.assertIn("0 file(s) changed", second.getvalue())
            self.assertFalse((assets / "stale.svg").exists())
            self.assertEqual((root / "assets" / "unrelated.svg").read_text(), "keep")
            readme = (root / "README.md").read_text()
            self.assertTrue(readme.startswith("before\n"))
            self.assertTrue(readme.endswith("after\n"))
            self.assertIn("Building: a < b & c", readme)


if __name__ == "__main__":
    unittest.main()
