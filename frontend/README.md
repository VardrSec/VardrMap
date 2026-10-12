# VardrMap frontend

Next.js 16 App Router and TypeScript frontend, deployed on Vercel.

## Setup

Run `npm install`, copy `.env.example` to `.env.local`, and run `npm run dev`.
See [development setup](../docs/development.md) for GitHub OAuth, backend configuration and local testing.
Required variables are `AUTH_SECRET`, `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET`,
`BACKEND_JWT_SECRET`, and `NEXT_PUBLIC_API_URL`. `AUTH_URL` is optional.

## Request and state flow

`auth.ts` configures Auth.js v5 and mints short-lived backend JWTs in its callbacks.
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
Settings contains API key, notification and client configuration.

## Verification

Run `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`.
Typecheck is required separately: tests are not all reachable from the build graph,
and Jest transpilation does not replace TypeScript checking.
Tests use the `test-utils/renderWithApp` harness. Inspect its context defaults by
hand when changing AppContext because its cast bypasses excess-property checks.
