import { useCallback, useState } from "react";
import type { StageSummary } from "./features/investigation/model";
import { ApiProvider, type ApiClient } from "./api/client";
import type { DemoUser } from "./api/types";
import { DEFAULT_DEMO_USER, isDemoUser } from "./auth/permissions";
import { EmptyState } from "./components/ui";
import { DemoControlsPanel } from "./layout/DemoControlsPanel";
import { DemoUserSelect } from "./layout/DemoUserSelect";
import { IncidentList } from "./layout/IncidentList";
import { IncidentWorkspace } from "./layout/IncidentWorkspace";
import { ReadinessDot } from "./layout/ReadinessDot";
import { useHashRoute } from "./lib/hashRoute";
import { readStorage, STORAGE_KEYS, writeStorage } from "./lib/storage";

function initialUser(): DemoUser {
  const stored = readStorage(STORAGE_KEYS.demoUser);
  return isDemoUser(stored) ? stored : DEFAULT_DEMO_USER;
}

export interface AppProps {
  /** Inject an API client (tests). Defaults to the real client. */
  client?: ApiClient;
}

export default function App({ client }: AppProps) {
  const [user, setUserState] = useState<DemoUser>(initialUser);
  const [route, navigate] = useHashRoute();
  // Bumped after a demo graph change: the workspace refetches everything instead of showing stale results.
  const [graphEpoch, setGraphEpoch] = useState(0);
  const onGraphChanged = useCallback(() => setGraphEpoch((n) => n + 1), []);
  const [summaries, setSummaries] = useState<Record<string, StageSummary>>({});
  const onSummaryChange = useCallback((id: string, s: StageSummary) => setSummaries((prev) => ({ ...prev, [id]: s })), []);

  const setUser = useCallback((u: DemoUser) => {
    writeStorage(STORAGE_KEYS.demoUser, u);
    setUserState(u);
  }, []);

  return (
    <ApiProvider user={user} client={client}>
      <div className="min-h-screen bg-canvas text-ink">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <header className="bg-shell text-white">
          <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-3">
              <span
                aria-hidden="true"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-brand-deep text-sm font-bold text-white"
              >
                IW
              </span>
              <h1 className="truncate text-lg font-bold">Incident Workbench</h1>
            </div>
            <span aria-hidden="true" className="hidden h-6 w-px bg-shell-line lg:block" />
            <p className="hidden text-[10px] font-bold tracking-[0.1em] text-shell-faint lg:block">
              NOVACOMMERCE &nbsp;/&nbsp; SYNTHETIC WORKSPACE
            </p>
            <div className="ml-auto flex flex-wrap items-center gap-3">
              <ReadinessDot />
            </div>
          </div>
        </header>

        {/* Below the bar, on a light surface: the identity switcher drives every permission in the demo,
            so it needs to be obvious rather than tucked into the dark header. */}
        <div className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 lg:px-6">
            <DemoUserSelect value={user} onChange={setUser} />
          </div>
        </div>

        <main
          id="main"
          className="mx-auto grid max-w-screen-2xl grid-cols-1 gap-5 p-4 lg:grid-cols-[minmax(17rem,19rem)_minmax(0,1fr)] lg:gap-6 lg:p-6"
        >
          <aside className="min-w-0">
            <IncidentList
              selectedId={route.incidentId}
              liveSummaries={summaries}
              onSelect={(incidentId) => navigate({ incidentId })}
            />
          </aside>
          <div className="flex min-w-0 flex-col gap-5">
            <DemoControlsPanel incidentId={route.incidentId} refreshKey={graphEpoch} onChanged={onGraphChanged} />
            <section aria-label="Incident workspace" className="min-w-0">
              {route.incidentId ? (
                <IncidentWorkspace
                  key={route.incidentId}
                  incidentId={route.incidentId}
                  refreshKey={graphEpoch}
                  tab={route.tab}
                  onSummaryChange={onSummaryChange}
                  onTabChange={(tab) => navigate({ incidentId: route.incidentId, tab })}
                />
              ) : (
                <EmptyState title="Select an incident">
                  Pick an incident on the left to watch or start an AI investigation.
                </EmptyState>
              )}
            </section>
          </div>
        </main>
      </div>
    </ApiProvider>
  );
}
