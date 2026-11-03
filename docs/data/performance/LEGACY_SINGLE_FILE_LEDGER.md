# Legacy Single-File Ledger

`ledger.json` in this directory is the last single-file Performance v1 ledger. It is a
historical artifact and is no longer written.

| Item | Value |
| --- | --- |
| Last written | scheduled run 41655022098 on 2026-11-03 |
| Published in | commit `ccc9f44a66f5d1bbe041e811c02ac12ee7a933bf` |
| `ledger.json` | 41,835,658 bytes, SHA-256 `11d9aab89e90ccffc68193cde135da82eafff94d2611eae1c97a19667c0ca5de` |
| Content | 1,399 picks (report dates 2026-05-11 to 2026-11-03) and 121 market snapshots |

From the next scheduled run on, the ledger is kept in `ledger/` as an index, one file
per report date of picks and one file per market-snapshot date. That run reads this
file once to seed `ledger/`. `ledger/index.json` records the file's SHA-256 in
`ledger_storage.legacy_seed_sha256`, and later runs refuse to start if the file
changes. `investmentagent.performance.load_ledger` reads either layout.

All 128 published versions of this file, 2026-05-11 to 2026-11-03, were replayed
through the partitioned layout. Each one reconstructs byte for byte and renders the
same scorecard. The four May versions that predate market snapshots are compared
after the loader adds their empty `market_snapshots`.
