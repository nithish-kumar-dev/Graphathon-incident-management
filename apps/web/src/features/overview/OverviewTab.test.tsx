import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail, InvestigationOut, ProposedActionOut } from "../../api/types";
import { fixtures, installMockApi } from "../../test/mockApi";
import OverviewTab from "./OverviewTab";
import { formatUtc } from "./format";

const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
const incident101 = () => clone<IncidentDetail>(fixtures.incident_101);
const incident092 = () => clone<IncidentDetail>(fixtures.incident_092);

function renderOverview(incident: IncidentDetail, investigation: InvestigationOut | null = null, user: DemoUser = "demo-viewer") {
  installMockApi();
  return render(
    <ApiProvider user={user}>
      <OverviewTab incident={incident} investigation={investigation} user={user} reloadIncident={() => {}} />
    </ApiProvider>,
  );
}

describe("formatUtc", () => {
  it("formats ISO timestamps as readable UTC and tolerates missing values", () => {
    expect(formatUtc("2026-10-17T14:05:00Z")).toBe("2026-10-17 14:05 UTC");
    expect(formatUtc("2026-10-17T13:52:00+00:00")).toBe("2026-10-17 13:52 UTC");
    expect(formatUtc(null)).toBe("—");
    expect(formatUtc("not a date")).toBe("not a date");
  });
});

describe("OverviewTab", () => {
  it("INC-101 without an investigation: facts, alerts and the path as a hypothesis", () => {
    renderOverview(incident101());

    expect(screen.getByText("No investigation yet — use Investigate above")).toBeInTheDocument();
    expect(screen.getByText("2026-10-17 14:05 UTC")).toBeInTheDocument();
    expect(screen.getByText("Not resolved")).toBeInTheDocument();

    const alerts = screen.getByRole("table", { name: /Alerts attached/ });
    expect(within(alerts).getAllByRole("row")).toHaveLength(3);
    expect(within(alerts).getByText("checkout:http_5xx_rate")).toBeInTheDocument();
    expect(within(alerts).getByText("synthetic://alerts/101-b")).toBeInTheDocument();
    expect(within(alerts).getByText("payment p99 2.8s (threshold 800ms)")).toBeInTheDocument();

    // One label per path: the hypothesis badge (with an explanatory title), not a second "Correlated" badge beside it.
    const label = within(screen.getByRole("list", { name: "Explanation paths" })).getByText("Hypothesis — correlated, not confirmed");
    expect(label).toBeVisible();
    expect(label).toHaveAttribute("title", "A graph correlation. Evidence for a hypothesis, not a confirmed cause.");
    expect(within(screen.getByRole("list", { name: "Explanation paths" })).queryByText("Correlated · not confirmed")).not.toBeInTheDocument();
    expect(screen.getAllByText(/not confirmed/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/confirmed cause/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/confirmed cause/i);

    const paths = screen.getByRole("list", { name: "Explanation paths" });
    expect(within(paths).getAllByText("nova.dep.payment.v2_4").length).toBeGreaterThan(0);
    expect(within(paths).getByText("nova.ev.101.deploy")).toBeInTheDocument();
    expect(within(paths).getAllByText("synthetic://deploys/payment/v2.4").length).toBeGreaterThan(0);
    expect(within(paths).getByText("nova.svc.payment")).toBeInTheDocument();
  });

  it("proposes the runbook action as a proposal, and shows the role the viewer lacks", () => {
    renderOverview(incident101(), null, "demo-viewer");
    const actions = screen.getByRole("list", { name: "Proposed actions" });
    expect(within(actions).getByText("rollback_deployment_simulated")).toBeInTheDocument();
    expect(within(actions).getByText("approver:payment")).toBeInTheDocument();
    expect(within(actions).getByText("Payment rollback policy v2")).toBeInTheDocument();
    expect(within(actions).getByText("nova.rb.payment.rollback")).toBeInTheDocument();
    expect(within(actions).getByText("Requires approver:payment")).toBeInTheDocument();
    expect(within(actions).queryByText(/You hold/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Proposal only — execution requires human approval (Phase 5); recommendation_only mode never executes."),
    ).toBeInTheDocument();
    // Nothing on this tab can execute anything.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows 'You hold approver:payment' for payments-lead", () => {
    renderOverview(incident101(), null, "payments-lead");
    const actions = screen.getByRole("list", { name: "Proposed actions" });
    expect(within(actions).getByText("You hold approver:payment")).toBeInTheDocument();
    expect(within(actions).queryByText(/^Requires/)).not.toBeInTheDocument();
  });

  it("shows the inconclusive empty state when there is no explanation path", () => {
    const inc = incident101();
    inc.explanation_paths = [];
    renderOverview(inc);
    expect(screen.getByText("No evidence-backed path found — inconclusive")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("No proposed actions")).toBeInTheDocument();
    expect(screen.queryByText("rollback_deployment_simulated")).not.toBeInTheDocument();
  });

  it("lists investigation_092 findings with their own claim type and evidence ids", () => {
    renderOverview(incident092(), clone<InvestigationOut>(fixtures.investigation_092));
    expect(within(screen.getByTestId("investigation-state")).getByText("Completed — the run finished")).toBeInTheDocument();
    const findings = screen.getByRole("list", { name: "Investigation findings" });
    expect(within(findings).getByTitle("Confirmed by a human or by ground truth.")).toHaveTextContent("Confirmed");
    expect(within(findings).getByText("payment v2.3 connection pool regression caused checkout 5xx")).toBeInTheDocument();
    for (const id of ["nova.ev.092.deploy", "nova.ev.092.checkout_errors", "nova.ev.092.recovery"]) {
      expect(within(findings).getByText(id)).toBeInTheDocument();
    }
    expect(within(findings).getByText("synthetic://metrics/checkout/http_5xx?t=2026-08-12T10:00Z")).toBeInTheDocument();
    // The graph path for the same incident still reads as a hypothesis.
    expect(within(screen.getByRole("list", { name: "Explanation paths" })).getByText("Hypothesis — correlated, not confirmed")).toBeInTheDocument();
    expect(screen.getByTitle("Incident status: Resolved")).toBeInTheDocument();
  });

  it("shows finding and investigation integrity warnings", () => {
    const inv = clone<InvestigationOut>(fixtures.investigation_092);
    inv.integrity_warnings = ["findings withheld: schema mismatch"];
    inv.findings[0]!.claim_type = "hypothesis";
    inv.findings[0]!.integrity_warnings = ["evidence id nova.ev.092.ghost omitted: not in graph"];
    renderOverview(incident092(), inv);
    expect(screen.getByText("findings withheld: schema mismatch")).toBeInTheDocument();
    expect(screen.getByText("evidence id nova.ev.092.ghost omitted: not in graph")).toBeInTheDocument();
    const findings = screen.getByRole("list", { name: "Investigation findings" });
    expect(within(findings).getByText("Hypothesis · not confirmed")).toBeInTheDocument();
    expect(within(findings).queryByText("Confirmed")).not.toBeInTheDocument();
  });

  it("explains a queued investigation", () => {
    renderOverview(incident101(), clone<InvestigationOut>(fixtures.investigation_queued));
    const state = screen.getByTestId("investigation-state");
    expect(state).toHaveTextContent("Queued — waiting for the orchestrator");
    expect(state).toHaveTextContent("The agent run arrives in a later phase");
    expect(screen.getByTitle("Investigation state: queued")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Investigation findings" })).not.toBeInTheDocument();
  });

  it("shows pending human approval for awaiting_review", () => {
    const inv = clone<InvestigationOut>(fixtures.investigation_queued);
    inv.status = "awaiting_review";
    renderOverview(incident101(), inv);
    expect(screen.getByTestId("investigation-state")).toHaveTextContent("Pending human approval");
    expect(screen.getByTitle("Investigation state: awaiting_review")).toBeInTheDocument();
  });

  it.each([
    ["running", "Running — the agent is gathering context"],
    ["failed", "Failed — the run did not finish"],
    ["escalated", "Escalated to a human"],
    ["inconclusive", "Inconclusive — no evidence-backed explanation"],
    ["timed_out", "Timed out — stopped before finishing"],
  ] as const)("shows a distinct message for %s", (status, title) => {
    const inv = clone<InvestigationOut>(fixtures.investigation_queued);
    inv.status = status;
    renderOverview(incident101(), inv);
    expect(within(screen.getByTestId("investigation-state")).getByText(title)).toBeInTheDocument();
  });

  it("shows 'No active policy — escalate' when no policy governs the target", () => {
    const inc = incident101();
    inc.explanation_paths[0]!.approval_policy = "no_active_policy_escalate";
    inc.explanation_paths[0]!.governing_decisions = [];
    renderOverview(inc, null, "payments-lead");
    const actions = screen.getByRole("list", { name: "Proposed actions" });
    expect(within(actions).getByText("No active policy — escalate")).toBeInTheDocument();
    expect(within(actions).queryByText(/You hold/)).not.toBeInTheDocument();
    expect(within(actions).getByText("rollback_deployment_simulated")).toBeInTheDocument();
  });
});

describe("OverviewTab with Phase 4 results", () => {
  const completed = () => clone<InvestigationOut>(fixtures.investigation_completed_101);

  const TEL_REF_OF = (inv: InvestigationOut) => inv.findings[1]!.evidence[0]!;

  it("completed run: summary, investigator, gate, findings with confidence, and the real proposal", () => {
    const inv = completed();
    const proposal = inv.proposed_actions![0]!;
    const observed = TEL_REF_OF(inv);
    renderOverview(incident101(), inv);

    expect(screen.getByRole("region", { name: "Investigation summary" })).toHaveTextContent(inv.summary!);
    expect(screen.getByTitle("Investigator: stub-v1")).toHaveTextContent("stub-v1");
    expect(screen.getByText("gate: accept")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Gate violations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    const findings = screen.getByRole("list", { name: "Investigation findings" });
    const items = within(findings).getAllByRole("listitem").filter((li) => li.parentElement === findings);
    expect(items).toHaveLength(inv.findings.length);
    expect(within(items[0]!).getByText("Correlated · not confirmed")).toBeInTheDocument();
    expect(within(items[0]!).getByText("confidence 80%")).toBeInTheDocument();
    expect(within(items[0]!).getByText(/Deployment v2\.4 of payment/)).toBeInTheDocument();
    expect(within(items[0]!).getByText("nova.ev.101.deploy")).toBeInTheDocument();
    expect(within(items[0]!).getByText(inv.findings[0]!.evidence.find((e) => e.id.startsWith("nova.ev.tel."))!.id)).toBeInTheDocument();
    expect(within(items[0]!).getByText("None recorded.")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Observed")).toBeInTheDocument();
    expect(within(items[1]!).getByText("confidence 85%")).toBeInTheDocument();
    expect(within(items[1]!).getByText(observed.source_ref)).toBeInTheDocument();

    const actions = screen.getByRole("list", { name: "Proposed actions" });
    expect(within(actions).getByText(proposal.id)).toBeInTheDocument();
    expect(within(actions).getByText(proposal.proposal_id)).toBeInTheDocument();
    const hash = within(actions).getByText(`${proposal.spec_hash.slice(0, 12)}…`);
    expect(hash).toHaveAttribute("title", proposal.spec_hash);
    expect(within(actions).getByTitle("Proposal status: proposed")).toBeInTheDocument();
    expect(within(actions).getByText("Proposal")).toBeInTheDocument();
    expect(within(actions).getByText(proposal.rationale)).toBeInTheDocument();
    expect(within(actions).getByRole("list", { name: `Evidence for proposal ${proposal.id}` })).toHaveTextContent(proposal.evidence[0]!.id);
    expect(within(actions).getByText("Requires approver:payment")).toBeInTheDocument();
    // The path-derived preview is replaced by the real proposal.
    expect(screen.queryByText("Preview — derived from graph paths")).not.toBeInTheDocument();
    expect(within(actions).getAllByRole("listitem").filter((li) => li.parentElement === actions)).toHaveLength(1);
    expect(screen.getByText(/Proposal only — execution requires human approval/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/(?<!not a )confirmed cause/i);
  });

  it("falls back to the path-derived preview when the run proposed nothing", () => {
    const inv = completed();
    inv.proposed_actions = [];
    renderOverview(incident101(), inv);
    const actions = screen.getByRole("list", { name: "Proposed actions" });
    expect(within(actions).getByText("Preview — derived from graph paths")).toBeInTheDocument();
    expect(within(actions).getByText("Payment service deployment rollback")).toBeInTheDocument();
  });

  it("shows contradicting evidence separately from supporting evidence", () => {
    const inv = completed();
    inv.findings[0]!.contradicting_evidence = [
      {
        id: "nova.ev.tel.contradiction",
        kind: "metric",
        source_ref: "synthetic://telemetry/payment/error_rate?t=2026-10-17T14:04Z",
        observed_at: "2026-10-17T14:04:00Z",
        excerpt: null,
      },
    ];
    renderOverview(incident101(), inv);
    const contra = screen.getByRole("list", { name: "Contradicting evidence for finding 1" });
    expect(within(contra).getByText("nova.ev.tel.contradiction")).toBeInTheDocument();
    expect(within(contra).getByText("synthetic://telemetry/payment/error_rate?t=2026-10-17T14:04Z")).toBeInTheDocument();
    const supporting = screen.getByRole("list", { name: "Evidence for finding 1" });
    expect(within(supporting).queryByText("nova.ev.tel.contradiction")).not.toBeInTheDocument();
  });

  it("escalated run: escalated banner and every gate violation", () => {
    const inv = clone<InvestigationOut>(fixtures.investigation_escalated_101);
    renderOverview(incident101(), inv);
    expect(screen.getByTestId("investigation-state")).toHaveTextContent("Escalated to a human");
    expect(screen.getByText("gate: escalate")).toBeInTheDocument();
    expect(screen.getByTitle("Investigator: stub-v1")).toBeInTheDocument();
    const violations = screen.getByRole("list", { name: "Gate violations" });
    const items = within(violations).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("unknown_runbook");
    expect(items[0]).toHaveTextContent("proposed_actions[0]");
    expect(items[0]).toHaveTextContent("runbook nova.rb.payment.nonexistent does not exist");
    // No real proposal, so the preview is shown and labelled as such.
    expect(screen.getByText("Preview — derived from graph paths")).toBeInTheDocument();
  });

  it("failed run: the error is shown", () => {
    renderOverview(incident101(), clone<InvestigationOut>(fixtures.investigation_failed_101));
    expect(screen.getByTestId("investigation-state")).toHaveTextContent("Failed — the run did not finish");
    expect(screen.getByRole("alert")).toHaveTextContent("unexpected RuntimeError");
    expect(screen.queryByRole("region", { name: "Investigation summary" })).not.toBeInTheDocument();
  });

  it("flags a stub-fallback investigator visibly", () => {
    const inv = completed();
    inv.investigator = "stub-fallback(ollama timeout)";
    renderOverview(incident101(), inv);
    const badge = screen.getByText("stub-fallback(ollama timeout)");
    expect(badge).toHaveAttribute("title", expect.stringMatching(/^Fallback: the configured LLM investigator was unavailable/));
    expect(badge).toHaveTextContent("⚠");
    expect(badge.className).toMatch(/bg-warn(?!-)/);
    expect(screen.queryByTitle("Investigator: stub-fallback(ollama timeout)")).not.toBeInTheDocument();
  });

  it("older responses without Phase 4 fields still render", () => {
    const inv = clone<InvestigationOut>(fixtures.investigation_092);
    const asLegacy = inv as InvestigationOut & { proposed_actions?: ProposedActionOut[] };
    delete asLegacy.proposed_actions;
    renderOverview(incident092(), asLegacy);
    expect(screen.queryByText(/^gate:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText("Contradicting evidence")).not.toBeInTheDocument();
  });
});
