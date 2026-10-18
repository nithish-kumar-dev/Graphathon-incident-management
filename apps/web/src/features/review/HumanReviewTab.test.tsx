import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail, InvestigationOut } from "../../api/types";
import { STORAGE_KEYS, writeStorage } from "../../lib/storage";
import { errorEnvelope, fixtures, installMockApi } from "../../test/mockApi";
import { InvestigationSessionProvider } from "../investigation/InvestigationSession";
import HumanReviewTab, { actionBlocker, userBlockers } from "./HumanReviewTab";

const incident = fixtures.incident_101 as unknown as IncidentDetail;
const awaiting = fixtures.investigation_awaiting_review_101 as unknown as InvestigationOut;
const executed = fixtures.investigation_executed_101 as unknown as InvestigationOut;
const recommendationOnly = fixtures.investigation_completed_101 as unknown as InvestigationOut;
const actionId = awaiting.proposed_actions![0]!.id;

function renderTab(user: DemoUser, run: InvestigationOut) {
  writeStorage(STORAGE_KEYS.investigationFor(incident.id), run.id);
  return render(
    <ApiProvider user={user}>
      <InvestigationSessionProvider incident={incident} incidentRefreshing={false} reloadIncident={() => {}}>
        <HumanReviewTab />
      </InvestigationSessionProvider>
    </ApiProvider>,
  );
}

const decisionButton = (name: string) => within(screen.getByRole("group", { name: "Review decision" })).getByRole("button", { name });

describe("HumanReviewTab", () => {
  it("lets payments-lead approve; sends the decision and shows the record, simulated execution and outcome verification", async () => {
    const api = installMockApi();
    let approved = false;
    api.on("GET", `/api/investigations/${awaiting.id}`, () => ({ body: approved ? executed : awaiting }));
    api.on("POST", `/api/actions/${actionId}/review`, () => {
      approved = true;
      return { body: fixtures.review_result_101 };
    });
    api.on("GET", "/api/incidents/nova.inc.101/memories", (req) => ({
      body: req.query.get("include_unverified") === "true" ? fixtures.memories_draft_101 : fixtures.memories_101,
    }));
    api.on("POST", "/api/memories/nova.mem.01draft/validate", { body: { id: "nova.mem.01draft", verification_status: "verified", outcome: "successful" } });
    const user = userEvent.setup();
    renderTab("payments-lead", awaiting);

    await waitFor(() => expect(decisionButton("Approve")).toBeEnabled());
    // Nothing blocks this reviewer, so the blocker panel is not rendered at all.
    expect(screen.queryByRole("region", { name: "Why this decision is blocked" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Decision note"), "Rollback looks safe.");
    await user.click(decisionButton("Approve"));

    const post = api.requestsTo("POST", `/api/actions/${actionId}/review`)[0];
    expect(post?.body).toEqual({ decision: "APPROVE", comment: "Rollback looks safe." });
    expect(post?.user).toBe("payments-lead");

    const record = await screen.findByRole("list", { name: "Decision record" });
    expect(within(record).getByText(/Approved by payments-lead/)).toBeInTheDocument();
    expect(within(record).getByText(/Rollback looks safe/)).toBeInTheDocument();
    const execution = await screen.findByRole("region", { name: "Simulated execution" });
    expect(execution).toHaveTextContent("Simulated execution: succeeded");
    expect(execution).toHaveTextContent("Nothing real was changed");
    expect(execution).toHaveTextContent("SIM-0001");
    expect(decisionButton("Approve")).toBeDisabled();

    await user.click(await screen.findByRole("button", { name: "Mark successful" }));
    expect(api.requestsTo("POST", "/api/memories/nova.mem.01draft/validate")[0]?.body).toEqual({ outcome: "successful" });
    expect(await screen.findByText(/Outcome recorded as successful/)).toBeInTheDocument();
  });

  it("sends REJECT and shows no execution", async () => {
    const api = installMockApi();
    let decided = false;
    api.on("GET", `/api/investigations/${awaiting.id}`, () => ({ body: decided ? fixtures.investigation_rejected_101 : awaiting }));
    api.on("POST", `/api/actions/${actionId}/review`, () => {
      decided = true;
      return { body: { ...fixtures.review_result_101, memory_id: null, message: "Rejected." } };
    });
    const user = userEvent.setup();
    renderTab("payments-lead", awaiting);
    await waitFor(() => expect(decisionButton("Reject")).toBeEnabled());
    await user.click(decisionButton("Reject"));
    expect(api.requestsTo("POST", `/api/actions/${actionId}/review`)[0]?.body).toEqual({ decision: "REJECT", comment: null });
    expect(await screen.findByText(/Rejected by payments-lead/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Simulated execution" })).not.toBeInTheDocument();
  });

  it("shows the server's refusal and leaves the action pending", async () => {
    const api = installMockApi();
    api.on("GET", `/api/investigations/${awaiting.id}`, { body: awaiting });
    api.on("POST", `/api/actions/${actionId}/review`, {
      status: 403,
      body: errorEnvelope("missing_approver_role", "Reviewer lacks approver:payment"),
    });
    const user = userEvent.setup();
    renderTab("payments-lead", awaiting);
    await waitFor(() => expect(decisionButton("Approve")).toBeEnabled());
    await user.click(decisionButton("Approve"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("missing_approver_role");
    expect(alert).toHaveTextContent("The decision was not recorded");
    expect(decisionButton("Approve")).toBeEnabled();
  });

  it("explains why demo-responder cannot decide and never calls the review endpoint", async () => {
    const api = installMockApi();
    api.on("GET", `/api/investigations/${awaiting.id}`, { body: awaiting });
    const user = userEvent.setup();
    renderTab("demo-responder", awaiting);
    const why = await screen.findByRole("region", { name: "Why this decision is blocked" });
    expect(why).toHaveTextContent(/demo-responder lacks the action:review permission/);
    for (const name of ["Approve", "Reject", "Request revision", "Escalate"]) {
      expect(decisionButton(name)).toBeDisabled();
      await user.click(decisionButton(name));
    }
    expect(api.requestsTo("POST", /^\/api\/actions/)).toHaveLength(0);
  });

  it("tells the user to start a simulation run when the run was recommendation-only", async () => {
    installMockApi();
    renderTab("payments-lead", recommendationOnly);
    expect(await screen.findByText(/Start a simulation run to enable approval/)).toBeInTheDocument();
    expect(decisionButton("Approve")).toBeDisabled();
  });
});

describe("review helpers", () => {
  it("actionBlocker allows only pending_review proposals", () => {
    const p = awaiting.proposed_actions![0]!;
    expect(actionBlocker(p)).toBeNull();
    expect(actionBlocker({ ...p, status: "executed_simulated" })).toMatch(/already executed simulated/);
    expect(actionBlocker(null)).toMatch(/Start an investigation/);
  });

  it("userBlockers explains missing permission and role", () => {
    expect(userBlockers("demo-viewer", ["approver:payment"])).toEqual(["demo-viewer lacks the action:review permission."]);
    expect(userBlockers("payments-lead", ["approver:ledger"])).toEqual(["Requires the approver:ledger role."]);
    expect(userBlockers("payments-lead", ["approver:payment"])).toEqual([]);
  });
});
