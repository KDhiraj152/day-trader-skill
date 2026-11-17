"""Guards for the pack's copy structure.

Each skill folder carries its own copy of the shared helpers (eastern time,
holidays, json and price loaders) because Hermes installs skills as standalone
folders: one folder, no shared import. That is a design constraint, not an
accident. The cost is drift: a fix applied to one copy but not its siblings.
These tests catch that. If a variation is deliberate, add (name, folder) to
ALLOWED with a reason, or rename the function.
"""

import ast
import importlib.util
import inspect
import json
import os
import re
import unittest

from _load import ROOT

SKILLS = sorted(d for d in os.listdir(ROOT)
                if os.path.isdir(os.path.join(ROOT, d)) and d.startswith("trader-"))

# deliberately divergent copies: (function, folder). Keep it short and give
# the reason, so the next person does not re-unify them.
ALLOWED = set()

# functions that exist in several folders and are meant to differ per tool
KNOWN_DIFFERENT = {"main", "compute", "describe", "evaluate", "render", "report",
                   "fingerprint", "parse_now", "select", "iso", "pct", "money",
                   "read_config", "read_json", "read_state", "load_prices",
                   "load_state", "parse_chart",
                   "session_bars", "chart_path", "yahoo_get", "yahoo_symbol",
                   "write_json", "write",
                   "cmd_check", "cmd_show", "_write", "parse_hhmm", "parse_clock",
                   # private helpers that are one tool's internals, not shared logic
                   "_get", "_p", "_load", "_num"}


def canon(src):
    """Comparable form of a function source: alias-proof, comment-free,
    docstring-free, whitespace-free."""
    src = re.sub(r"\b_dt\.", "datetime.", src)
    tree = ast.parse(src)
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(getattr(fn.body[0], "value", None), ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body = fn.body[1:] or [ast.Pass()]
    return ast.dump(fn)


def functions():
    """name -> {folder: canon source}, module-level functions only."""
    out = {}
    for s in SKILLS:
        folder = os.path.join(ROOT, s)
        for f in os.listdir(folder):
            if not f.endswith(".py"):
                continue
            spec = importlib.util.spec_from_file_location("dg_" + s, os.path.join(folder, f))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for name, fn in vars(mod).items():
                if inspect.isfunction(fn) and fn.__module__ == "dg_" + s:
                    out.setdefault(name, {})[s] = canon(inspect.getsource(fn))
    return out


class SharedCopies(unittest.TestCase):
    def test_shared_code_stays_in_sync(self):
        drifted = []
        for name, folders in functions().items():
            if len(folders) < 2:
                continue
            watched = {f: c for f, c in folders.items()
                       if (name, f) not in ALLOWED and name not in KNOWN_DIFFERENT}
            if len(watched) > 1 and len(set(watched.values())) > 1:
                drifted.append("%s: %s" % (name, ", ".join(sorted(watched))))
        self.assertEqual(drifted, [], "shared copies drifted; the same function "
                         "differs between folders. Propagate the change to every "
                         "copy, or add (name, folder) to ALLOWED in "
                         "tests/test_copies.py with a reason:\n  " + "\n  ".join(drifted))

    def test_known_differ_list_is_not_stale(self):
        # a name listed as meant-to-differ must actually differ (or exist once),
        # otherwise it belongs in the watched set, not in KNOWN_DIFFERENT
        stale = []
        for name in KNOWN_DIFFERENT:
            folders = functions().get(name, {})
            if len(set(folders.values())) == 1 and len(folders) > 1:
                stale.append(name)
        self.assertEqual(stale, [], "these are now identical across folders: %s; "
                         "remove them from KNOWN_DIFFERENT" % ", ".join(stale))


class Versions(unittest.TestCase):
    def test_every_user_agent_matches_plugin_version(self):
        with open(os.path.join(ROOT, ".hermes-plugin", "plugin.json")) as fh:
            version = json.load(fh)["version"]
        minor = ".".join(version.split(".")[:2])  # 2.0.0 -> 2.0
        wrong = []
        for s in SKILLS + ["portfolio"]:
            folder = os.path.join(ROOT, s)
            for base, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    path = os.path.join(base, f)
                    with open(path, encoding="utf-8") as fh:
                        for m in re.finditer(r"(?:day-trader-skill|trader-skill)/(\d+\.\d+)", fh.read()):
                            if m.group(1) != minor:
                                wrong.append("%s says /%s" % (os.path.relpath(path, ROOT), m.group(1)))
        self.assertEqual(wrong, [], "user agents disagree with plugin.json's %s: %s"
                         % (version, ", ".join(wrong)))


if __name__ == "__main__":
    unittest.main()
