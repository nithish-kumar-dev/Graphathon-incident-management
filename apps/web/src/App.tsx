import { useCallback, useState } from "react";
import type { StageSummary } from "./features/investigation/model";
import { ApiProvider, type ApiClient } from "./api/client";
import type { DemoUser } from "./api/types";
import { DEFAULT_DEMO_USER, isDemoUser } from "./auth/permissions";
import { EmptyState } from "./components/ui";
import { DemoUserSelect } from "./layout/DemoUserSelect";
import { IncidentList } from "./layout/IncidentList";
import { IncidentWorkspace } from "./layout/IncidentWorkspace";
import { ReadinessDot } from "./layout/ReadinessDot";
import { SyntheticDataBanner } from "./layout/SyntheticDataBanner";
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
  const [summaries, setSummaries] = useState<Record<string, StageSummary>>({});
  const onSummaryChange = useCallback((id: string, s: StageSummary) => setSummaries((prev) => ({ ...prev, [id]: s })), []);

  const setUser = useCallback((u: DemoUser) => {
    writeStorage(STORAGE_KEYS.demoUser, u);
    setUserState(u);
  }, []);

  return (
    <ApiProvider user={user} client={client}>
      <div className="min-h-screen bg-[#F3F6FA] text-slate-900">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <header className="bg-[#101E35] text-white">
          <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-lg font-semibold">Graphathon Incident Investigator</h1>
              <ReadinessDot />
            </div>
            <DemoUserSelect value={user} onChange={setUser} />
          </div>
        </header>
        <SyntheticDataBanner />

        <main
          id="main"
          className="mx-auto grid max-w-screen-2xl grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)]"
        >
          <aside className="min-w-0">
            <IncidentList
              selectedId={route.incidentId}
              liveSummaries={summaries}
              onSelect={(incidentId) => navigate({ incidentId })}
            />
          </aside>
          <section aria-label="Incident workspace" className="min-w-0 rounded-lg bg-white p-4 shadow-sm">
            {route.incidentId ? (
              <IncidentWorkspace
                key={route.incidentId}
                incidentId={route.incidentId}
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
        </main>
      </div>
    </ApiProvider>
  );
}
