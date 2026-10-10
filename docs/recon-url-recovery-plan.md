# Recovering recon URLs corrupted by the old importer

**Status: Proposed. Nothing in this document has been executed, and no existing row has been
modified.** It exists for review. The fix for *new* imports shipped in v0.43.0; this covers the rows
stored before it.

## What happened

Every recon importer ran URLs through `strip_html` (nh3), a sanitiser for prose. It does not return
what it was given: it HTML-encodes `&`, `<` and `>`, and *deletes* anything tag-shaped. So the URL
`?q=1&page=2` was stored as `?q=1&amp;page=2`. Recon URLs are read back as scan targets, so a runner
then fetched a URL whose second parameter was literally named `amp;page`.

Affected: `recon_items.url`, `.host`, `.path` for `httpx`, `ffuf`, `katana`, `gau`; and
`scan_items.asset` / `.matched_at` for `nuclei`. (dalfox was never affected: it was stored losslessly
from the start.) Anything keyed on those strings is keyed on a value that was never the URL: dedup,
the asset graph, job targets.

## Why existing rows cannot simply be decoded

Measured against the real sanitiser, not assumed:

| original | stored |
|---|---|
| `a&b`, `a&amp;b`, `a&#38;b`, `a&#x26;b`, `a&ampb` | **`a&amp;b`** (five originals, one value) |
| `a>b`, `a&gt;b` | **`a&gt;b`** |
| `a<b` | `a` (everything after a bare `<` is gone) |
| `x<script>y</script>z` | `xz` (tag *and content* deleted) |
| `a&amp;amp;b` | `a&amp;amp;b` (unchanged) |

So a stored `&amp;` is **ambiguous**: decoding to `&` is right for most rows, but archive-sourced URLs
(gau, katana) routinely contain a *literal* `&amp;` scraped from HTML, and those would be silently
changed into a different URL. And some damage is **irrecoverable**: deleted tag content cannot be
detected from the row, let alone restored. A blind decode would corrupt a minority of rows to repair
the majority, with no way to tell which.

## Already true for new imports

URL-valued fields are stored exactly as reported (control characters removed, 8192-char cap; `<` and
`>` percent-encoded so a URL is never stored as markup). An original `a&b` and an original `a&amp;b`
are now distinct rows. Existing rows are never touched by an import.

**Boundary behaviour (pinned by tests).** Dedup is on the exact string, so re-importing a URL whose
legacy row is encoded adds the correct row *beside* the old one. httpx is the exception: it matches by
host and enriches in place, so its rows **repair themselves on the next probe**. For ffuf, katana and
gau the pair persists until reconciled below. Skipping the import instead would silently drop the
correct URL.

## Step 0 — measure first (read-only, available now)

```bash
python backend/audit_recon_urls.py --fixed-since <deploy time>   # add --json for tooling
```

It issues only SELECTs, in the database's read-only mode (a write fails; tested). Per source it
reports how many rows contain an encoded character, how many are **corroborated** (a *different* row
exists in the same engagement and source whose legacy form equals this one, i.e. direct evidence of the
original), how many are **collisions** (two different originals share the value) and how many are
**unpaired** (no evidence at all). `--fixed-since` matters: a row created after the fix that contains
`&amp;` is a genuine literal entity, identical by content to a corrupted one.

**The decision below should be made on these numbers, not before.**

## Options

| | What | Risk |
|---|---|---|
| **R0** | Do nothing. httpx heals itself; the rest ages out as sources are re-run. | Corrupted targets keep being scanned (wrong parameters) until superseded. |
| **R1** | **Evidence-based merge** (recommended). For each corroborated row, repoint its references to the correct row and retire the corrupted one. | Needs the destructive-change sign-off below. Only acts where evidence exists. |
| **R2** | Re-observation. Re-run the original tool; fixed imports create the correct rows, which then qualify for R1. | Costs scan traffic against the target. |
| **R3** | Operator-reviewed decode for *unpaired* rows: export, review per batch, then apply. | Slow; the reviewer decides, so it is a human claim rather than an inference. |
| **R4** | Blind decode of everything. | **Rejected**: silently rewrites literal-entity URLs and cannot be told apart. |

## Recommended sequence

1. Run the audit. If `suspect` is small or mostly corroborated, R1 alone may suffice.
2. **R1 on corroborated rows only.** Dry-run by default, printing every proposed change.
3. Leave *unpaired* rows alone, or offer R3, or re-observe them with R2. Never auto-decode.
4. Re-run the audit; `corroborated` should be 0 and nothing else should have moved.

## Safeguards any repair step must have

- **Dry-run is the default**; applying requires an explicit flag, and prints a before/after summary.
- **A backup first**: copy the affected rows (id, old values, and every referencing id) into a
  dedicated table before changing anything, so every change is reversible.
- **A checkable invariant.** For every repair, `legacy_form(new_value) == old_value` must hold (the
  old sanitiser applied to the proposed original reproduces exactly what was stored). A proposed
  original that fails this is not an original of that row. This is the proof a repair is consistent
  with history, and the step must refuse any that fail it.
- **Per-engagement batches, each in one transaction**, idempotent, and bounded in size.
- **No deletion without explicit sign-off.** Retiring a corrupted row is destructive; per this
  repository's rules that needs a yes before it is written, with the data loss stated. The backup is
  what makes that sign-off reasonable. A non-destructive variant (flag the row as superseded, exclude
  it from target resolution) needs a column and is the alternative if deletion is refused.
- **Repoint, don't orphan**: `job_result_links` (CASCADE on delete) and `asset_id` references move to
  the surviving row first, otherwise provenance would silently vanish with the deleted row.

## Open questions for review

1. After running the audit, is R1 enough, or do the unpaired numbers justify R3?
2. Retire corrupted rows by **deletion** (simplest, needs sign-off) or by a **superseded flag**
   (non-destructive, needs a column and a filter in target resolution)?
3. Should job-target resolution *exclude* suspect legacy rows in the meantime? It stops wrong scans
   today, but changes what existing jobs target.
4. What `--fixed-since` is the real deploy time? Without it every marked row counts as suspect.

## Not covered — but a larger, related problem

The same encoding hits **every field that goes through `strip_html`**, not only URLs: confirmed against
the sanitiser, `Terms & Conditions` is stored as `Terms &amp; Conditions` and a finding titled
`IDOR on /orders?a=1&b=2` as `...a=1&amp;b=2` (14 call sites in `schemas.py` alone). The frontend has no
entity decoder, so users see the literal `&amp;`. That is display corruption rather than data a tool reads
back, so it is out of scope for this plan and was not changed, but it is wider than recon and worth its
own decision: store text losslessly and escape on output (the frontend already does), or keep
sanitising on input and decode on output.