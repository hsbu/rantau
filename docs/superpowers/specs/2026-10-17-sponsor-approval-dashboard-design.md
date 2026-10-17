# B-04 Sponsor Approval Dashboard Design

**Status:** Written spec and inline implementation plan approved on 2026-10-17; implementation is in progress.

## Goal

Give an authenticated sponsor a same-origin browser flow to sign in, review pending payment requests and record an approval or rejection for the exact terms shown. The dashboard reports only that the owner decision was recorded. All payments and provider/university records remain simulated; a recorded approval does not execute a payment or prove tuition was paid.

## Scope

- Add the sponsor page at `/sponsor`, including the existing demo credential sign-in, current-session check, approval inbox, decision confirmation and logout.
- Relay only the existing backend login, session, logout, sponsor approval list and decision routes through fixed Next.js route handlers.
- Display the masked beneficiary and source labels, purpose, source principal, fee, total debit, destination amount/currencies, status and expiry from B-03 `ApprovalView`.
- Submit the displayed `terms_hash` with `APPROVED` or `REJECTED`; do not accept decision terms from chat, query strings or locally stored state.

Out of scope: mandate management, student approval, credential provisioning/reset, payment execution, new financial/backend contracts, migrations, real banking/provider connections and changes to the agent/chat flow.

## Components and data flow

1. `frontend/app/sponsor/page.tsx` provides the route shell; a focused client component owns sign-in, session, inbox, confirmation and logout state. The browser uses same-origin relative URLs, `credentials: "same-origin"` and `cache: "no-store"`.
2. Fixed route handlers under `frontend/app/sponsor/api/` proxy only the five listed operations to the configured `AGENT_API_ORIGIN`. They never accept an arbitrary upstream URL, actor, role, tenant, scope, raw cookie or authorization header from the body.
3. For every mutating browser request, the relay validates that `Origin` matches the request host and rejects `Sec-Fetch-Site: cross-site`. It forwards the original `Origin`, the browser session cookie and only the endpoint's validated body to the fixed backend path. It does not forward browser-supplied identity headers.
4. The login/logout relay preserves only the backend's `Set-Cookie` session header so the host-only, HttpOnly, SameSite=Strict cookie belongs to the frontend host. Subsequent relays forward that cookie to the backend. All relay responses disable caching and redirects.
5. The backend remains authoritative for role, current session, request ownership, exact terms and decision persistence. The browser only renders typed responses and submits the displayed digest; it cannot grant itself authority.

## Interaction and states

- On load, fetch the current session through the relay. A sponsor session loads the approval inbox; a missing or expired session displays sign-in. A non-sponsor session receives no inbox and is asked to sign out before using the sponsor page.
- Render pending requests with clear source/destination amounts and currencies, recipient and itemized costs. Render all non-pending states as read-only history. Do not imply that `APPROVED` means money moved.
- Selecting Approve or Reject opens an explicit confirmation showing the same request summary. Submit the chosen decision and exact `terms_hash` to the fixed decision path for that request's `approval_id`.
- After success, refresh the inbox and state that the decision was recorded. The backend's same-decision retry behavior supports manual recovery, but the browser never retries an uncertain POST automatically.
- On 409, refresh and require a new review of the current terms. On an uncertain network/5xx response, show that the outcome is unconfirmed and offer an inbox refresh before any further decision. On 401, return to sign-in; on 404, show a generic unavailable request; on 429, explain that sign-in is temporarily limited; on 503, preserve the page and show service unavailable.

## Security and privacy

- Keep passwords only in the sign-in form/request; never persist them in storage or logs. Do not expose the HttpOnly session token to JavaScript.
- Validate route IDs against the shared identifier pattern; parse and allowlist login/decision request fields. Treat all relay and backend JSON as untrusted until it passes runtime shape checks.
- Use only the safe B-03 view. Do not display balances, account IDs, full terms, student identity, obligation IDs or beneficiary fingerprints.
- Confirmation must bind to the currently displayed `approval_id` and `terms_hash`. Disable duplicate clicks while a request is in flight and do not create an execution call.
- The backend may return 503 for approval operations until Dev C injects the trusted financial adapter. The UI must explain this as unavailable and must not install mocks or claim a successful decision.

## Dependencies and validation

Uses existing B-01 auth endpoints, B-03 approval routes and generated contract types. The existing `AGENT_API_ORIGIN` is the only backend destination. `AUTH_TRUSTED_ORIGIN` must match the browser frontend origin forwarded by the relay. No schema or API contract change is expected.

After written-spec approval, produce the required focused implementation plan and get approval for the execution method. Local validation can include frontend typecheck, lint, production build if available, diff checks and repository hygiene. No test suite change/run is included unless the requester asks for testing or verification. Production backend/C integration, browser sign-in with seeded credentials, remote CI and external review remain separate evidence requirements.
