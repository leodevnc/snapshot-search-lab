# Roadmap

## Completed: generation-bound retrieval

- Full-corpus builds with transactional rollback
- Explicit activation with expected-active conflict detection
- Search and citation resolution against immutable generations
- Generation-local relevance statistics and deterministic tie breaking
- Fictional runbook revisions and CLI walkthrough
- Failure, concurrency, restart, and subprocess-crash tests

## Next experiment: retention and pinned readers

Define explicit retention rules and allow consumers to pin generations for a bounded period.
Test pruning against active generations, outstanding pins, and expired citations. Document how
deletion requests override historical reproducibility and how clients discover an expired citation.

## Further questions

- Add a publication epoch to detect A -> B -> A changes.
- Measure rebuild time, retained bytes, and query latency as corpus sizes grow.
- Compare lexical relevance with a labeled retrieval dataset before adding another retriever.
- Define an index-format version and migration policy across SQLite versions.
