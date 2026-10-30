# VardrMap frontend

Next.js 16 App Router and TypeScript frontend, used in the local Compose
distribution and hosted on Vercel.

## Setup

Run `npm install`, copy `.env.example` to `.env.local`, and run `npm run dev`.
See [development setup](../docs/development.md) for backend configuration and tests.
Set `VARDRMAP_AUTH_METHODS` consistently on frontend and backend: `github` (default),
`local`, or `github,local`. `AUTH_SECRET`, `BACKEND_JWT_SECRET` and
`NEXT_PUBLIC_API_URL` remain required; `AUTH_GITHUB_ID` and `AUTH_GITHUB_SECRET`
are required only when GitHub is enabled. `AUTH_URL` is optional.

Local-account login requires trusted HTTPS for both UI and API and explicit backend
allowed origins; `npm run dev` alone does not establish that. Follow the
[local authentication guide](../docs/local-authentication.md) or the distribution
[installation guide](https://github.com/VardrSec/VardrSec/blob/main/docs/installation.md).
Initial account creation and recovery are terminal operations, not public signup.

## Request and state flow

`auth.ts` configures Auth.js v5 and, when GitHub is enabled, mints short-lived
backend JWTs in its callbacks. Local login uses the backend session endpoints
and a secure HTTP-only cookie; cookie-authenticated writes include Origin and
`X-CSRF-Token`. Both paths retain existing backend authorization checks.
`app/api/auth/[...nextauth]/route.ts` exposes its handlers. `proxy.ts` applies
Auth.js middleware; it does not proxy backend API requests.
`app/context/AppContext.tsx` provides `authFetch`, which sends authenticated
requests directly to `NEXT_PUBLIC_API_URL`. Backend CORS must allow the frontend origin.
The API URL is public; signing secrets remain server-side.

`app/page.tsx` selects the engagement and section. `app/context/appReducer.ts`
coordinates global state. `app/types.ts` defines the seven sections:
Dashboard, Scope, Overview, Review, Findings, Reports and Settings.
Dashboard and Review are tab containers. Their children provide the job composer,
imports, reconnaissance, services, scanner review and manual testing.
Findings hold reviewed issues; scanner matches remain candidates until verified.
Reports include finding write-ups and engagement deliverables as separate workflows.
The API case builder reads Map's versioned playbook catalog on demand. Gate jobs show
assessment completeness separately from lifecycle and expose filtered execution
evidence for operator review and finding linkage. These views do not certify coverage.
Settings contains API key, notification and client configuration.

## Verification

Run `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`.
Typecheck is required separately: tests are not all reachable from the build graph,
and Jest transpilation does not replace TypeScript checking.
Tests use the `test-utils/renderWithApp` harness. Inspect its context defaults by
hand when changing AppContext because its cast bypasses excess-property checks.
