# Legacy Single-File Analysis

`performance-v2.json` and `performance-v2.md` in this directory are the last
single-file outputs of the schema-4 benchmark analysis. They are historical artifacts
and are no longer updated.

| Item | Value |
| --- | --- |
| Generated and data cutoff | `2026-10-30T06:03:51Z` |
| Published in | commit `db28ebe960df8610347a1ae6e47904ac22aa7189` |
| `performance-v2.json` | 103,656,375 bytes, SHA-256 `a89a7fea02a55d46b1aa698fa1b886af2b52840561af1b745d843a37bd33c198` |

The next scheduled analyses (2026-11-02 and 2026-11-03) would have been 100.76 MiB,
above GitHub's 100 MiB limit, and their publication failed.

The same analysis is now published in `performance-v2/` as an index plus one file per
evaluation run and horizon. `investmentagent.analysis_storage.load_analysis` rebuilds
the single-file dictionary. Regenerating the 2026-10-30 analysis and storing it in the
new layout reconstructs this `performance-v2.json` byte for byte.
