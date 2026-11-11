# Changelog

## Unreleased

- Backport the maintained util-linux mount/descriptor security fixes and their
  header/flag follow-ups, retaining the Trixie ABI and corresponding source.

- Backport the upstream infocmp analysis bound to the existing Trixie ncurses
  source; retain original/modified source without replacing runtime libraries.

- Rebuild the fixed SQLite runtime in both local images using Trixie build
  packages, retaining original/modified source and package copyright material.


## Prepared source versions

- [v0.44.0 — managed authorization and reconciled user guidance](changelog/v0.44.0.md)
  (prepared source version; not a published release).

## Previous releases

Versioned release histories are retained in [changelog/](changelog/).
Historical version headings do not by themselves confirm published tags or artifacts.
