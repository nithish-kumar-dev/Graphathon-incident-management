import { describe, expect, it } from "vitest";
import type { IncidentSummary, InvestigationOut } from "../../api/types";
import completed from "../../test/fixtures/investigation_completed_101.json";
import failed from "../../test/fixtures/investigation_failed_101.json";
import queued from "../../test/fixtures/investigation_queued.json";
import awaiting from "../../test/fixtures/investigation_awaiting_review_101.json";
import executed from "../../test/fixtures/investigation_executed_101.json";
import rejected from "../../test/fixtures/investigation_rejected_101.json";
import events from "../../test/fixtures/investigation_events_101.json";
import incidents from "../../test/fixtures/incidents.json";
import type { AgentEventOut } from "../../api/types";
import { deriveAgents, deriveStages, phaseOf, primaryActionFor, runEventsToTimeline } from "./model";

const incident = (incidents as { items: IncidentSummary[] }).items[0]!;
const inv = (x: unknown) => x as InvestigationOut;
const status = (stages: ReturnType<typeof deriveStages>, id: string) => stages.find((s) => s.id === id)?.status;

describe("investigation model", () => {
  it("chooses the primary action from the real phase", () => {
    expect(primaryActionFor("none").kind).toBe("start");
    expect(primaryActionFor("running").kind).toBe("resume");
    expect(primaryActionFor("awaiting_review").kind).toBe("resume");
    expect(primaryActionFor("completed").kind).toBe("view");
    expect(primaryActionFor("failed").kind).toBe("view");
  });

  it("maps timed_out to failed", () => {
    expect(phaseOf(inv({ ...failed, status: "timed_out" }))).toBe("failed");
    expect(phaseOf(null)).toBe("none");
  });

  it("derives stages from backend state only", () => {
    const none = deriveStages(incident, null);
    expect(none).toHaveLength(6);
    expect(status(none, "execution")).not.toBe("completed");
    expect(status(deriveStages(incident, inv(queued)), "analyzing")).toBe("pending");
    expect(status(deriveStages(incident, inv(awaiting)), "review")).toBe("waiting");
    const done = deriveStages(incident, inv(completed));
    expect(status(done, "analyzing")).toBe("completed");
    expect(status(done, "review")).toBe("skipped");
    expect(status(done, "execution")).toBe("skipped");
    const bad = deriveStages(incident, inv(failed));
    expect(bad.some((s) => s.status === "failed")).toBe(true);
  });

  it("marks review and execution completed after an approved, simulated execution", () => {
    const stages = deriveStages(incident, inv(executed));
    expect(status(stages, "review")).toBe("completed");
    expect(stages.find((x) => x.id === "review")?.caption).toBe("Approved by payments-lead.");
    expect(status(stages, "execution")).toBe("completed");
    expect(stages.find((x) => x.id === "execution")?.caption).toContain("Nothing real was changed");
  });

  it("marks a rejected action as reviewed with nothing executed", () => {
    const stages = deriveStages(incident, inv(rejected));
    expect(status(stages, "review")).toBe("completed");
    expect(stages.find((x) => x.id === "review")?.caption).toBe("Rejected by payments-lead.");
    expect(status(stages, "execution")).toBe("skipped");
  });

  it("keeps a revision request or escalation visible as a human decision", () => {
    const revision = inv({ ...executed, proposed_actions: [{ ...executed.proposed_actions[0], status: "revision_requested", execution: null }] });
    expect(status(deriveStages(incident, revision), "review")).toBe("completed");
    const escalated = inv({ ...executed, status: "escalated", proposed_actions: [{ ...executed.proposed_actions[0], status: "escalated", execution: null }] });
    const stages = deriveStages(incident, escalated);
    expect(status(stages, "recommending")).toBe("completed");
    expect(status(stages, "review")).toBe("waiting");
  });

  it("turns step events into timeline rows, dropping 'started' and keeping ids unique", () => {
    const rows = runEventsToTimeline(events.events as AgentEventOut[]);
    expect(rows).toHaveLength(events.events.length - 1);
    expect(rows.every((r) => r.id.startsWith("run:"))).toBe(true);
    expect(rows.map((r) => r.type)).toContain("agent_step_waiting");
    expect(rows.find((r) => r.summary?.startsWith("Coordinator"))?.summary).toBe("Coordinator: 3 branches");
    expect(runEventsToTimeline(null)).toEqual([]);
  });

  it("shows no agents when no run exists", () => {
    expect(deriveAgents({ incident: incident as never, investigation: null, bundle: null })).toEqual([]);
  });
});
