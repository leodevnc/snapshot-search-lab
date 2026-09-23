import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from snapshot_search import Document, SearchIndex


class CrashTests(unittest.TestCase):
    def test_process_exit_during_build_leaves_prior_generation_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            index = SearchIndex(path)
            original = Document("deploy", "Deployment", "Require one approval.")
            first = index.build([original])
            index.activate(first.generation, expected_active=None)
            script = """
import os
import sys
from snapshot_search import Document, SearchIndex
index = SearchIndex(sys.argv[1])
def source():
    yield Document('deploy', 'Deployment', 'Require two approvals.')
    os._exit(17)
index.build(source())
"""
            result = subprocess.run([sys.executable, "-c", script, str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 17, result.stderr)
            reopened = SearchIndex(path)
            self.assertEqual(reopened.generations(), (first,))
            self.assertEqual(reopened.active_generation(), first.generation)
            hit = reopened.search("deployment").hits[0]
            self.assertEqual(reopened.resolve(hit.citation), original)
            self.assertEqual(reopened.build([original]).document_count, 1)


if __name__ == "__main__":
    unittest.main()
