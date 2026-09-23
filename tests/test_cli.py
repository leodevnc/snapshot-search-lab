import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def test_document_update_preserves_prior_cli_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = [sys.executable, "-m", "snapshot_search", "--db", str(Path(directory) / "index.sqlite3")]
            def run(*args):
                result = subprocess.run(prefix + list(args), capture_output=True, text=True, check=True)
                return json.loads(result.stdout)
            first = run("build", "examples/runbooks-v1.json")["generation"]
            run("activate", str(first), "--expected", "none")
            citation = run("search", "deployment")["hits"][0]["citation"]
            second = run("build", "examples/runbooks-v2.json")["generation"]
            run("activate", str(second), "--expected", str(first))
            self.assertIn("two approvals", run("search", "deployment")["hits"][0]["excerpt"])
            original = run("resolve", str(citation["generation"]), citation["doc_id"], citation["digest"])
            self.assertIn("one approval", original["body"])
            failure = subprocess.run(prefix + ["activate", str(first), "--expected", "none"],
                                     capture_output=True, text=True)
            self.assertEqual(failure.returncode, 2)
            self.assertIn("expected active", failure.stderr)
            self.assertNotIn("Traceback", failure.stderr)


if __name__ == "__main__":
    unittest.main()
