# Nonce-based script CSP: report-only trial

The enforcing page CSP in `frontend/next.config.ts` remains unchanged:
`frame-ancestors 'none'; base-uri 'self'; object-src 'none'`. This PR does not
weaken any of these controls.

On HTML navigation, the existing Auth.js `frontend/proxy.ts` adds a
`Content-Security-Policy-Report-Only` script directive with a fresh 128-bit
random nonce, and forwards the same policy and `x-nonce` header to Next.js.
The root layout reads request headers so HTML is dynamically rendered.
HTML responses are marked private/no-store to prevent nonce reuse.

The new script policy is **report-only**. No scripts are blocked. There is no
central violation collector or third-party reporting endpoint; browser
developer tools can show policy violations. Authentication handlers, RSC
requests, and static assets retain the existing paths and enforcement.

## Verification before considering enforcement

1. Run `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`
   inside `frontend/`.
2. Verify unauthenticated GitHub sign-in, authenticated browser navigation,
   and the local-account Compose workflow. Ensure the existing framing CSP
   remains enforced, and nonce values rotate per document response.
3. Review Chrome and Firefox violation events on real browser sessions in
   development and production builds. Investigate any unnonced framework
   scripts and dynamic imports before enforcement.
4. Measure the operational cost of dynamic HTML rendering on Vercel and in
   the Compose distribution, and verify no shared HTML caching occurs.
5. Enabling enforced `script-src` requires a separate reviewed change.

Passing the Chromium browser tests does not demonstrate that the proposed
enforced policy would be violation-free. Do not equate report-only with
effective enforcement.
