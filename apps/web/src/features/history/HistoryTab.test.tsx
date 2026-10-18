import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { IncidentDetail } from "../../api/types";
import { errorEnvelope, fixtures, installMockApi } from "../../test/mockApi";
import { InvestigationSessionProvider } from "../investigation/InvestigationSession";
import HistoryTab from "./HistoryTab";

const incident = fixtures.incident_101 as unknown as IncidentDetail;

function renderTab() {
  return render(
    <ApiProvider user="demo-viewer">
      <InvestigationSessionProvider incident={incident} incidentRefreshing={false} reloadIncident={() => {}}>
        <HistoryTab />
      </InvestigationSessionProvider>
    </ApiProvider>,
  );
}

describe("HistoryTab", () => {
  it("lists every run from the API, newest first", async () => {
    const api = installMockApi();
    renderTab();
    const table = await screen.findByRole("table", { name: "Investigation runs" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("awaiting_review");
    expect(rows[0]).toHaveTextContent("simulation");
    expect(rows[1]).toHaveTextContent("recommendation_only");
    expect(api.requestsTo("GET", "/api/incidents/nova.inc.101/investigations")).toHaveLength(1);
  });

  it("keeps agent execution and incident events as separate records, and switches which is emphasised", async () => {
    installMockApi();
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("table", { name: "Investigation runs" });

    const control = screen.getByRole("group", { name: "Which record set to emphasise" });
    const runTimeline = within(control).getByRole("button", { name: /Run timeline/ });
    const incidentEvents = within(control).getByRole("button", { name: /Incident events/ });
    expect(runTimeline).toHaveAttribute("aria-pressed", "true");
    expect(incidentEvents).toHaveAttribute("aria-pressed", "false");

    const agentList = await screen.findByRole("list", { name: "Agent execution events" });
    const incidentList = screen.getByRole("list", { name: "Incident events" });
    expect(within(agentList).getAllByRole("listitem").length).toBeGreaterThan(0);
    expect(within(incidentList).getAllByRole("listitem").length).toBeGreaterThan(0);
    // The two record sets never share rows.
    expect(within(incidentList).queryByText(/Coordinator/)).not.toBeInTheDocument();

    await user.click(incidentEvents);
    expect(incidentEvents).toHaveAttribute("aria-pressed", "true");
    expect(runTimeline).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("list", { name: "Incident events" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Agent execution events" })).toBeInTheDocument();
  });

  it("shows an empty state when no run exists", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents/nova.inc.101/investigations", { body: { incident_id: "nova.inc.101", items: [] } });
    renderTab();
    expect(await screen.findByText("No investigation has been run for this incident")).toBeInTheDocument();
  });

  it("shows the error and a retry when the list fails", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents/nova.inc.101/investigations", { status: 500, body: errorEnvelope("internal_error", "boom") });
    renderTab();
    expect(await screen.findByText("Could not load investigation runs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
