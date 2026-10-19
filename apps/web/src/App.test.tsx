import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";
import { errorEnvelope, fixtures, installMockApi } from "./test/mockApi";

describe("App", () => {
  it("renders the synthetic-workspace marker and the incident list from fixtures", async () => {
    installMockApi();
    render(<App />);
    expect(screen.getByText(/SYNTHETIC WORKSPACE/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Incident Workbench" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Incident list" });
    expect(within(list).getByText("INC-101")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /1 RESOLVED/ })).toBeInTheDocument();
    expect(within(list).getByText("Checkout 5xx spike after payment release")).toBeInTheDocument();
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it("selecting INC-101 shows the workspace header and five tabs", async () => {
    const api = installMockApi();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /INC-101/ }));

    expect(await screen.findByRole("heading", { level: 2, name: "Checkout 5xx spike after payment release" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/incidents/nova.inc.101");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Investigation",
      "Evidence graph",
      "Knowledge & memory",
      "Human review",
      "History",
    ]);
    await user.click(screen.getByRole("tab", { name: "Evidence graph" }));
    expect(window.location.hash).toBe("#/incidents/nova.inc.101/evidence");
    expect(api.requestsTo("GET", "/api/incidents/nova.inc.101")[0]?.user).toBe("demo-viewer");
  });

  it("disables Start Investigation for demo-viewer and enables it for demo-responder", async () => {
    const api = installMockApi();
    const user = userEvent.setup();
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);

    const button = await screen.findByRole("button", { name: "Start Investigation" });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute("title", expect.stringContaining("investigation:create"));

    await user.selectOptions(screen.getByLabelText("Viewing as"), "demo-responder");
    expect(screen.getByRole("button", { name: "Start Investigation" })).toBeEnabled();
    expect(window.localStorage.getItem("graphathon.demoUser")).toBe("demo-responder");

    await user.click(screen.getByRole("button", { name: "Start Investigation" }));
    expect((await screen.findAllByText("Queued")).length).toBeGreaterThan(0);
    const post = api.requestsTo("POST", "/api/investigations")[0];
    expect(post?.user).toBe("demo-responder");
    expect(post?.body).toEqual({ incident_id: "nova.inc.101", mode: "recommendation_only" });
    expect(window.localStorage.getItem("graphathon.investigation.nova.inc.101")).toBe("nova.ses.01example");
    await waitFor(() => expect(api.requestsTo("GET", "/api/investigations/nova.ses.01example").length).toBeGreaterThan(0));
  });

  it("shows a 409 from Start Investigation in an ErrorBanner", async () => {
    const api = installMockApi();
    api.on("POST", "/api/investigations", {
      status: 409,
      body: errorEnvelope("incident_resolved", "incident is resolved", "req-409-abcdef"),
    });
    window.localStorage.setItem("graphathon.demoUser", "payments-lead");
    window.location.hash = "#/incidents/nova.inc.101";
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Start Investigation" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("incident_resolved");
    expect(alert).toHaveTextContent("req-409-abcdef");
  });

  it("offers no way to start an investigation on a resolved incident", async () => {
    installMockApi();
    window.localStorage.setItem("graphathon.demoUser", "payments-lead");
    window.location.hash = "#/incidents/nova.inc.092";
    render(<App />);
    expect(await screen.findByText("Incident resolved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start investigation/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-investigate" })).not.toBeInTheDocument();
  });

  it("moves the navigator badge from Open to Investigating when a run starts, without a manual refresh", async () => {
    const api = installMockApi();
    // The list endpoint stays stale (open); only the incident detail reflects the server-side status change.
    api.on("GET", "/api/incidents/nova.inc.101", () => ({
      body: { ...fixtures.incident_101, status: api.requestsTo("POST", "/api/investigations").length > 0 ? "investigating" : "open" },
    }));
    window.localStorage.setItem("graphathon.demoUser", "payments-lead");
    window.location.hash = "#/incidents/nova.inc.101";
    const user = userEvent.setup();
    render(<App />);

    const list = await screen.findByRole("list", { name: "Incident list" });
    const row = () => within(list).getByRole("button", { name: /INC-101/ });
    expect(within(row()).getByText("Open")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Start Investigation" }));
    await waitFor(() => expect(within(row()).getByText("Investigating")).toBeInTheDocument());
    expect(within(row()).queryByText("Open")).not.toBeInTheDocument();
  });

  it("maps legacy tab hashes to the new sections", async () => {
    installMockApi();
    window.location.hash = "#/incidents/nova.inc.101/overview";
    render(<App />);
    const tab = await screen.findByRole("tab", { name: "Investigation" });
    expect(tab).toHaveAttribute("aria-selected", "true");
  });

  it("toggles the navigator between Active and Resolved incidents", async () => {
    installMockApi();
    const user = userEvent.setup();
    render(<App />);
    const list = await screen.findByRole("list", { name: "Incident list" });
    expect(within(list).getByText("INC-101")).toBeInTheDocument();
    expect(within(list).queryByText("INC-092")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /RESOLVED/ }));
    expect(within(screen.getByRole("list", { name: "Incident list" })).getByText("INC-092")).toBeInTheDocument();
  });
});
