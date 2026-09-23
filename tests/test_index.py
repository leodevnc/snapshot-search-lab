import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from snapshot_search import (
    ActivationConflict, Citation, CitationMismatch, Document, SearchIndex,
)


OLD = Document("deploy", "Deployment procedure", "Deployment requires one approval.")
NEW = Document("deploy", "Deployment procedure", "Deployment requires two approvals.")


class IndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "search.sqlite3"
        self.index = SearchIndex(self.path)

    def publish(self, documents, expected=None):
        generation = self.index.build(documents).generation
        self.index.activate(generation, expected_active=expected)
        return generation

    def test_no_implicit_publication(self):
        self.index.build([OLD])
        self.assertIsNone(self.index.active_generation())
        with self.assertRaisesRegex(LookupError, "no active"):
            self.index.search("deployment")

    def test_staged_generation_is_searchable_without_changing_active(self):
        old = self.publish([OLD])
        staged = self.index.build([NEW]).generation
        self.assertEqual(self.index.search("deployment").generation, old)
        hit = self.index.search("deployment", generation=staged).hits[0]
        self.assertEqual(self.index.resolve(hit.citation), NEW)

    def test_old_citation_survives_update_and_restart(self):
        old = self.publish([OLD])
        citation = self.index.search("deployment").hits[0].citation
        current = self.publish([NEW], expected=old)
        restarted = SearchIndex(self.path)
        self.assertEqual(restarted.active_generation(), current)
        self.assertEqual(restarted.resolve(citation), OLD)
        self.assertEqual(restarted.resolve(restarted.search("deployment").hits[0].citation), NEW)

    def test_deletion_affects_new_generation_only(self):
        old = self.publish([OLD])
        citation = self.index.search("deployment").hits[0].citation
        self.publish([], expected=old)
        self.assertEqual(self.index.search("deployment").hits, ())
        self.assertEqual(self.index.resolve(citation), OLD)

    def test_old_ranking_and_scores_do_not_change_after_new_build(self):
        old = self.publish([OLD, Document("other", "Deployment", "Deployment deployment guide.")])
        before = self.index.search("deployment", generation=old)
        self.index.build([Document(str(i), "Deployment", "Deployment " * 30) for i in range(100)])
        self.assertEqual(self.index.search("deployment", generation=old), before)

    def test_manifest_is_independent_of_input_order(self):
        other = Document("cache", "Cache", "Cache timeout recovery.")
        first = self.index.build([OLD, other])
        second = self.index.build([other, OLD])
        third = self.index.build([NEW, other])
        self.assertEqual(first.manifest_digest, second.manifest_digest)
        self.assertNotEqual(first.manifest_digest, third.manifest_digest)

    def test_partial_source_failure_rolls_back_catalog_and_fts_tables(self):
        old = self.publish([OLD])
        before = self.index.generations()
        def broken_source():
            yield NEW
            raise RuntimeError("source disconnected")
        with self.assertRaisesRegex(RuntimeError, "source disconnected"):
            self.index.build(broken_source())
        self.assertEqual(self.index.generations(), before)
        self.assertEqual(self.index.active_generation(), old)
        with sqlite3.connect(self.path) as connection:
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='corpus_2'"
            ).fetchone())

    def test_duplicate_ids_roll_back_build(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.index.build([OLD, NEW])
        self.assertEqual(self.index.generations(), ())

    def test_interruption_rolls_back_build(self):
        def interrupted():
            yield OLD
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.index.build(interrupted())
        self.assertEqual(self.index.generations(), ())

    def test_reader_can_search_during_uncommitted_build(self):
        old = self.publish([OLD])
        inserted = threading.Event()
        release = threading.Event()
        def slow_source():
            yield NEW
            inserted.set()
            if not release.wait(10):
                raise TimeoutError("test did not release builder")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.index.build, slow_source())
            try:
                self.assertTrue(inserted.wait(5))
                result = self.index.search("deployment")
                self.assertEqual(result.generation, old)
                self.assertEqual(self.index.resolve(result.hits[0].citation), OLD)
            finally:
                release.set()
            future.result(timeout=5)

    def test_competing_publishers_have_one_winner(self):
        old = self.publish([OLD])
        staged = [self.index.build([NEW]).generation for _ in range(2)]
        barrier = threading.Barrier(2)
        def activate(generation):
            barrier.wait(timeout=5)
            try:
                self.index.activate(generation, expected_active=old)
                return generation
            except ActivationConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(activate, staged))
        winners = [value for value in results if value is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.index.active_generation(), winners[0])

    def test_rollback_reactivates_prior_generation(self):
        old = self.publish([OLD])
        new = self.publish([NEW], expected=old)
        self.index.activate(old, expected_active=new)
        self.assertEqual(self.index.resolve(self.index.search("deployment").hits[0].citation), OLD)

    def test_unknown_generation_does_not_change_active(self):
        old = self.publish([OLD])
        with self.assertRaises(LookupError):
            self.index.activate(999, expected_active=old)
        self.assertEqual(self.index.active_generation(), old)

    def test_citation_digest_is_checked(self):
        self.publish([OLD])
        citation = self.index.search("deployment").hits[0].citation
        with self.assertRaises(CitationMismatch):
            self.index.resolve(replace(citation, digest="0" * 64))
        with self.assertRaises(LookupError):
            self.index.resolve(replace(citation, doc_id="missing"))

    def test_stored_content_tampering_is_detected(self):
        generation = self.publish([OLD])
        citation = self.index.search("deployment").hits[0].citation
        with sqlite3.connect(self.path) as connection:
            connection.execute(f"UPDATE corpus_{generation} SET body='changed'")
        with self.assertRaises(CitationMismatch):
            self.index.resolve(citation)

    def test_fts_operators_are_searched_as_literal_terms(self):
        self.publish([OLD, Document("syntax", "Operator", "Deployment OR cache")])
        result = self.index.search('deployment OR "cache"*')
        self.assertEqual([hit.citation.doc_id for hit in result.hits], ["syntax"])

    def test_equal_scores_use_document_id_as_tiebreaker(self):
        self.publish([Document(key, "Cache", "Timeout recovery") for key in ("z", "a")])
        self.assertEqual([h.citation.doc_id for h in self.index.search("cache").hits], ["a", "z"])

    def test_query_generation_and_document_validation(self):
        self.publish([OLD])
        for query in ("", "!!!", "x " * 33, "x" * 513):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.index.search(query)
        for generation in (True, -1, "1; DROP TABLE active"):
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                self.index.search("deployment", generation=generation)
        for limit in (0, 101, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.index.search("deployment", limit=limit)
        with self.assertRaises(ValueError):
            Document("", "title", "body")
        with self.assertRaises(ValueError):
            Document("id", "title", "\x00")


if __name__ == "__main__":
    unittest.main()
