# Architecture

## Data flow

```text
Complete source corpus -> build transaction -> immutable generation N
                                                  |
                               inspect with search(generation=N)
                                                  |
                         activate(N, expected_active=previous)
                                                  |
                                         active pointer
                                                  |
                              search -> citation(N, doc_id, digest)
                                                  |
                                        resolve exact content
```

The catalog contains completed generation metadata and a single active pointer. Each generation
has its own FTS5 table containing document ID, title, body, and digest. Only title and body are
indexed. User data is bound as SQL parameters; generated table names use validated positive
integer IDs assigned by SQLite.

## Transaction boundaries

`build` starts `BEGIN IMMEDIATE`, allocates a generation, creates the FTS table, consumes the source
iterator, and writes a manifest digest. Commit makes the completed generation visible. Failure
rolls back the table and catalog entry together. Source parsing and indexing hold the write lock;
this intentionally simple model is unsuitable for large or remote streaming inputs.

`activate` takes a separate write transaction, checks the completed target and expected active
generation, then updates the pointer. The compare-and-swap rejects a publisher whose expected
value is no longer current. It compares IDs, not a monotonic publication epoch: an A -> B -> A
sequence is not detected by a later operation expecting A.

`search` reads the active pointer and queries its FTS table inside one read transaction. All hits
in the returned object share that generation. A caller may pin a completed generation explicitly.
Old generations are never modified by the public API, so `resolve` can follow citations after
publication changes. No generation-pruning API is implemented.

WAL lets an existing reader observe committed content while a rebuild writes its replacement.
Writers still serialize. Initializing a new SearchIndex instance also takes a schema write lock
and can wait behind an ongoing build; reuse an initialized instance for concurrent reading.
Every public call opens and closes its own connection; state lives in the database, not in a
shared Python connection. See SQLite's [isolation documentation](https://www.sqlite.org/isolation.html).

## Content identity and ranking

A document digest hashes a canonical JSON array of its ID, title, and body. The manifest hashes
sorted `(document ID, document digest)` pairs, making it independent of input order. It describes
source content, not the SQLite binary representation or a cross-version ranking guarantee.

Separate FTS tables also isolate BM25 corpus statistics. A generation filter on one shared FTS
table would filter rows but leave scoring dependent on documents in other generations. Scores
sort ascending under SQLite's BM25 convention, with document ID as a deterministic tie breaker.
See the [FTS5 reference](https://www.sqlite.org/fts5.html#the_bm25_function).

## Guarantees and limits

| Property | Boundary |
| --- | --- |
| No partially visible rebuild | One SQLite transaction covers source ingestion and index creation |
| Complete publication | Active pointer references a committed generation |
| Stable historical source | API retains immutable generations and returns generation-bound citations |
| Stable historical scores | Separate indexes isolate statistics; tested within the same runtime |
| Digest verification | Detects changed content, but does not authenticate its author |
| Writer conflict detection | Expected active ID check; no publication history or ABA protection |
| Search relevance | Lexical AND matching; semantic correctness is not measured |
| Deletion | Removes documents from new generations, not old stored copies |

There is no network listener or provider integration. Database file access is the trust boundary.
Do not place the database on a multi-host shared filesystem. Retrieved text is data; this library
does not judge whether it is trustworthy or safe to include in an assistant's instructions.
