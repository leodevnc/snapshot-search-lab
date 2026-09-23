"""Immutable lexical indexes with atomic publication and verifiable citations."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


class ActivationConflict(RuntimeError):
    """Another publisher changed the active generation."""


class CitationMismatch(ValueError):
    """The requested citation does not identify the stored content."""


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    body: str

    def __post_init__(self) -> None:
        for name, maximum in (("doc_id", 256), ("title", 1024), ("body", 1_000_000)):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError(f"{name} must be nonblank text of at most {maximum} characters")
            if "\x00" in value:
                raise ValueError(f"{name} must not contain NUL")

    @property
    def digest(self) -> str:
        return _digest([self.doc_id, self.title, self.body])


@dataclass(frozen=True)
class Generation:
    generation: int
    document_count: int
    manifest_digest: str


@dataclass(frozen=True)
class Citation:
    generation: int
    doc_id: str
    digest: str


@dataclass(frozen=True)
class Hit:
    title: str
    excerpt: str
    score: float
    citation: Citation


@dataclass(frozen=True)
class SearchResult:
    generation: int
    hits: tuple[Hit, ...]


class SearchIndex:
    """Single-host SQLite index. Each public call owns and closes its connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if not self.path or self.path == ":memory:":
            raise ValueError("a persistent file path is required")
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        with self._transaction(write=True) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS generations (
                    generation INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    manifest_digest TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS active (
                    slot INTEGER PRIMARY KEY CHECK (slot = 1),
                    generation INTEGER REFERENCES generations(generation)
                )"""
            )
            connection.execute("INSERT OR IGNORE INTO active VALUES (1, NULL)")

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10, isolation_level=None)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _table(generation: int) -> str:
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be a positive integer")
        return f"corpus_{generation}"

    @staticmethod
    def _require(connection: sqlite3.Connection, generation: int) -> None:
        SearchIndex._table(generation)
        if connection.execute(
            "SELECT 1 FROM generations WHERE generation=?", (generation,)
        ).fetchone() is None:
            raise LookupError(f"unknown generation: {generation}")

    def active_generation(self) -> int | None:
        with self._transaction() as connection:
            return connection.execute("SELECT generation FROM active WHERE slot=1").fetchone()[0]

    def generations(self) -> tuple[Generation, ...]:
        with self._transaction() as connection:
            return tuple(
                Generation(*row)
                for row in connection.execute("SELECT * FROM generations ORDER BY generation")
            )

    def build(self, documents: Iterable[Document]) -> Generation:
        """Commit a complete, inactive generation or leave no partial index behind."""
        with self._transaction(write=True) as connection:
            generation = connection.execute("INSERT INTO generations DEFAULT VALUES").lastrowid
            table = self._table(generation)
            connection.execute(
                f"CREATE VIRTUAL TABLE {table} USING fts5("
                "doc_id UNINDEXED, title, body, digest UNINDEXED, tokenize='unicode61')"
            )
            manifest: dict[str, str] = {}
            for document in documents:
                if not isinstance(document, Document):
                    raise TypeError("build expects Document instances")
                if document.doc_id in manifest:
                    raise ValueError(f"duplicate document id: {document.doc_id}")
                if len(manifest) >= 10_000:
                    raise ValueError("this prototype supports at most 10000 documents per generation")
                manifest[document.doc_id] = document.digest
                connection.execute(
                    f"INSERT INTO {table} (doc_id, title, body, digest) VALUES (?, ?, ?, ?)",
                    (document.doc_id, document.title, document.body, document.digest),
                )
            digest = _digest(sorted(manifest.items()))
            connection.execute(
                "UPDATE generations SET document_count=?, manifest_digest=? WHERE generation=?",
                (len(manifest), digest, generation),
            )
            return Generation(generation, len(manifest), digest)

    def activate(self, generation: int, *, expected_active: int | None) -> None:
        """Publish with compare-and-swap; old generations may also be reactivated."""
        if expected_active is not None:
            self._table(expected_active)
        with self._transaction(write=True) as connection:
            self._require(connection, generation)
            current = connection.execute("SELECT generation FROM active WHERE slot=1").fetchone()[0]
            if current != expected_active:
                raise ActivationConflict(f"expected active {expected_active}, found {current}")
            connection.execute("UPDATE active SET generation=? WHERE slot=1", (generation,))

    def search(self, query: str, *, generation: int | None = None, limit: int = 5) -> SearchResult:
        """Search literal terms joined with AND; do not expose the FTS query language."""
        if not isinstance(query, str) or len(query) > 512:
            raise ValueError("query must be text of at most 512 characters")
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not terms or len(terms) > 32:
            raise ValueError("query must contain between 1 and 32 alphanumeric terms")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        expression = " AND ".join('"' + term + '"' for term in terms)
        with self._transaction() as connection:
            if generation is None:
                generation = connection.execute(
                    "SELECT generation FROM active WHERE slot=1"
                ).fetchone()[0]
                if generation is None:
                    raise LookupError("no active generation; build and activate one first")
            self._require(connection, generation)
            table = self._table(generation)
            rows = connection.execute(
                f"SELECT doc_id, title, digest, snippet({table}, 2, '', '', ' ... ', 24) AS excerpt, "
                f"bm25({table}) AS score FROM {table} WHERE {table} MATCH ? "
                "ORDER BY score, doc_id COLLATE BINARY LIMIT ?",
                (expression, limit),
            ).fetchall()
            hits = tuple(
                Hit(row["title"], row["excerpt"], row["score"],
                    Citation(generation, row["doc_id"], row["digest"]))
                for row in rows
            )
            return SearchResult(generation, hits)

    def resolve(self, citation: Citation) -> Document:
        """Fetch the exact cited revision, independently of the active generation."""
        with self._transaction() as connection:
            self._require(connection, citation.generation)
            table = self._table(citation.generation)
            row = connection.execute(
                f"SELECT doc_id, title, body, digest FROM {table} WHERE doc_id=?", (citation.doc_id,)
            ).fetchone()
            if row is None:
                raise LookupError(f"unknown document: {citation.doc_id}")
            document = Document(row["doc_id"], row["title"], row["body"])
            if citation.digest != row["digest"] or citation.digest != document.digest:
                raise CitationMismatch("citation digest does not match stored document")
            return document
