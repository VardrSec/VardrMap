# Contributing to VardrMap

Thanks for your interest in VardrMap. A few things to know before you open a pull request.

## License and the Developer Certificate of Origin

VardrMap is licensed under the **GNU Affero General Public License v3.0** (see [`LICENSE`](LICENSE)). Contributions are accepted under that same license.

We use the **Developer Certificate of Origin** ([`DCO.txt`](DCO.txt)) rather than a signed CLA. Every commit must be signed off, certifying that you wrote the change (or otherwise have the right to submit it under the AGPL) and that you agree it may be redistributed under this project's license, including by the maintainer under separate commercial terms.

Sign off with the `-s` flag:

```
git commit -s -m "Your message"
```

This appends a line to your commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must match the commit author. Pull requests whose commits are not signed off cannot be merged.

> **Why sign-off matters here:** VardrMap is offered under the AGPL *and* may be offered by the copyright holder under a separate commercial license. Your sign-off is what keeps that dual-licensing possible — it confirms your contribution can be distributed under both.

## Before you open a PR

See [`CLAUDE.md`](CLAUDE.md) and [`docs/development.md`](docs/development.md) for setup and conventions. In short:

- `main` is protected — branch and open a PR.
- Backend: `cd backend && .\venv\Scripts\pytest.exe tests -v`
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`
- Behavior-changing work needs matching documentation and a `CHANGELOG.md` entry.
