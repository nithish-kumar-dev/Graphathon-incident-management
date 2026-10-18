import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";
import { errorEnvelope, installMockApi } from "./test/mockApi";

describe("App", () => {
  it("renders the synthetic-data banner and the incident list from fixtures", async () => {
    installMockApi();
    render(<App />);
    expect(screen.getByText("Synthetic company data — NovaCommerce is fictional")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Graphathon Incident Investigator" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Incident list" });
    expect(within(list).getByText("INC-101")).toBeInTheDocument();
    expect(within(list).getByText("INC-092")).toBeInTheDocument();
    expect(within(list).getByText("Checkout 5xx spike after payment release")).toBeInTheDocument();
    expect(await screen.findByText("Backend ready")).toBeInTheDocument();
  });

  it("selecting INC-101 shows the workspace header and five tabs", async () => {
    const api = installMockApi();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /INC-101/ }));

    expect(await screen.findByRole("heading", { level: 2, name: "Checkout 5xx spike after payment release" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/incidents/nova.inc.101");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Overview",
      "Graph evidence",
      "Agent activity",
      "Memory & company brain",
      "Human review",
    ]);
    await user.click(screen.getByRole("tab", { name: "Graph evidence" }));
    expect(window.location.hash).toBe("#/incidents/nova.inc.101/evidence");
    expect(api.requestsTo("GET", "/api/incidents/nova.inc.101")[0]?.user).toBe("demo-viewer");
  });

  it("disables Investigate for demo-viewer and enables it for demo-responder", async () => {
    const api = installMockApi();
    const user = userEvent.setup();
    window.location.hash = "#/incidents/nova.inc.101";
    render(<App />);

    const button = await screen.findByRole("button", { name: "Investigate" });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute("title", expect.stringContaining("investigation:create"));

    await user.selectOptions(screen.getByLabelText("Demo identity (not authentication)"), "demo-responder");
    expect(screen.getByRole("button", { name: "Investigate" })).toBeEnabled();
    expect(window.localStorage.getItem("graphathon.demoUser")).toBe("demo-responder");

    await user.click(screen.getByRole("button", { name: "Investigate" }));
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    const post = api.requestsTo("POST", "/api/investigations")[0];
    expect(post?.user).toBe("demo-responder");
    expect(post?.body).toEqual({ incident_id: "nova.inc.101", mode: "recommendation_only" });
    expect(window.localStorage.getItem("graphathon.investigation.nova.inc.101")).toBe("nova.ses.01example");
    await waitFor(() => expect(api.requestsTo("GET", "/api/investigations/nova.ses.01example").length).toBeGreaterThan(0));
  });

  it("shows a 409 from Investigate in an ErrorBanner", async () => {
    const api = installMockApi();
    api.on("POST", "/api/investigations", {
      status: 409,
      body: errorEnvelope("incident_resolved", "incident is resolved", "req-409-abcdef"),
    });
    window.localStorage.setItem("graphathon.demoUser", "payments-lead");
    window.location.hash = "#/incidents/nova.inc.101";
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Investigate" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("incident_resolved");
    expect(alert).toHaveTextContent("req-409-abcdef");
  });
});
