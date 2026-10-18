import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "../App";
import type { DemoControls } from "../api/types";
import { errorEnvelope, installMockApi, type MockApi } from "../test/mockApi";

const DEP = "checkout_depends_on_payment";
const GOV = "rollback_policy_governs_payment";

function controls(dep: boolean, gov: boolean): DemoControls {
  const covered = gov;
  return {
    enabled: true,
    toggles: [
      {
        id: DEP,
        label: "Checkout depends on Payment",
        description: "dependency",
        edge: "nova.svc.checkout -[DEPENDS_ON]-> nova.svc.payment",
        present: dep,
      },
      {
        id: GOV,
        label: "Rollback policy v2 governs Payment",
        description: "policy",
        edge: "nova.dec.payment.rollback_v2 -[GOVERNS]-> nova.svc.payment",
        present: gov,
      },
    ],
    effect: !dep
      ? {
          incident_id: "nova.inc.101",
          rollback_paths: 0,
          target_service_ids: [],
          deployment_ids: [],
          approval_policy: "no_rollback_path",
          summary: "No rollback is recommended: nothing is reachable.",
        }
      : {
          incident_id: "nova.inc.101",
          rollback_paths: 1,
          target_service_ids: ["nova.svc.payment"],
          deployment_ids: ["nova.dep.payment.v2_4"],
          approval_policy: covered ? "policy_in_force" : "no_active_policy_escalate",
          summary: covered ? "Roll back deployment v2.4 of nova.svc.payment; approver: approver:payment." : "must escalate",
        },
  };
}

/** A tiny stateful backend for the two toggles. */
function installDemo(api: MockApi) {
  const state = { dep: true, gov: true };
  api.on("GET", "/api/demo/controls", () => ({ body: controls(state.dep, state.gov) }));
  api.on("PUT", /^\/api\/demo\/controls\/[^/]+$/, (req) => {
    const id = req.path.split("/").pop();
    const present = (req.body as { present: boolean }).present;
    if (id === "reset") {
      state.dep = state.gov = true;
    } else if (id === DEP) state.dep = present;
    else if (id === GOV) state.gov = present;
    return { body: controls(state.dep, state.gov) };
  });
  return state;
}

describe("DemoControlsPanel", () => {
  it("is not rendered when the server reports controls disabled", async () => {
    const api = installMockApi();
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);
    await screen.findByRole("heading", { level: 2, name: "Checkout 5xx spike after payment release" });
    expect(api.requestsTo("GET", "/api/demo/controls").length).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: "Demo controls" })).not.toBeInTheDocument();
  });

  it("stays hidden when the endpoint is missing (404)", async () => {
    const api = installMockApi();
    api.on("GET", "/api/demo/controls", { status: 404, body: errorEnvelope("not_found", "no such route") });
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);
    await screen.findByRole("heading", { level: 2, name: "Checkout 5xx spike after payment release" });
    expect(screen.queryByRole("heading", { name: "Demo controls" })).not.toBeInTheDocument();
  });

  it("is read-only for demo-viewer, with the reason", async () => {
    const api = installMockApi();
    installDemo(api);
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Demo controls" })).toBeInTheDocument();
    expect(screen.getByText(/demo-viewer cannot change demo controls/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Remove link: Checkout depends on Payment/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restore both" })).toBeDisabled();
    expect(api.requestsTo("PUT", /\/api\/demo\//)).toHaveLength(0);
  });

  it("removing a link changes the recommendation and refetches the incident; restore brings it back", async () => {
    const api = installMockApi();
    installDemo(api);
    const user = userEvent.setup();
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);
    await screen.findByRole("heading", { name: "Demo controls" });
    await user.selectOptions(screen.getByLabelText("Viewing as"), "demo-responder");
    expect(await screen.findByText(/Roll back deployment v2.4/)).toBeInTheDocument();
    const before = api.requestsTo("GET", "/api/incidents/nova.inc.101").length;

    await user.click(screen.getByRole("button", { name: /Remove link: Checkout depends on Payment/ }));

    expect(await screen.findByText(/No rollback is recommended/)).toBeInTheDocument();
    expect(screen.getByText("link removed")).toBeInTheDocument();
    const put = api.requestsTo("PUT", `/api/demo/controls/${DEP}`)[0];
    expect(put?.body).toEqual({ present: false });
    expect(put?.user).toBe("demo-responder");
    expect(put?.query.get("incident_id")).toBe("nova.inc.101");
    // No stale result: the incident (and so every tab) was fetched again after the change.
    await waitFor(() => expect(api.requestsTo("GET", "/api/incidents/nova.inc.101").length).toBeGreaterThan(before));

    await user.click(await screen.findByRole("button", { name: /Restore link: Checkout depends on Payment/ }));
    expect(await screen.findByText(/Roll back deployment v2.4/)).toBeInTheDocument();
  });

  it("shows the server error and keeps the panel usable when a change fails", async () => {
    const api = installMockApi();
    installDemo(api);
    api.on("PUT", `/api/demo/controls/${GOV}`, { status: 404, body: errorEnvelope("demo_data_missing", "not seeded") });
    const user = userEvent.setup();
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);
    await screen.findByRole("heading", { name: "Demo controls" });
    await user.selectOptions(screen.getByLabelText("Viewing as"), "payments-lead");
    await user.click(screen.getByRole("button", { name: /Remove link: Rollback policy v2 governs Payment/ }));
    expect(await screen.findByText("Could not change the demo graph")).toBeInTheDocument();
    expect(screen.getByText("demo_data_missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Remove link: Rollback policy v2 governs Payment/ })).toBeEnabled();
  });
});
