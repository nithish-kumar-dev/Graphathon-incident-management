import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail, InvestigationOut } from "../../api/types";
import { fixtures, installMockApi } from "../../test/mockApi";
import type { TabProps } from "../types";
import ReviewTab from "./ReviewTab";

const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;

function renderTab(user: DemoUser, overrides: Partial<TabProps> = {}) {
  const props: TabProps = {
    incident: clone<IncidentDetail>(fixtures.incident_101),
    investigation: null,
    user,
    reloadIncident: () => {},
    ...overrides,
  };
  return render(
    <ApiProvider user={user}>
      <ReviewTab {...props} />
    </ApiProvider>,
  );
}

describe("ReviewTab", () => {
  it("shows the rollback candidate with exact args, policy, owner and evidence", async () => {
    installMockApi();
    renderTab("demo-viewer");
    expect(screen.getByRole("heading", { level: 3, name: /rollback_deployment_simulated/ })).toBeInTheDocument();
    const args = screen.getByLabelText("Exact arguments for rollback_deployment_simulated");
    expect(args.textContent).toContain('"service_id": "nova.svc.payment"');
    expect(JSON.parse(args.textContent ?? "")).toEqual({
      action_type: "rollback_deployment_simulated",
      tenant_id: "nova",
      service_id: "nova.svc.payment",
      deployment_id: "nova.dep.payment.v2_4",
      from_version: "v2.4",
    });
    expect(screen.getByText("approver:payment")).toBeInTheDocument();
    expect(screen.getByText(/Payment rollback policy v2/)).toBeInTheDocument();
    expect(screen.getByText("medium (simulated rollback)")).toBeInTheDocument();
    expect(screen.getByText("nova.rb.payment.rollback")).toBeInTheDocument();
    expect(screen.getByText(/Preview derived from graph evidence/)).toBeInTheDocument();
    expect(screen.getByText("nova.ev.101.deploy")).toBeInTheDocument();
    expect(screen.getAllByText("synthetic://deploys/payment/v2.4").length).toBeGreaterThan(0);
    expect(await screen.findByText("nova.team.payments")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("shows the empty state when there are no explanation paths", () => {
    installMockApi();
    const incident = clone<IncidentDetail>(fixtures.incident_101);
    incident.explanation_paths = [];
    renderTab("payments-lead", { incident });
    expect(screen.getByText("No evidence-backed candidate action — nothing to review")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "APPROVE" })).not.toBeInTheDocument();
  });

  it("shows 'No active policy — escalate' for an escalate path", async () => {
    installMockApi();
    const incident = clone<IncidentDetail>(fixtures.incident_101);
    incident.explanation_paths[0]!.approval_policy = "no_active_policy_escalate";
    incident.explanation_paths[0]!.governing_decisions = [];
    renderTab("payments-lead", { incident });
    expect(screen.getByText("No active policy — escalate")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ESCALATE" })).not.toBeInTheDocument();
    await screen.findByText("nova.team.payments");
  });

  it("lists unconfirmed findings and shows the pending banner while awaiting review", async () => {
    installMockApi();
    const inv = clone<InvestigationOut>(fixtures.investigation_queued);
    inv.status = "awaiting_review";
    inv.findings = [
      { claim_type: "confirmed", statement: "checkout 5xx observed", evidence: [] },
      { claim_type: "hypothesis", statement: "payment pool sizing regressed in v2.4", evidence: [] },
    ];
    renderTab("payments-lead", { investigation: inv });
    expect(screen.getByText("Pending your approval").closest("[role='status']")).toHaveTextContent(/awaiting human review/);
    expect(screen.getByText("payment pool sizing regressed in v2.4")).toBeInTheDocument();
    expect(screen.queryByText("checkout 5xx observed")).not.toBeInTheDocument();
    expect(screen.getByText("Hypothesis · not confirmed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "APPROVE" })).not.toBeInTheDocument();
    await screen.findByText("nova.team.payments");
  });

  it("awaiting_review with a real proposal: exact spec, full hash, Pending banner, no decision buttons (decisions live in Human Review)", async () => {
    const api = installMockApi();
    const inv = clone<InvestigationOut>(fixtures.investigation_awaiting_review_101);
    const proposal = inv.proposed_actions![0]!;
    renderTab("payments-lead", { investigation: inv });

    expect(screen.getByText("Pending your approval").closest("[role='status']")).toHaveTextContent(inv.id);
    // The real proposal replaces the path-derived preview.
    expect(screen.getByRole("heading", { level: 3, name: /Proposal: rollback_deployment_simulated/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Exact arguments for rollback_deployment_simulated")).not.toBeInTheDocument();
    expect(screen.queryByText(/Preview derived from graph evidence/)).not.toBeInTheDocument();

    const proposals = screen.getByRole("list", { name: "Proposals" });
    expect(within(proposals).getByText(proposal.id)).toBeInTheDocument();
    expect(within(proposals).getByText(proposal.proposal_id)).toBeInTheDocument();
    expect(within(proposals).getAllByTitle("Proposal status: pending_review").length).toBeGreaterThan(0);
    expect(within(proposals).getByText("simulation")).toBeInTheDocument();

    const spec = screen.getByLabelText("Exact spec for rollback_deployment_simulated");
    expect(JSON.parse(spec.textContent ?? "")).toEqual({
      action_type: "rollback_deployment_simulated",
      tenant_id: "nova",
      env: "prod",
      service_id: "nova.svc.payment",
      deployment_id: "nova.dep.payment.v2_4",
      runbook_id: "nova.rb.payment.rollback",
    });
    expect(screen.getByLabelText("Spec hash").textContent).toBe(proposal.spec_hash);
    expect(proposal.spec_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(within(proposals).getByText(proposal.evidence[0]!.id)).toBeInTheDocument();
    expect(screen.getByText("Payment service deployment rollback")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "APPROVE" })).not.toBeInTheDocument();
    expect(await screen.findByText("nova.team.payments")).toBeInTheDocument();
    expect(api.requests.filter((r) => r.path.startsWith("/api/actions"))).toHaveLength(0);
  });

});
