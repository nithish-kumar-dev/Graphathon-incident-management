import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/client";
import type { DemoUser, IncidentDetail, IncidentMemories, RetrievalBundle, ServiceContext } from "../../api/types";
import { fixtures, installMockApi, type MockApi } from "../../test/mockApi";
import type { TabProps } from "../types";
import MemoryTab from "./MemoryTab";

const clone = <T,>(v: unknown): T => JSON.parse(JSON.stringify(v)) as T;
const MEMORIES = "/api/incidents/nova.inc.101/memories";
const RETRIEVAL = "/api/incidents/nova.inc.101/retrieval";

function tab(user: DemoUser, overrides: Partial<TabProps> = {}) {
  const props: TabProps = {
    incident: clone<IncidentDetail>(fixtures.incident_101),
    investigation: null,
    user,
    reloadIncident: () => {},
    ...overrides,
  };
  return (
    <ApiProvider user={user}>
      <MemoryTab {...props} />
    </ApiProvider>
  );
}

/** Like the real API: drafts only with include_unverified=true. */
function serveMemoriesLikeServer(api: MockApi) {
  api.on("GET", MEMORIES, (req) => {
    const all = clone<IncidentMemories>(fixtures.memories_101);
    const include = req.query.get("include_unverified") === "true";
    return {
      body: {
        ...all,
        include_unverified: include,
        memories: include ? all.memories : all.memories.filter((m) => m.verification_status === "verified"),
      },
    };
  });
}

function memoryItem(id: string): HTMLElement {
  const list = screen.getByRole("list", { name: "Memories" });
  return within(list).getByText(id).closest("li") as HTMLElement;
}

function sectionOf(heading: string): HTMLElement {
  return screen.getByRole("heading", { name: heading }).closest("section") as HTMLElement;
}

describe("MemoryTab", () => {
  it("shows verified precedent by default and no draft", async () => {
    const api = installMockApi();
    serveMemoriesLikeServer(api);
    render(tab("demo-viewer"));

    await screen.findByRole("list", { name: "Memories" });
    const toggle = screen.getByRole("checkbox", { name: "Include unverified (drafts)" });
    expect(toggle).not.toBeChecked();
    expect(api.requestsTo("GET", MEMORIES)[0]?.query.get("include_unverified")).not.toBe("true");

    const success = memoryItem("nova.mem.092.rollback_success");
    expect(within(success).getByText("Supports")).toBeInTheDocument();
    expect(within(success).getByText("payments-lead")).toBeInTheDocument();
    expect(within(success).getByText("nova.act.092.rollback.v1")).toBeInTheDocument();
    expect(within(success).getByText("synthetic://wiki/postmortems/092")).toBeInTheDocument();
    expect(within(success).getByText(/shared service/)).toBeInTheDocument();

    const failed = memoryItem("nova.mem.092.restart_failed");
    expect(within(failed).getByText(/Warns against/)).toBeInTheDocument();
    expect(within(failed).getByText("synthetic://tickets/OPS-4411")).toBeInTheDocument();

    expect(screen.queryByText("nova.mem.092.cache_ttl_idea")).not.toBeInTheDocument();
    expect(screen.queryByText(/Draft — not usable as precedent/)).not.toBeInTheDocument();
  });

  it("never shows a draft with the toggle off, even if the server sends one", async () => {
    installMockApi(); // default route returns the include_unverified=true fixture
    render(tab("demo-viewer"));
    await screen.findByRole("list", { name: "Memories" });
    expect(screen.queryByText("nova.mem.092.cache_ttl_idea")).not.toBeInTheDocument();
  });

  it("toggling include-unverified refetches with include_unverified=true and labels the draft", async () => {
    const api = installMockApi();
    serveMemoriesLikeServer(api);
    const user = userEvent.setup();
    render(tab("demo-viewer"));
    await screen.findByRole("list", { name: "Memories" });

    await user.click(screen.getByRole("checkbox", { name: "Include unverified (drafts)" }));
    await waitFor(() =>
      expect(api.requestsTo("GET", MEMORIES).at(-1)?.query.get("include_unverified")).toBe("true"),
    );
    const draft = await waitFor(() => memoryItem("nova.mem.092.cache_ttl_idea"));
    expect(within(draft).getByText("Draft — not usable as precedent")).toBeInTheDocument();
    expect(within(draft).queryByText("Supports")).not.toBeInTheDocument();
    expect(within(draft).getByText("not validated")).toBeInTheDocument();
    expect(within(memoryItem("nova.mem.092.rollback_success")).getByText("Supports")).toBeInTheDocument();
  });

  it("ranks retrieval memories with score, components, rationale and excluded counts", async () => {
    installMockApi();
    render(tab("demo-viewer"));
    const ranked = await screen.findByRole("list", { name: "Ranked memories" });
    const items = Array.from(ranked.children) as HTMLElement[];
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("score 0.7784");
    expect(items[0]).toHaveTextContent("applies: shared service");
    expect(items[0]).toHaveTextContent("Supports");
    expect(items[0]).toHaveTextContent("verified successful outcome (human, by nova.rsp.payments_lead)");
    expect(within(items[0]!).getByRole("table", { name: /Score components/ })).toHaveTextContent("verified_outcome");
    expect(items[1]).toHaveTextContent("Warns against");
    expect(screen.getByText(/1 draft excluded/)).toBeInTheDocument();
  });

  it("says a text-similarity-only memory cannot support or warn", async () => {
    const api = installMockApi();
    const bundle = clone<RetrievalBundle>(fixtures.retrieval_101);
    bundle.memory_context.items[0]!.applicability = "text_similarity_only";
    bundle.memory_context.items[0]!.precedent = "none";
    api.on("GET", RETRIEVAL, { body: bundle });
    render(tab("demo-viewer"));
    expect(await screen.findByText("Text similarity only — cannot support or warn")).toBeInTheDocument();
  });

  it("shows knowledge chunks as context with verbatim graph links, never the restricted handbook", async () => {
    const api = installMockApi();
    const bundle = clone<RetrievalBundle>(fixtures.retrieval_101);
    bundle.knowledge_context.excluded = { unauthorised: 1 };
    api.on("GET", RETRIEVAL, { body: bundle });
    render(tab("demo-viewer"));

    const chunks = await screen.findByRole("list", { name: "Knowledge chunks" });
    const link = "Decision nova.dec.payment.rollback_v2 -[DOCUMENTED_IN]-> Document nova.doc.adr_031";
    expect(within(chunks).getAllByText(link).some((el) => el.tagName === "CODE")).toBe(true);
    expect(within(chunks).getAllByText("Context — not a claim")).toHaveLength(3);
    expect(within(chunks).getByText("synthetic://wiki/adr/031#chunk-0")).toBeInTheDocument();
    expect(within(chunks).getByText("no graph link — text match only")).toBeInTheDocument();
    expect(screen.getByText(/1 unauthorised excluded/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("sec_handbook");
    // synthetic:// refs are text, never links
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("shows the owning team and current policy for the target service", async () => {
    const api = installMockApi();
    render(tab("demo-viewer"));
    const section = sectionOf("Owning team and current policy");
    expect(await within(section).findByText("nova.team.payments")).toBeInTheDocument();
    expect(within(section).getByText("payments-lead")).toBeInTheDocument();
    expect(within(section).getByText("Payment rollback policy v2")).toBeInTheDocument();
    expect(within(section).getByText(/ADR-031/)).toBeInTheDocument();
    expect(within(section).getByText("approver:payment")).toBeInTheDocument();
    expect(within(section).getByText("nova.dec.payment.rollback_v1")).toBeInTheDocument();
    expect(within(section).getByText("synthetic://wiki/adr/031")).toBeInTheDocument();
    expect(api.requestsTo("GET", "/api/services/nova.svc.payment/context")).toHaveLength(1);
  });

  it("falls back to the first affected service when there is no explanation path", async () => {
    const api = installMockApi();
    api.on("GET", "/api/services/nova.svc.checkout/context", {
      body: { ...clone<ServiceContext>(fixtures.service_payment), service: { id: "nova.svc.checkout", name: "checkout", tier: "tier1" } },
    });
    const incident = clone<IncidentDetail>(fixtures.incident_101);
    incident.explanation_paths = [];
    render(tab("demo-viewer", { incident }));
    const section = sectionOf("Owning team and current policy");
    await within(section).findByText("nova.team.payments");
    expect(api.requestsTo("GET", "/api/services/nova.svc.checkout/context")).toHaveLength(1);
    expect(api.requestsTo("GET", "/api/services/nova.svc.payment/context")).toHaveLength(0);
  });

  it("drops stale retrieval values after a reload or a rerender", async () => {
    const api = installMockApi();
    const second = clone<RetrievalBundle>(fixtures.retrieval_101);
    second.memory_context.items = second.memory_context.items.slice(1);
    second.memory_context.items[0]!.score = 0.5111;
    second.memory_context.excluded = { draft: 1, superseded: 2 };
    const third = clone<RetrievalBundle>(fixtures.retrieval_101);
    third.memory_context.items = [];
    third.knowledge_context.items = third.knowledge_context.items.slice(2);
    api.on("GET", RETRIEVAL, [{ body: fixtures.retrieval_101 }, { body: second }, { body: third }]);
    const user = userEvent.setup();
    const { rerender } = render(tab("demo-viewer"));

    expect(await screen.findByText("score 0.7784")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh retrieval" }));
    expect(await screen.findByText("score 0.5111")).toBeInTheDocument();
    expect(screen.queryByText("score 0.7784")).not.toBeInTheDocument();
    expect(screen.queryByText("score 0.7099")).not.toBeInTheDocument();
    expect(screen.getByText(/2 superseded excluded/)).toBeInTheDocument();

    rerender(tab("payments-lead"));
    expect(await screen.findByText("No verified memories ranked for this incident")).toBeInTheDocument();
    expect(screen.queryByText("score 0.5111")).not.toBeInTheDocument();
    expect(screen.queryByText(/ADR-031 Payment rollbacks/, { selector: "p" })).not.toBeInTheDocument();
    expect(api.requestsTo("GET", RETRIEVAL).at(-1)?.user).toBe("payments-lead");
  });
});
