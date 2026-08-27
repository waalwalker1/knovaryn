# Benchmark results — knovaryn 0.2.1

Produced on 2026-08-25T15:01:14+00:00 by `benchmarks/run_report.py`
(methodology v2: `docs/reference/benchmark-methodology.md`) on commit
`2bad356e5e0736fd658611893767119806a951cc`.

- `environment.json` — machine/software record
- `run-1..3.json` — per-repetition metrics (deterministic inputs;
  only timing/memory vary between repetitions)
- `aggregate.json` — medians, release-digest equality verdict, explicit
  *not measured* items
- `checksums.txt` — SHA-256 of every file above

Offline deterministic framework benchmark. Not live-model generation
throughput. Reproduce with:

```bash
uv run python benchmarks/run_report.py --version 0.2.1 --runs 3
```

then compare `release_bundle_sha256_values` (must be length 1) and spot-check
counts against the committed files.
