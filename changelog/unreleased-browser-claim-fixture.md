# Browser legacy claim fixture

The browser evidence fixture now omits the body on an ordinary legacy job claim.
An empty object is an explicit but invalid execution-control request; strict
validation and managed-job guards are preserved. This changes only the fixture,
not production claim or finish behavior.
