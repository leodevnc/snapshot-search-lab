# Design decisions

## 001: Separate build from publication

A successful rebuild should be inspectable before it replaces live search. `build` returns a
completed but inactive generation, and `activate` performs a small guarded pointer update.
This also makes rollback a pointer change. The cost is retained storage and a second explicit step.

## 002: Use a complete index per generation

A shared FTS index with a generation column looks simpler, but document-frequency statistics
would cross generation boundaries. Independent FTS tables keep old ranking results stable when
unrelated new corpora are added. Storage and full rebuild cost are accepted for the local experiment.

## 003: Make the citation identify content

Document ID alone points to a logical document, not a revision. Each citation carries generation,
ID, and SHA-256 digest. Resolution fetches that version and recomputes the digest. It does not
claim authenticity: someone able to rewrite the database and a citation can change both.

## 004: Use plain lexical queries

The search API extracts alphanumeric terms, quotes them, and joins them with AND. Reserved words
such as OR are ordinary terms. This makes query behavior small and testable, but it does not offer
phrase syntax, prefixes, multilingual segmentation, synonyms, or semantic retrieval.

## 005: Retain all completed generations initially

Pruning would invalidate citations and require a policy for pinned consumers, retention windows,
and deletion requirements. This milestone has no automatic pruning. Historical storage is therefore
unbounded across builds even though individual builds have an input-count limit.
