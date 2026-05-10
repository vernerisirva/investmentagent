# Saved Watchlist Reports Design

## Goal

Let users save a generated watchlist to a durable daily report file for later review and comparison.

## Scope

In scope:

- Add `--save PATH` to `investmentagent watchlist`.
- Infer save format from extension:
  - `.json` writes structured JSON.
  - `.md` or `.markdown` writes Markdown.
- Create parent directories when needed.
- Include metadata in saved files: generated timestamp, provider, country filter, limit, First North setting, market-cap filters, sector filter, and source checks.
- Keep existing stdout behavior unchanged.

Out of scope:

- Scheduling or automation.
- Comparing two saved reports.
- Excel/PDF export.
- Changing the existing `--output text|json` console behavior.

## Behavior

Example:

```bash
investmentagent watchlist --provider live --country se,fi --limit 25 --save reports/watchlists/2026-05-10.md
```

The command should print the normal watchlist to stdout and also write the report file.

Unsupported extensions should fail with a clear CLI error:

```text
save path must end in .json, .md, or .markdown
```

## Testing

Tests should cover:

- Saving JSON creates a file with metadata, source checks, and ranked items.
- Saving Markdown creates a readable report with metadata and watchlist content.
- Unsupported save extension fails clearly.
- Existing console output still works.
