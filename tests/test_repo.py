import importlib.util
import json
import os
import re
import unittest
from unittest import mock

from _load import ROOT

# v2, the day-trading pack: the twelve folders the reel's repo card shows
SKILLS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
          "trader-risk", "trader-budget", "trader-broker", "trader-alerts", "trader-analyst",
          "trader-pelosi", "trader-research"]
# portfolio basket (v1 skills moved here)
PORTFOLIO_SKILLS = ["trader-copycat", "trader-screener", "trader-tax", "trader-rebalance"]
ABOUT = ("12 skills for day trading: scan thousands of charts, track breaking news, time every "
         "entry and exit, replay every outcome before you risk a dollar, and dig into any stock: "
         "options, shorts, dark-pool flow, insider trades and the macro numbers.")
# skills on the way to an order carry the safety block
ORDER_PATH = ["trader-scanner", "trader-entry", "trader-exit", "trader-timemachine", "trader-budget",
              "trader-pelosi", "trader-risk", "trader-broker", "trader-alerts"]
# v1-only skills that should not appear in daytrader files (but are in portfolio/)
V1_ONLY = ["trader-copycat", "trader-screener", "trader-tax", "trader-rebalance"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_eleven_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_matches_the_reel(self):
        # trader/ is the runtime folder the skills write into (gitignored): it
        # appears the moment anyone runs the pack from this checkout. dist/,
        # node_modules/ and *.egg-info/ are the installer's build output,
        # which only exists after someone packages the repo.
        build = ("dist", "node_modules", "trader_skill.egg-info", ".pytest_cache")
        root = sorted(d for d in os.listdir(ROOT)
                      if d not in (".git", ".gitignore", ".github", "trader") + build)
        self.assertEqual(root, sorted(["plugin.json", "marketplace.json", "LICENSE",
                                       "README.md", "tests", "portfolio",
                                       "pyproject.toml", "package.json",
                                       "bin", "installer", "trader_memory"] + SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("yes", low, s)

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "trader-skill")
        # Agents discover SKILL.md folders themselves: no "skills" key, and the
        # manifest validates against the official plugin schema
        self.assertNotIn("skills", plugin)
        self.assertEqual(plugin["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "trader-skill")
        self.assertEqual(market["plugins"][0]["name"], "trader-skill")
        # no $schema in the marketplace manifest: no published schema for it,
        # and a dead link is worse than none
        self.assertNotIn("$schema", market)

    def test_readme_carries_the_reel_copy(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# The Trader skill"))
        for line in (ABOUT,
                     "git clone https://github.com/KDhiraj152/trader-skill.git",
                     "cp -r trader-skill/trader-*",
                     "`plugin.json` and `marketplace.json`",
                     "## Fine print"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            if not rel.startswith(os.path.join("tests", "fixtures")):  # fixtures are real data, kept as published
                self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)  # built, so this file passes too

    def test_no_agent_brand_names(self):
        # the pack installs on any agent: no agent or vendor name anywhere in
        # the shipped text (brokers like Alpaca and Interactive Brokers are
        # fine, they are not agents)
        brands = ("hermes", "claude", "anthropic", "openai", "codex", "nous")
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith(os.path.join("tests", "fixtures")) or rel == os.path.relpath(__file__, ROOT) \
                    or rel.startswith("trader" + os.sep):
                continue  # fixtures are real data; the runtime trader/ folder is generated, not shipped
            with open(path, encoding="utf-8", errors="replace") as fh:
                low = fh.read().lower()
            for b in brands:
                self.assertNotIn(b, low, rel)

    def test_license_says_k_dhiraj(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
            license_text = fh.read()
        self.assertIn("Copyright (c) 2026 K Dhiraj", license_text)
        # nobody else's name in the license or the credits
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith(os.path.join("tests", "fixtures")) or rel == os.path.relpath(__file__, ROOT):
                continue  # fixtures are real data; this test file names the string it guards against
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            self.assertNotIn("Jake", text, rel)
            self.assertNotIn("Schincariol", text, rel)

    def test_no_v1_only_skill_is_left_behind(self):
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith("tests" + os.sep) or rel == "README.md" or rel.startswith("portfolio" + os.sep):
                continue  # the README points v1 users to the v1 commit; portfolio/ contains v1 skills
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for old in V1_ONLY:
                self.assertNotIn(old, text, rel)

    def test_every_tool_runs_on_python_3_8(self):
        # no 3.9+ only modules or syntax in the tools (the README promises 3.8)
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix(",
                            "match ", "list[", "dict[", "tuple["):
                    if bad == "match ":
                        self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                    elif bad.endswith("["):
                        self.assertNotRegex(src, r"(?<![\w.])%s" % re.escape(bad), "%s/%s" % (s, f))
                    else:
                        self.assertNotIn(bad, src, "%s/%s" % (s, f))

    def test_day_trading_limits_ship_in_the_example_config(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_usd", "max_daily_loss_usd", "max_trades_per_day",
                  "min_reward_risk", "require_stop", "no_entries_after", "flat_by"):
            self.assertIn(k, cfg, k)
        self.assertIs(cfg["require_stop"], True)
        self.assertIs(cfg.get("allow_short", False), False)
        self.assertIs(cfg.get("allow_margin", False), False)

    def test_paper_trading_is_the_default(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg.get("allow_options", False), False)


class Package(unittest.TestCase):
    """The pack installs from pip and npm, and both ship the whole thing.

    `pipx install trader-skill` and `npx trader-skill` are first-class ways
    in, next to the clone-and-copy path. These tests keep the two packages
    in step with each other and with the plugin manifest.
    """

    def test_versions_agree_across_every_manifest(self):
        with open(os.path.join(ROOT, "plugin.json")) as fh:
            plugin = json.load(fh)["version"]
        with open(os.path.join(ROOT, "package.json")) as fh:
            npm = json.load(fh)["version"]
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
            m = re.search(r'(?m)^version = "(.+)"$', fh.read())
            pip = m.group(1) if m else None
        self.assertTrue(plugin and pip and npm, "a manifest is missing its version")
        self.assertEqual(plugin, pip, "plugin.json vs pyproject.toml")
        self.assertEqual(plugin, npm, "plugin.json vs package.json")

    def test_npm_package_bundles_the_pack(self):
        with open(os.path.join(ROOT, "package.json")) as fh:
            npm = json.load(fh)
        self.assertEqual(npm["name"], "trader-skill")
        self.assertEqual(npm["bin"], {"trader-skill": "bin/cli.js"})
        self.assertGreaterEqual(int(npm["engines"]["node"].lstrip(">=^~ ").split(".")[0]), 14)
        files = npm["files"]
        self.assertIn("bin/", files)
        self.assertIn("trader-*", files, "the npm tarball must carry the skill folders")
        self.assertIn("plugin.json", files)
        self.assertIn("marketplace.json", files)
        self.assertNotIn("tests", files)  # nobody needs the test suite in their npm install
        # what the shipped CLI promises is what the plugin manifest names
        with open(os.path.join(ROOT, "bin", "cli.js"), encoding="utf-8") as fh:
            cli = fh.read()
        for word in ("--dir", "--skills", "--force", "--list", "SKILL.md"):
            self.assertIn(word, cli, word)

    def test_pip_package_bundles_the_pack(self):
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
            pyproject = fh.read()
        self.assertIn('name = "trader-skill"', pyproject)
        self.assertIn('requires-python = ">=3.8"', pyproject)
        self.assertIn('trader-skill = "installer.cli:main"', pyproject)
        self.assertIn("force-include", pyproject)
        # every skill folder rides in the wheel
        for s in SKILLS:
            self.assertIn('"%s" = "installer/_pack/%s"' % (s, s), pyproject, s)
        self.assertIn('"plugin.json" = "installer/_pack/plugin.json"', pyproject)
        self.assertIn('"marketplace.json" = "installer/_pack/marketplace.json"', pyproject)
        with open(os.path.join(ROOT, "installer", "cli.py"), encoding="utf-8") as fh:
            cli = fh.read()
        for word in ("--skills", "--force", "_pack"):
            self.assertIn(word, cli, word)

    def test_installer_picks_a_destination_on_its_own(self):
        # bare `trader-skill install` must not ask the user for a path:
        # ./skills wins when the project has one, else ~/.agents/skills
        spec = importlib.util.spec_from_file_location(
            "ts_cli", os.path.join(ROOT, "installer", "cli.py"))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.dict(os.environ, {"HOME": "/tmp/ts-fake-home"}):
            self.assertEqual(cli.pick_destination(),
                             os.path.abspath("/tmp/ts-fake-home/.agents/skills"))
            self.assertEqual(cli.pick_destination("./elsewhere"),
                             os.path.abspath("./elsewhere"))


if __name__ == "__main__":
    unittest.main()
