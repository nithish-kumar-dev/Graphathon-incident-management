import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail, InvestigationOut } from "../../api/types";
import { fixtures, installMockApi } from "../../test/mockApi";
import type { TabProps } from "../types";
import ReviewTab from "./ReviewTab";

const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
const DECISIONS = ["APPROVE", "REJECT", "REQUEST_REVISION", "ESCALATE"];
const PHASE5 = "Review API not available until Phase 5 (human-in-the-loop)";

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

function reasonsFor(button: HTMLElement): string[] {
  const id = button.getAttribute("aria-describedby");
  expect(id).toBeTruthy();
  const list = document.getElementById(id!);
  expect(list).not.toBeNull();
  return within(list!).getAllByRole("listitem").map((li) => li.textContent ?? "");
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
    expect(screen.getByText(/SHA-256 spec hash and expiry are created server-side in Phase 5/)).toBeInTheDocument();
    expect(screen.getByText("nova.ev.101.deploy")).toBeInTheDocument();
    expect(screen.getAllByText("synthetic://deploys/payment/v2.4").length).toBeGreaterThan(0);
    expect(await screen.findByText("nova.team.payments")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it.each(["demo-viewer", "demo-responder", "payments-lead"] as const)(
    "keeps all four decision buttons disabled for %s",
    async (user) => {
      installMockApi();
      renderTab(user);
      for (const name of DECISIONS) {
        const button = screen.getByRole("button", { name });
        expect(button).toBeDisabled();
        expect(button).toHaveAttribute("aria-disabled", "true");
        expect(reasonsFor(button)).toContain(PHASE5);
      }
      await screen.findByText("nova.team.payments");
    },
  );

  it("demo-viewer and demo-responder are told they lack action:review", async () => {
    installMockApi();
    const { unmount } = renderTab("demo-viewer");
    expect(reasonsFor(screen.getByRole("button", { name: "APPROVE" }))).toEqual([
      "You are signed in as demo-viewer, who lacks action:review.",
      PHASE5,
    ]);
    await screen.findByText("nova.team.payments");
    unmount();

    renderTab("demo-responder");
    expect(reasonsFor(screen.getByRole("button", { name: "REJECT" }))).toEqual([
      "You are signed in as demo-responder, who lacks action:review.",
      PHASE5,
    ]);
    expect(screen.queryByText(/satisfied/)).not.toBeInTheDocument();
    await screen.findByText("nova.team.payments");
  });

  it("payments-lead has action:review and the role; only the Phase 5 reason remains", async () => {
    installMockApi();
    renderTab("payments-lead");
    const reasons = reasonsFor(screen.getByRole("button", { name: "APPROVE" }));
    expect(reasons).toEqual([PHASE5]);
    expect(reasons.join(" ")).not.toMatch(/lacks action:review/);
    expect(reasons.join(" ")).not.toMatch(/Requires approver:payment/);
    expect(screen.getByText(/Role approver:payment satisfied for payments-lead/)).toBeInTheDocument();
    await screen.findByText("nova.team.payments");
  });

  it("a reviewer without the required approver role is told which role is required", async () => {
    installMockApi();
    const incident = clone<IncidentDetail>(fixtures.incident_101);
    incident.explanation_paths[0]!.governing_decisions[0]!.required_approver_role = "approver:ledger";
    renderTab("payments-lead", { incident });
    expect(reasonsFor(screen.getByRole("button", { name: "APPROVE" }))).toEqual(["Requires approver:ledger", PHASE5]);
    expect(screen.queryByText(/satisfied/)).not.toBeInTheDocument();
    await screen.findByText("nova.team.payments");
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
    expect(reasonsFor(screen.getByRole("button", { name: "ESCALATE" }))).toEqual([PHASE5]);
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
    expect(screen.getByRole("button", { name: "APPROVE" })).toBeDisabled();
    await screen.findByText("nova.team.payments");
  });

  it("clicking disabled buttons never calls any /api/actions endpoint", async () => {
    const api = installMockApi();
    const user = userEvent.setup();
    renderTab("payments-lead");
    await screen.findByText("nova.team.payments");
    await user.type(screen.getByLabelText("Comment (optional)"), "looks right");
    for (const name of DECISIONS) await user.click(screen.getByRole("button", { name }));
    expect(api.requestsTo("POST", /^\/api\/actions/)).toHaveLength(0);
    expect(api.requests.filter((r) => r.path.startsWith("/api/actions"))).toHaveLength(0);
    expect(screen.getByLabelText("Comment (optional)")).toHaveAttribute("maxLength", "1000");
  });

  it("awaiting_review with a real proposal: exact spec, full hash, Pending banner, buttons disabled", async () => {
    const api = installMockApi();
    const inv = clone<InvestigationOut>(fixtures.investigation_awaiting_review_101);
    const proposal = inv.proposed_actions![0]!;
    renderTab("payments-lead", { investigation: inv });

    expect(screen.getByText("Pending your approval").closest("[role='status']")).toHaveTextContent(inv.id);
    // The real proposal replaces the path-derived preview.
    expect(screen.getByRole("heading", { level: 3, name: /Proposal: rollback_deployment_simulated/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Exact arguments for rollback_deployment_simulated")).not.toBeInTheDocument();
    expect(screen.queryByText(/SHA-256 spec hash and expiry are created server-side/)).not.toBeInTheDocument();

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
    expect(within(proposals).getByText("nova.ev.tel.96886385b4b97b90")).toBeInTheDocument();
    expect(screen.getByText("Payment service deployment rollback")).toBeInTheDocument();
    expect(screen.getByText(/Role approver:payment satisfied for payments-lead/)).toBeInTheDocument();

    for (const name of DECISIONS) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(reasonsFor(button)).toEqual([PHASE5]);
    }
    expect(await screen.findByText("nova.team.payments")).toBeInTheDocument();
    expect(api.requests.filter((r) => r.path.startsWith("/api/actions"))).toHaveLength(0);
  });

  it("a real proposal still tells demo-responder it lacks action:review", async () => {
    installMockApi();
    renderTab("demo-responder", { investigation: clone<InvestigationOut>(fixtures.investigation_completed_101) });
    expect(screen.queryByText("Pending your approval")).not.toBeInTheDocument();
    expect(reasonsFor(screen.getByRole("button", { name: "APPROVE" }))).toEqual([
      "You are signed in as demo-responder, who lacks action:review.",
      PHASE5,
    ]);
    await screen.findByText("nova.team.payments");
  });
});
