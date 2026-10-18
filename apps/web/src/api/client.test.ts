import { describe, expect, it } from "vitest";
import { errorEnvelope, fixtures, installMockApi } from "../test/mockApi";
import { ApiError, createClient } from "./client";

describe("api client", () => {
  it("sends the X-Demo-User header", async () => {
    const api = installMockApi();
    const client = createClient(() => "demo-responder");
    const list = await client.listIncidents({ limit: 10 });
    expect(list.items.map((i) => i.key)).toEqual(["INC-101", "INC-092"]);
    expect(api.requests[0]?.user).toBe("demo-responder");
    expect(api.requests[0]?.query.get("limit")).toBe("10");
  });

  it("parses the error envelope into ApiError", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents/nova.inc.999", { status: 404, body: fixtures.error_404 });
    const client = createClient(() => "demo-viewer");
    const err = await client.getIncident("nova.inc.999").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(404);
    expect(apiErr.code).toBe("not_found");
    expect(apiErr.message).toBe("incident nova.inc.999 not found");
    expect(apiErr.requestId).toBe("7ab809b6c2234730850e31a52ca283ff");
  });

  it("keeps envelope details", async () => {
    const api = installMockApi();
    api.on("POST", "/api/investigations", {
      status: 409,
      body: errorEnvelope("investigation_in_progress", "active in another mode", "req-1234abcd", { mode: "simulation" }),
    });
    const client = createClient(() => "demo-responder");
    const err = (await client
      .createInvestigation({ incident_id: "nova.inc.101", mode: "recommendation_only" })
      .catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(409);
    expect(err.code).toBe("investigation_in_progress");
    expect(err.details).toEqual({ mode: "simulation" });
  });

  it("maps a network failure to ApiError network_error", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents", { networkError: true });
    const client = createClient(() => "demo-viewer");
    const err = (await client.listIncidents().catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("network_error");
    expect(err.status).toBe(0);
  });

  it("maps a non-envelope error body to http_<status>", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents", { status: 502, body: "Bad gateway" });
    const err = (await createClient(() => "demo-viewer").listIncidents().catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("http_502");
    expect(err.status).toBe(502);
  });

  it("createInvestigation returns created=true for 201 and false for 200", async () => {
    const api = installMockApi();
    api.on("POST", "/api/investigations", [
      { status: 201, body: fixtures.investigation_queued },
      { status: 200, body: fixtures.investigation_queued },
    ]);
    const client = createClient(() => "demo-responder");
    const first = await client.createInvestigation({ incident_id: "nova.inc.101", mode: "recommendation_only" });
    const second = await client.createInvestigation({ incident_id: "nova.inc.101", mode: "recommendation_only" });
    expect(first.created).toBe(true);
    expect(second.created).toBe(false);
    expect(second.investigation.id).toBe("nova.ses.01example");
    const posts = api.requestsTo("POST", "/api/investigations");
    expect(posts[0]?.body).toEqual({ incident_id: "nova.inc.101", mode: "recommendation_only" });
    expect(posts[0]?.headers["content-type"]).toBe("application/json");
  });

  it("rejects with an AbortError (not ApiError) when aborted", async () => {
    const api = installMockApi();
    api.on("GET", "/api/incidents", { delayMs: 50, body: fixtures.incidents });
    const controller = new AbortController();
    const p = createClient(() => "demo-viewer").listIncidents({}, controller.signal);
    controller.abort();
    const err = await p.catch((e: unknown) => e);
    expect(err).not.toBeInstanceOf(ApiError);
    expect((err as Error).name).toBe("AbortError");
  });

  it("getReadiness resolves ready=false on 503", async () => {
    const api = installMockApi();
    api.on("GET", "/readyz", { status: 503, body: { status: "unavailable", checks: { falkordb: false, postgres: true } } });
    const r = await createClient(() => "demo-viewer").getReadiness();
    expect(r).toEqual({ ready: false, httpStatus: 503, body: { status: "unavailable", checks: { falkordb: false, postgres: true } } });
  });

  it("getRetrieval and getServiceContext hit the right paths", async () => {
    const api = installMockApi();
    const client = createClient(() => "payments-lead");
    const bundle = await client.getRetrieval("nova.inc.101");
    expect(bundle.steps.graph?.status).toBe("completed");
    await client.getServiceContext("nova.svc.payment", { depth: 2 });
    expect(api.requestsTo("GET", "/api/services/nova.svc.payment/context")[0]?.query.get("depth")).toBe("2");
  });
});
