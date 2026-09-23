# Learning notes

The first question was whether changing an active index could make a prior citation point at
different evidence. A citation tied only to a document ID has that ambiguity. Binding it to a
generation and digest makes the intended revision explicit and testable.

A second issue appeared in ranking. Filtering a shared search index by generation does not
necessarily isolate the statistics used to score results. This implementation gives every
generation a separate FTS index; a regression test adds a large replacement corpus and checks
that old hits and scores remain identical.

Atomic construction and atomic activation solve different problems. Construction prevents partial
indexes. Activation prevents readers from mixing current and staged data. The expected-active
check stops two simultaneous publishers from silently replacing each other's work, but it does
not detect an intervening change that eventually restores the same active ID.

The failure experiments cover a source iterator raising an exception, a Python interruption, and
a subprocess exiting without cleanup after an insert. Each leaves the old active generation
usable. A separate reader continues searching while a build is deliberately paused before commit.

The next unresolved tension is retention. Keeping old evidence helps reproducibility, while
deletion requirements may demand removing it. A retention policy must state what happens to an
outstanding citation before old generations can be pruned safely.
