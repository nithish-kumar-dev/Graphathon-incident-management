# Graphathon Incident Investigator (web)

React dashboard for graph-grounded incident investigation over **synthetic** data.
NovaCommerce is a fictional company. The user picker sets the `X-Demo-User` header: it is a demo identity, not authentication.

Stack: Vite 6, React 18, TypeScript (strict), Tailwind CSS v4, Vitest + Testing Library (jsdom). All versions are pinned exactly in `package.json`. There is no router and no state library: tabs live in component state and the URL hash.

## Run

```bash
cd apps/web
npm install
npm run dev        # http://127.0.0.1:5173 (needs the API on http://127.0.0.1:8000)
npm test           # vitest run (no backend needed, uses fixtures)
npm run typecheck  # tsc -b, also type-checks the fixtures against src/api/types.ts
npm run build      # tsc -b && vite build -> dist/
```

The dev server proxies `/api`, `/healthz` and `/readyz` to `http://127.0.0.1:8000`, so the browser only talks to one origin.

## Layout

```
src/
  main.tsx, App.tsx, index.css     shell: header, demo-user select, readiness dot, synthetic banner, two columns
  api/
    types.ts                       TS mirror of the Pydantic models (+ const arrays for every enum)
    client.ts                      createClient, ApiError, ApiProvider / useApi
    types.test.ts                  fixture <-> type check (compile time) and enum values (runtime)
  auth/permissions.ts              can(), rolesFor(), permissionsFor(), usersWith() (UX only; server enforces)
  hooks/
    useAsync.ts                    abortable fetch keyed by deps, drops stale results
    usePolling.ts                  poll until terminal, pauses when the page is hidden
    useIncidentInvestigation.ts    current investigation per incident (state + localStorage)
  components/ui/                   Badge, StatusBadge, SeverityBadge, ClaimTypeBadge, InvestigationStatusBadge,
                                   BranchStatusBadge, InvestigatorBadge, ProposalStatusBadge, GateDecisionBadge,
                                   GateViolationList, Spinner, ErrorBanner, EmptyState, Card, Tabs, CodeBlock, cx,
                                   wrap.tsx (withWordBreaks: <wbr> after . : / _ - so ids never wrap mid-word)
  layout/                          IncidentList, IncidentWorkspace, InvestigateControls, DemoUserSelect, ReadinessDot,
                                   SyntheticDataBanner
  lib/                             hashRoute (#/incidents/<id>/<tab>), storage (localStorage that never throws)
  features/
    types.ts                       TabProps, TAB_IDS, TAB_LABELS
    proposals.ts                   pathForProposal, shortHash, formatConfidence (real Phase 4 proposals)
    overview/OverviewTab.tsx       one folder per tab; each default-exports a component taking TabProps
    evidence/EvidenceTab.tsx
    activity/ActivityTab.tsx
    memory/MemoryTab.tsx
    review/ReviewTab.tsx
  test/
    setup.ts                       jest-dom matchers, cleanup, clears localStorage/hash, unstubs fetch
    mockApi.ts                     fetch mock routed to fixtures
    fixtures/*.json                responses captured from the live API; investigation_{completed,awaiting_review,
                                   escalated,failed}_101.json follow the Phase 4 InvestigationOut contract
public/favicon.svg                 inline SVG favicon (linked from index.html)
```

## Tab contract

```ts
// src/features/types.ts
export interface TabProps {
  incident: IncidentDetail;
  investigation: InvestigationOut | null;   // latest polled value, or null if none started
  user: DemoUser;
  reloadIncident: () => void;               // refetch IncidentDetail
}
```

Tabs, in order: `overview` Overview, `evidence` Graph evidence, `activity` Agent activity, `memory` Memory & company brain, `review` Human review.
The workspace mounts only the selected tab, and remounts everything when the incident changes (`key={incidentId}`).

Inside a tab, fetch extra data with the client from context and key the request by everything it depends on:

```tsx
const { client } = useApi();
const { data, error, loading, reload } = useAsync(
  (signal) => client.getRetrieval(incident.id, signal),
  [client, incident.id, user],
);
```

Show failures with `<ErrorBanner error={error} onRetry={reload} />`, which includes the server `request_id`.
Gate actions with `can(user, "...")` for the UX, and still handle 403 from the server.

## Testing with mockApi

```ts
import { errorEnvelope, fixtures, installMockApi } from "../test/mockApi";

const api = installMockApi();                            // stubs global fetch with fixture routes
api.on("GET", "/api/incidents/nova.inc.101/retrieval", { status: 503, body: errorEnvelope("dependency_unavailable", "down") });
api.on("GET", /^\/api\/investigations\//, [{ body: fixtures.investigation_queued }, { body: fixtures.investigation_092 }]);
api.on("GET", "/api/incidents", { networkError: true });
// ...
expect(api.requestsTo("POST", "/api/investigations")[0]?.user).toBe("demo-responder");
```
