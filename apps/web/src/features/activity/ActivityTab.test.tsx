import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail, InvestigationOut, RetrievalBundle } from "../../api/types";
import { errorEnvelope, fixtures, installMockApi } from "../../test/mockApi";
import type { TabProps } from "../types";
import ActivityTab from "./ActivityTab";

const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;

function renderTab(overrides: Partial<TabProps> = {}) {
  const user: DemoUser = overrides.user ?? "demo-viewer";
  const props: TabProps = {
    incident: clone<IncidentDetail>(fixtures.incident_101),
    investigation: null,
    user,
    reloadIncident: () => {},
    ...overrides,
  };
  return render(
    <ApiProvider user={user}>
      <ActivityTab {...props} />
    </ApiProvider>,
  );
}

function branchItem(name: string): HTMLElement {
  const list = screen.getByRole("list", { name: "Branch states" });
  const code = within(list).getByText(name);
  return code.closest("li") as HTMLElement;
}

async function stepRow(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: "Retrieval steps" });
  return within(table).getByRole("rowheader", { name }).closest("tr") as HTMLElement;
}

describe("ActivityTab", () => {
  it("shows an empty state with no investigation", async () => {
    installMockApi();
    renderTab();
    expect(screen.getByText("No investigation started")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Retrieval steps" })).toBeInTheDocument();
  });

  it("queued investigation: three pending branches and the queued explanation", async () => {
    installMockApi();
    renderTab({ investigation: clone<InvestigationOut>(fixtures.investigation_queued) });
    expect(screen.getByText("inv-01example")).toBeInTheDocument();
    expect(screen.getByText("demo-responder")).toBeInTheDocument();
    for (const name of ["graph_context", "memory_context", "telemetry_context"]) {
      expect(within(branchItem(name)).getByText("pending")).toBeInTheDocument();
    }
    expect(screen.getByText(/orchestrator \(Phase 4\) has not picked this investigation up/)).toBeInTheDocument();
    await screen.findByRole("table", { name: "Retrieval steps" });
  });

  it("shows failed and skipped branches visibly with their details", async () => {
    installMockApi();
    const inv = clone<InvestigationOut>(fixtures.investigation_queued);
    inv.status = "running";
    inv.branches = {
      graph_context: { status: "completed", detail: null },
      memory_context: { status: "failed", detail: "graph timeout" },
      telemetry_context: { status: "skipped", detail: "telemetry source disabled" },
    };
    inv.integrity_warnings = ["finding without evidence"];
    renderTab({ investigation: inv });

    const memory = branchItem("memory_context");
    expect(within(memory).getByText("failed")).toBeInTheDocument();
    expect(within(memory).getByText("✕ Branch failed")).toBeInTheDocument();
    expect(within(memory).getByText("graph timeout")).toBeInTheDocument();

    const telemetry = branchItem("telemetry_context");
    expect(within(telemetry).getByText("skipped")).toBeInTheDocument();
    expect(within(telemetry).getByText("⤼ Branch skipped")).toBeInTheDocument();
    expect(within(telemetry).getByText("telemetry source disabled")).toBeInTheDocument();

    expect(within(branchItem("graph_context")).getByText("completed")).toBeInTheDocument();
    expect(screen.queryByText(/has not picked this investigation up/)).not.toBeInTheDocument();
    expect(screen.getByText("finding without evidence")).toBeInTheDocument();
    await screen.findByRole("table", { name: "Retrieval steps" });
  });

  it("shows retrieval steps from retrieval_101, all completed, with extracted terms and model", async () => {
    installMockApi();
    renderTab();
    for (const [name, candidates] of [
      ["graph", "5"],
      ["keyword", "5"],
      ["vector", "6"],
    ] as const) {
      const row = await stepRow(name);
      expect(within(row).getByText("completed")).toBeInTheDocument();
      expect(within(row).getByText(candidates)).toBeInTheDocument();
    }
    expect(screen.queryByText(/Fallback:/)).not.toBeInTheDocument();
    expect(screen.getByText("nomic-embed-text")).toBeInTheDocument();
    const terms = screen.getByRole("list", { name: "Extracted error terms" });
    expect(within(terms).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "5xx",
      "latency",
      "p99",
      "pool",
      "timeouts",
    ]);
    expect(screen.getAllByText("nova.svc.checkout").length).toBeGreaterThan(0);
  });

  it("shows the fallback detail when the vector step failed", async () => {
    const api = installMockApi();
    const bundle = clone<RetrievalBundle>(fixtures.retrieval_101);
    bundle.steps.vector = { status: "failed", detail: "EmbeddingUnavailable; graph + keyword only", candidates: 0 };
    bundle.embedding_model = null;
    api.on("GET", "/api/incidents/nova.inc.101/retrieval", { body: bundle });
    renderTab();
    const row = await stepRow("vector");
    expect(within(row).getByText("failed")).toBeInTheDocument();
    expect(within(row).getByText("EmbeddingUnavailable; graph + keyword only")).toBeInTheDocument();
    expect(within(row).getByText(/Fallback: graph \+ keyword only/)).toBeInTheDocument();
    expect(within(await stepRow("graph")).getByText("completed")).toBeInTheDocument();
  });

  it("lists the timeline in order with ref_ids", async () => {
    installMockApi();
    renderTab();
    const list = await screen.findByRole("list", { name: "Timeline events" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("2026-10-17 14:04:00 UTC");
    expect(items[0]).toHaveTextContent("alert_fired");
    expect(items[0]).toHaveTextContent("nova.alr.101.checkout_5xx");
    expect(items[1]).toHaveTextContent("status_change");
    expect(items[1]).toHaveTextContent("storefront-oncall");
    expect(items[1]).not.toHaveTextContent("ref:");
    expect(items[2]).toHaveTextContent("2026-10-17 14:06:00 UTC");
    expect(items[2]).toHaveTextContent("nova.alr.101.payment_latency");
  });

  it("shows an ErrorBanner on a retrieval 503 and refetches on retry", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents/nova.inc.101/retrieval", [
      { status: 503, body: errorEnvelope("dependency_unavailable", "graph down", "req-503-xyz") },
      { body: fixtures.retrieval_101 },
    ]);
    const user = userEvent.setup();
    renderTab();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("dependency_unavailable");
    expect(alert).toHaveTextContent("req-503-xyz");
    expect(api.requestsTo("GET", "/api/incidents/nova.inc.101/retrieval")).toHaveLength(1);

    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("table", { name: "Retrieval steps" })).toBeInTheDocument();
    expect(api.requestsTo("GET", "/api/incidents/nova.inc.101/retrieval")).toHaveLength(2);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows the investigator, gate decision, violations and revision count of a Phase 4 run", async () => {
    installMockApi();
    renderTab({ investigation: clone<InvestigationOut>(fixtures.investigation_escalated_101) });
    expect(screen.getByTitle("Investigator: ollama:qwen2.5:7b")).toBeInTheDocument();
    expect(screen.getByText("gate: escalate")).toBeInTheDocument();
    const violations = screen.getByRole("list", { name: "Gate violations (activity)" });
    expect(violations).toHaveTextContent("action_not_allowed");
    expect(violations).toHaveTextContent("run_shell is not an allowed action type");
    expect(screen.getByText("Revisions").nextElementSibling).toHaveTextContent("2");
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
    await screen.findByRole("table", { name: "Retrieval steps" });
  });

  it("shows the error of a failed run and flags a fallback investigator", async () => {
    installMockApi();
    const inv = clone<InvestigationOut>(fixtures.investigation_failed_101);
    inv.investigator = "stub-fallback(ollama timeout)";
    renderTab({ investigation: inv });
    expect(screen.getByText("Error").nextElementSibling).toHaveTextContent("investigator unavailable after 3 attempts");
    expect(screen.getByText("stub-fallback(ollama timeout)")).toHaveAttribute("title", expect.stringMatching(/^Fallback/));
    expect(screen.getByText("Gate decision").nextElementSibling).toHaveTextContent("not recorded");
    await screen.findByRole("table", { name: "Retrieval steps" });
  });
});
