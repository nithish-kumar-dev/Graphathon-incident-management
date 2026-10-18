import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail } from "../../api/types";
import { errorEnvelope, fixtures, installMockApi } from "../../test/mockApi";
import type { TabProps } from "../types";
import EvidenceTab from "./EvidenceTab";

const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
const incident101 = () => clone<IncidentDetail>(fixtures.incident_101);
const incident092 = () => clone<IncidentDetail>(fixtures.incident_092);
const CONTEXT_PATH = "/api/services/nova.svc.payment/context";

function tab(incident: IncidentDetail, user: DemoUser = "demo-viewer") {
  const props: TabProps = { incident, investigation: null, user, reloadIncident: () => {} };
  return (
    <ApiProvider user={user}>
      <EvidenceTab key={incident.id} {...props} />
    </ApiProvider>
  );
}

const hopTexts = () => screen.getAllByTestId("hop").map((li) => li.textContent);

describe("EvidenceTab", () => {
  it("renders the 5 golden-path hops in stored order with real ids and relationship names", async () => {
    installMockApi();
    render(tab(incident101()));
    const hops = within(screen.getByRole("list", { name: "Hops of path 1" })).getAllByRole("listitem");
    expect(hops).toHaveLength(5);
    expect(hopTexts()).toEqual([
      "Incidentnova.inc.101—AFFECTS→Servicenova.svc.checkout",
      "Servicenova.svc.checkout—DEPENDS_ON→Servicenova.svc.payment",
      "Deploymentnova.dep.payment.v2_4—DEPLOYED_TO→Servicenova.svc.payment",
      "Incidentnova.inc.101—HAS_EVIDENCE→Evidencenova.ev.101.deploy",
      "Evidencenova.ev.101.deploy—REFERS_TO→Deploymentnova.dep.payment.v2_4",
    ]);
    // ids are monospace code, labels are plain text tags
    const first = hops[0]!;
    expect(within(first).getByText("nova.inc.101").tagName).toBe("CODE");
    expect(within(first).getByText("Incident").tagName).toBe("SPAN");

    const paths = screen.getByRole("list", { name: "Explanation paths" });
    expect(within(paths).getByText("Hypothesis — correlated, not confirmed")).toHaveAttribute(
      "title",
      "A graph correlation. Evidence for a hypothesis, not a confirmed cause.",
    );
    // A single label: no second "Correlated · not confirmed" badge next to it.
    expect(within(paths).queryByText("Correlated · not confirmed")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/confirmed cause/i);

    // Decision and runbook with their relationship context and documents.
    const decisions = within(paths).getByRole("list", { name: "Governing decisions of path 1" });
    expect(decisions).toHaveTextContent("Decisionnova.dec.payment.rollback_v2—GOVERNS→Servicenova.svc.payment");
    expect(decisions).toHaveTextContent("Payment rollback policy v2");
    expect(within(decisions).getByText("approver:payment")).toBeInTheDocument();
    expect(within(decisions).getByText("synthetic://wiki/adr/031")).toBeInTheDocument();
    expect(decisions).toHaveTextContent("ADR-031 Payment rollbacks require payments lead approval");
    const runbooks = within(paths).getByRole("list", { name: "Runbooks of path 1" });
    expect(runbooks).toHaveTextContent("Runbooknova.rb.payment.rollback—APPLIES_TO→Servicenova.svc.payment");
    expect(within(runbooks).getByText("rollback_deployment_simulated")).toBeInTheDocument();

    await screen.findByRole("list", { name: "Owners of nova.svc.payment" });
  });

  it("marks evidence rows used by a path", async () => {
    installMockApi();
    render(tab(incident101()));
    const table = screen.getByRole("table", { name: /Incident evidence/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    const deployRow = rows.find((r) => r.textContent?.includes("nova.ev.101.deploy"))!;
    expect(within(deployRow).getByText("used in path")).toBeInTheDocument();
    expect(within(deployRow).getByText("synthetic://deploys/payment/v2.4")).toBeInTheDocument();
    expect(within(deployRow).getByText("nova.svc.payment")).toBeInTheDocument();
    expect(within(deployRow).getByText("nova.dep.payment.v2_4")).toBeInTheDocument();
    expect(within(table).getAllByText("used in path")).toHaveLength(1);
    await screen.findByRole("list", { name: "Owners of nova.svc.payment" });
  });

  it("fetches the target service context at depth 2 and shows owners, decisions and dependency paths", async () => {
    const api = installMockApi();
    render(tab(incident101(), "demo-responder"));
    const owners = await screen.findByRole("list", { name: "Owners of nova.svc.payment" });
    expect(within(owners).getByText("nova.team.payments")).toBeInTheDocument();
    expect(within(owners).getByText("payments-lead")).toBeInTheDocument();
    expect(within(owners).getByText("payments-oncall")).toBeInTheDocument();

    const reqs = api.requestsTo("GET", CONTEXT_PATH);
    expect(reqs).toHaveLength(1);
    expect(reqs[0]?.query.get("depth")).toBe("2");
    expect(reqs[0]?.user).toBe("demo-responder");

    const decisions = screen.getByRole("list", { name: "Active decisions for nova.svc.payment" });
    expect(within(decisions).getByText("nova.dec.payment.rollback_v2")).toBeInTheDocument();
    expect(within(decisions).getByText("nova.dec.payment.rollback_v1")).toBeInTheDocument();

    expect(screen.getByRole("list", { name: "Dependencies of nova.svc.payment" })).toHaveTextContent(
      "nova.svc.payment—DEPENDS_ON→nova.svc.auth",
    );
    expect(screen.getByRole("list", { name: "Dependents of nova.svc.payment" })).toHaveTextContent(
      "nova.svc.checkout—DEPENDS_ON→nova.svc.payment",
    );
    expect(screen.getByRole("list", { name: "Recent deployments of nova.svc.payment" })).toHaveTextContent(
      "nova.dep.payment.v2_4",
    );
  });

  it("shows an ErrorBanner when the service context returns 503, and Retry re-requests", async () => {
    const api = installMockApi();
    api.on("GET", CONTEXT_PATH, [
      { status: 503, body: errorEnvelope("dependency_unavailable", "graph down", "req-503-ctx") },
      { body: fixtures.service_payment },
    ]);
    const user = userEvent.setup();
    render(tab(incident101()));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("dependency_unavailable");
    expect(alert).toHaveTextContent("req-503-ctx");
    // The rest of the tab still renders.
    expect(screen.getAllByTestId("hop")).toHaveLength(5);

    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("list", { name: "Owners of nova.svc.payment" })).toBeInTheDocument();
    expect(api.requestsTo("GET", CONTEXT_PATH)).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("only shows ids and refs that exist in the API data", async () => {
    installMockApi();
    render(tab(incident101()));
    await screen.findByRole("list", { name: "Owners of nova.svc.payment" });
    const known = JSON.stringify([fixtures.incident_101, fixtures.service_payment]);
    const shown = [...document.querySelectorAll("code")].map((c) => c.textContent ?? "");
    expect(shown.length).toBeGreaterThan(20);
    for (const text of shown) expect(known, `rendered id ${text}`).toContain(JSON.stringify(text));
    // Relationship names come from the hops (or the graph schema for GOVERNS / DOCUMENTED_IN / APPLIES_TO).
    for (const rel of ["AFFECTS", "DEPENDS_ON", "DEPLOYED_TO", "HAS_EVIDENCE", "REFERS_TO"]) {
      expect(known).toContain(`"${rel}"`);
    }
  });

  it("lists every source reference once, with the ids it belongs to", async () => {
    installMockApi();
    render(tab(incident101()));
    await screen.findByRole("list", { name: "Owners of nova.svc.payment" });
    const table = screen.getByRole("table", { name: /Deduplicated source references/ });
    const refs = within(table)
      .getAllByRole("rowheader")
      .map((h) => h.textContent);
    expect(refs).toEqual([
      "synthetic://deploys/payment/v2.4",
      "synthetic://wiki/adr/031",
      "synthetic://runbooks/payment-rollback",
      "synthetic://metrics/checkout/http_5xx?t=2026-10-17T14:04Z",
      "synthetic://metrics/payment/p99?t=2026-10-17T14:06Z",
    ]);
    const deployRow = within(table).getByRole("rowheader", { name: "synthetic://deploys/payment/v2.4" }).closest("tr")!;
    expect(within(deployRow).getByText("nova.dep.payment.v2_4")).toBeInTheDocument();
    expect(within(deployRow).getByText("nova.ev.101.deploy")).toBeInTheDocument();
  });

  it("shows empty states and falls back to the first affected service without paths", async () => {
    const api = installMockApi();
    api.on("GET", "/api/services/nova.svc.checkout/context", {
      body: { ...fixtures.service_payment, service: { id: "nova.svc.checkout", name: "checkout", tier: "tier1" }, owners: [], dependencies: [], dependents: [], active_decisions: [], runbooks: [], recent_deployments: [] },
    });
    const inc = incident101();
    inc.explanation_paths = [];
    inc.evidence = [];
    render(tab(inc));
    expect(screen.getByText("No evidence-backed path found — inconclusive")).toBeInTheDocument();
    expect(screen.getByText("No evidence attached to this incident")).toBeInTheDocument();
    expect(await screen.findByText("No owning team recorded.")).toBeInTheDocument();
    expect(api.requestsTo("GET", "/api/services/nova.svc.checkout/context")).toHaveLength(1);
    expect(api.requestsTo("GET", CONTEXT_PATH)).toHaveLength(0);
    expect(screen.queryByText("used in path")).not.toBeInTheDocument();
  });

  it("drops INC-101 data when rerendered with INC-092", async () => {
    installMockApi();
    const { rerender } = render(tab(incident101()));
    await screen.findByRole("list", { name: "Owners of nova.svc.payment" });
    rerender(tab(incident092()));
    await screen.findByRole("list", { name: "Owners of nova.svc.payment" });

    expect(hopTexts()[0]).toBe("Incidentnova.inc.092—AFFECTS→Servicenova.svc.checkout");
    expect(screen.getAllByText("nova.dep.payment.v2_3").length).toBeGreaterThan(0);
    const text = document.body.textContent ?? "";
    for (const id of [
      "nova.inc.101",
      "nova.ev.101.deploy",
      "nova.ev.101.checkout_errors",
      "nova.ev.101.payment_latency",
      "synthetic://metrics/payment/p99?t=2026-10-17T14:06Z",
    ]) {
      expect(text).not.toContain(id);
    }
    // v2.4 legitimately remains as a recent deployment of the payment service, but not in the paths or evidence.
    expect(within(screen.getByRole("list", { name: "Explanation paths" })).queryByText("nova.dep.payment.v2_4")).toBeNull();
    expect(within(screen.getByRole("table", { name: /Incident evidence/ })).queryByText("nova.dep.payment.v2_4")).toBeNull();
  });
});
