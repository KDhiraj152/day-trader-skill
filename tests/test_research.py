"""Tests for the research desk: offline fixtures, graceful failures, URLs.

The desk is the one skill that talks to a server you run (OpenBB, free, no
key). The suite never needs that server: --offline DIR reads the fixture
files, and a fake urllib catches the URLs the desk builds.
"""

import io
import json
import os
import subprocess
import sys
import unittest
import urllib.request
from unittest import mock

from _load import ROOT

sys.path.insert(0, os.path.dirname(__file__))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "dg_research", os.path.join(ROOT, "trader-research", "research.py"))
research = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(research)

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "research")


def run_cli(*argv):
    cmd = [sys.executable, os.path.join(ROOT, "trader-research", "research.py")]
    out = subprocess.run(cmd + list(argv), capture_output=True, text=True, timeout=60)
    return out.returncode, out.stdout, out.stderr


class Offline(unittest.TestCase):
    """Every command renders from the fixtures and says nothing false."""

    def test_every_command_runs_offline(self):
        base = ["--offline", FIXTURES]
        cases = [
            (["quote", "TSLA"], ["delayed", "iv30", "52w"]),
            (["shorts", "TSLA", "--limit", "3"], ["days cover", "2026-10-30"]),
            (["darkpool", "TSLA", "--limit", "2"], ["avg trade size"]),
            (["ftd", "TSLA", "--limit", "2"], ["Fails to deliver"]),
            (["insider", "TSLA", "--limit", "2"], ["Insider trades"]),
            (["filings", "TSLA", "--limit", "2"], ["Filings, TSLA"]),
            (["news", "TSLA", "--limit", "2"], ["Headlines, TSLA"]),
            (["calendar", "--days", "7", "--limit", "3"], ["Earnings,", "eps est"]),
            (["macro", "FEDFUNDS"], ["Macro, FEDFUNDS"]),
            (["chains", "TSLA"], ["expiration", "contracts"]),
            (["chains", "TSLA", "--expiration", "2026-11-18", "--limit", "2"],
             ["spot", "delta", "theta", "call"]),
        ]
        for argv, needles in cases:
            code, out, err = run_cli(*(base + argv))
            self.assertEqual(code, 0, "%s: %s" % (" ".join(argv), err))
            for needle in needles:
                self.assertIn(needle, out, " ".join(argv))

    def test_chains_lists_expirations_before_picking_one(self):
        code, out, _ = run_cli("--offline", FIXTURES, "chains", "TSLA")
        self.assertEqual(code, 0)
        self.assertIn("2026-11-18", out)
        self.assertNotIn("delta", out)  # the table only comes with --expiration

    def test_unknown_expiration_is_a_message_not_a_trace(self):
        code, _, err = run_cli("--offline", FIXTURES, "chains", "TSLA",
                               "--expiration", "2099-01-01")
        self.assertEqual(code, 2)
        self.assertIn("no contracts at 2099-01-01", err)
        self.assertNotIn("Traceback", err)

    def test_json_output_is_the_raw_rows(self):
        code, out, _ = run_cli("--offline", FIXTURES, "--json", "quote", "TSLA")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["symbol"], "TSLA")

    def test_missing_offline_file_is_a_message(self):
        code, _, err = run_cli("--offline", FIXTURES, "quote", "ZZZZ")
        self.assertEqual(code, 2)
        self.assertIn("not there", err)
        self.assertNotIn("Traceback", err)


class Server(unittest.TestCase):
    """Against a server that is down, the desk explains and stops."""

    def test_dead_server_names_the_fix(self):
        code, _, err = run_cli("--base", "http://127.0.0.1:1", "quote", "TSLA")
        self.assertEqual(code, 2)
        self.assertIn("openbb-api", err)
        self.assertIn("OPENBB_BASE_URL", err)
        self.assertNotIn("Traceback", err)

    def test_url_is_root_plus_api_plus_query(self):
        captured = {}

        def fake_urlopen(url, timeout=None):
            captured["url"] = url
            return io.StringIO(json.dumps({"results": [{"symbol": "TSLA"}]}))

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            rows = research._get("/cboe/equity/quote", {"symbol": "TSLA"},
                                 base="http://127.0.0.1:6900")
        self.assertEqual(rows, [{"symbol": "TSLA"}])
        self.assertEqual(captured["url"],
                         "http://127.0.0.1:6900/api/v1/cboe/equity/quote?symbol=TSLA")

    def test_server_warning_is_printed_not_swallowed(self):
        def fake_urlopen(url, timeout=None):
            return io.StringIO(json.dumps(
                {"results": [], "warnings": [{"message": "rate limited"}]}))

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rows = research._get("/cboe/equity/quote", {"symbol": "TSLA"},
                                 base="http://127.0.0.1:6900")
        self.assertEqual(rows, [])
        self.assertIn("rate limited", err.getvalue())

    def test_base_url_env_var_wins_over_config(self):
        with mock.patch.dict(os.environ, {"OPENBB_BASE_URL": "http://10.0.0.5:9999"}):
            self.assertEqual(research.read_base(), "http://10.0.0.5:9999")


class Folder(unittest.TestCase):
    def test_mcp_example_is_the_standard_shape(self):
        with open(os.path.join(ROOT, "trader-research", "mcp_servers.example.json")) as fh:
            data = json.load(fh)
        self.assertIn("mcpServers", data)
        server = data["mcpServers"]["openbb"]
        self.assertIn("url", server)
        self.assertEqual(server["url"], "http://127.0.0.1:8001/mcp")


if __name__ == "__main__":
    unittest.main()
