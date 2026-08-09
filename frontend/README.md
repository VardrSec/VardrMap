# VardrMap — Frontend

Next.js 16 (App Router, TypeScript) frontend for VardrMap. Deployed on Vercel.

---

## Setup

```bash
npm install
cp .env.example .env.local
# fill in .env.local values — see docs/development.md for descriptions
npm run dev
```

App runs at `http://localhost:3000`.

---

## Environment Variables

See [../docs/development.md](../docs/development.md#environment-variables) for full descriptions. Required values in `.env.local`:

```
AUTH_SECRET
AUTH_GITHUB_ID
AUTH_GITHUB_SECRET
BACKEND_JWT_SECRET
NEXT_PUBLIC_API_URL
```

`AUTH_URL` is optional — Auth.js v5 infers it from the request.

---

## Key Files

| Path | Purpose |
|---|---|
| `app/page.tsx` | Root client component — program list, nav, section routing, auth state |
| `app/types.ts` | Shared TypeScript types for all data shapes |
| `app/components/ui.tsx` | Shared primitives — `Panel`, `Input`, `PrimaryButton`, `DangerButton`, `SectionHeader` |
| `app/components/DashboardSection.tsx` | Per-program summary cards using aggregate stats |
| `app/components/FindingsSection.tsx` | Findings list, create/edit/delete, self-fetches |
| `app/components/ReportsSection.tsx` | Reports list, markdown preview, export, self-fetches |
| `app/components/ManualSection.tsx` | Manual test log, self-fetches |
| `app/components/ScanningSection.tsx` | Scan review, status updates, bulk actions, pagination |
| `app/components/ReconSection.tsx` | Recon browser with client-side search |
| `app/components/ScopeSection.tsx` | In/out scope management |
| `app/components/ImportsSection.tsx` | File upload for ffuf, httpx, nuclei output |
| `app/components/SettingsSection.tsx` | API key management — generate, copy, revoke |
| `proxy.ts` | Next.js middleware — rewrites `/api/backend/*` to `NEXT_PUBLIC_API_URL/*` |
| `app/api/auth/[...nextauth]/route.ts` | Auth.js v5 route handler — GitHub OAuth + JWT minting |

---

## Auth Pattern

The frontend uses Auth.js v5 for the GitHub OAuth session. After login, `app/api/auth/[...nextauth]/route.ts` mints a short-lived HS256 JWT signed with `BACKEND_JWT_SECRET`. This JWT is attached to every backend request by the `authFetch` helper in `page.tsx`.

`proxy.ts` (Next.js middleware) rewrites all requests from `/api/backend/*` to the backend URL. This means the browser never sends requests directly to the Railway backend — CORS and the backend URL are not exposed to the client.

---

## Scripts

```bash
npm run dev       # development server (Turbopack)
npm run build     # production build + TypeScript check
npm run lint      # ESLint
```
