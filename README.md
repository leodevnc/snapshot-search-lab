# snapshot-search-lab

What happens to a search result when its source document changes before someone follows the
citation? This project explores that question with a small local document index.

Each rebuild creates an immutable **generation**. Publication switches one active pointer after
the complete generation has been committed. Every result includes its generation, document ID,
and content digest, so a citation can still retrieve the original text after an update or rollback.

The example corpus is a set of fictional operational runbooks. The same consistency question
appears when retrieved passages are passed to an assistant: the cited evidence should identify
the text actually retrieved.

## Quick start

Use Python 3.11+ with SQLite FTS5 enabled. There are no runtime dependencies or external services.
Run commands from the repository root. Choose a **new database path** for the numbered example:

```bash
python -m unittest discover -s tests -v
python -m snapshot_search --db demo.sqlite3 build examples/runbooks-v1.json
python -m snapshot_search --db demo.sqlite3 activate 1 --expected none
python -m snapshot_search --db demo.sqlite3 search deployment
```

The result cites generation 1 and says deployment requires one approval. Build and inspect the
replacement before making it active:

```bash
python -m snapshot_search --db demo.sqlite3 build examples/runbooks-v2.json
python -m snapshot_search --db demo.sqlite3 search deployment --generation 2
python -m snapshot_search --db demo.sqlite3 activate 2 --expected 1
python -m snapshot_search --db demo.sqlite3 search deployment
python -m snapshot_search --db demo.sqlite3 search deployment --generation 1
```

The current result now says **two approvals**; the explicitly pinned result still says **one
approval**. To resolve a citation, copy all three fields from a search result:

```bash
python -m snapshot_search --db demo.sqlite3 resolve 1 deploy COPIED_DIGEST
```

`COPIED_DIGEST` is a placeholder, not an example digest. A mismatch fails explicitly. Generation
numbers in existing databases may differ; `status` lists the active pointer and completed builds.

Rollback uses the same guarded activation operation:

```bash
python -m snapshot_search --db demo.sqlite3 activate 1 --expected 2
python -m snapshot_search --db demo.sqlite3 status
```

## Implemented behavior

- Whole-corpus builds commit completely or leave no partial generation.
- A staged generation is queryable without changing the active one.
- Publication requires the active generation to match the caller's expectation.
- Separate FTS5 indexes keep each generation's ranking statistics independent.
- Citations resolve exact document revisions and verify their SHA-256 digests.
- Plain-text queries use literal terms joined with AND; raw FTS operators are not exposed.
- A complete replacement corpus defines deletions from current search results.

The library API is also usable directly:

```python
from snapshot_search import Document, SearchIndex

index = SearchIndex("library-demo.sqlite3")
expected = index.active_generation()
built = index.build([Document("guide", "Cache recovery", "Inspect cache timeout metrics.")])
index.activate(built.generation, expected_active=expected)
hit = index.search("cache timeout").hits[0]
assert index.resolve(hit.citation).doc_id == "guide"
```

## Scope and limitations

This is a single-host, lexical retrieval prototype using SQLite FTS5 and BM25. It has no embedding
model, answer generation, HTTP service, or cloud deployment. Python's bundled SQLite must include
FTS5. A missing extension causes initialization of a build to fail.

Builds serialize writers and retain full copies. The input guard is 10,000 documents per generation,
not a measured capacity claim. There is no automatic retention policy. **Removing a document from
the new corpus does not erase historical copies**; old citations can still access them. Use only
public or synthetic source documents for this experiment.

The digest detects an incorrect or changed citation target; it is not a signature or an access
control mechanism. A production retrieval service also needs tenant authorization, retention,
resource limits, relevance evaluation, and operational measurements.

## Study record

- [Architecture and invariants](docs/architecture.md)
- [Design decisions](docs/decisions.md)
- [Test evidence](docs/test-evidence.md)
- [Learning notes](docs/learning-notes.md)
- [Remaining experiments](docs/roadmap.md)

Tests run locally with the command above. An optional [GitHub Actions template](ci/github-actions.yml)
is provided but is not installed as a workflow. See [test evidence](docs/test-evidence.md) for status.

## License

MIT
