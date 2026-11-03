# NM-2 secret-scan false-positive disposition

Independent review classified the historical gitleaks finding in
`docs/development.md` at commit `275b37e2ed237f7dfa7aa0ae54bce8868f8058c0`
as ordinary prose describing authentication and result/stop/observation flows.
It contains no credential assignment or authentication material.

`.gitleaksignore` adds only that exact commit/path/rule/line fingerprint while
preserving every existing entry. Existing scanner configuration and its inherited
test-fixture exclusions are unchanged; this change adds no path or rule exclusion.
A fresh offline noncredential positive control remains detectable. Raw finding
values are not included in published or staged evidence.

This is a false-positive disposition, not a security-risk waiver or proof of
universal secret absence. Hosted CI, deployed-schema comparison and independent
release approval remain open.
