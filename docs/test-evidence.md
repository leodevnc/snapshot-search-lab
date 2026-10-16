# Testing

Run from the repository root:

```bash
python -m unittest discover -s tests -v
```

The suite exercises observable behavior, using temporary database files and controlled concurrency.
It does not need a network connection, cloud account, model, or third-party Python package.

## Test scenarios

SQLite must include FTS5 support.

| Experiment | Verified behavior |
| --- | --- |
| Update source and follow old citation | Old citation resolves original text after a restart |
| Remove source from replacement corpus | Current search omits it; historical generation retains it |
| Build without activating | Current search stays on the prior generation |
| Source failure or KeyboardInterrupt mid-build | Catalog and FTS table creation roll back |
| Subprocess exits during build | Reopened database serves old content and accepts another build |
| Reader during paused writer | Reader returns committed prior content before writer is released |
| Two publishers share expected active value | Exactly one publishes; the other reports a conflict |
| Add unrelated generation | Pinned ranking and scores stay unchanged |
| Alter cited digest or stored body | Resolution fails with CitationMismatch |
| CLI revision walkthrough | Build, activate, search, resolve, and conflict exit behavior work together |

These checks establish behavior for the tested local runtime; they are not a throughput benchmark,
a power-loss durability test, or proof of equivalent rankings across SQLite releases.

An optional workflow template is stored under `ci/`. It is not an active GitHub Actions workflow.
Validation currently uses local tests; no hosted CI result is claimed.
