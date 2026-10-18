// Local transport test double. Never imported by application or container runtime.
import { createServer } from "node:http";

// Sponsor workspace fixtures; the relay validates every field strictly.
const TOKEN = "a".repeat(43);
const MALFORMED_TOKEN = "m".repeat(43);
const SET_COOKIE = `session=${TOKEN}; HttpOnly; Path=/; SameSite=Strict; Max-Age=3600`;
const CLEAR_COOKIE = 'session=""; HttpOnly; Path=/; SameSite=Strict; Max-Age=0';

const approval = {
  source_label: "Sponsor wallet •••• 4242",
  beneficiary_label: "Fictional university •••• DEMO",
  source_principal_minor: 20000000,
  fee_minor: 150000,
  approval_id: "apr_test_001",
  intent_id: "intent_test_001",
  intent_revision: 1,
  terms_hash: "b".repeat(64),
  state: "PENDING",
  expires_at: "2026-10-19T04:00:00+00:00",
  purpose: "TUITION",
  source_currency: "IDR",
  destination_currency: "CNY",
  source_total_minor: 20150000,
  destination_amount_minor: 890000,
  simulated: true,
};

const securityCase = {
  case_id: "case_test_001",
  resource_id: "intent_test_001",
  state: "OPEN",
  reason: "BENEFICIARY_CHANGE_REQUESTED",
  created_at: "2026-10-18T02:00:00+00:00",
  updated_at: "2026-10-18T02:05:00+00:00",
  audit_event_id: "audit_test_001",
};

const sessionSummary = { authenticated: true, role: "SPONSOR" };
let received;

function send(response, status, body, headers = {}) {
  response.writeHead(status, { "Content-Type": "application/json", ...headers });
  response.end(JSON.stringify(body));
}

function cookieToken(request) {
  const parts = (request.headers.cookie ?? "").split(";").map(part => part.trim());
  const match = parts.find(part => part.startsWith("session="));
  return match ? match.slice("session=".length) : "";
}

createServer(async (request, response) => {
  const url = request.url ?? "";
  if (url === "/health") return send(response, 200, {});
  if (url === "/inspect") return send(response, 200, received ?? {});

  if (url === "/api/v1/auth/login" && request.method === "POST") {
    let text = "";
    for await (const chunk of request) text += chunk;
    let body;
    try { body = JSON.parse(text); } catch { return send(response, 422, { code: "INVALID_REQUEST" }); }
    if (body.password === "wrong") return send(response, 401, { detail: "private diagnostic" });
    if (body.password === "throttled") return send(response, 429, { detail: "private diagnostic" });
    return send(response, 200, sessionSummary, { "Set-Cookie": SET_COOKIE });
  }

  const token = cookieToken(request);
  if (url === "/api/v1/auth/session" && request.method === "GET") {
    if (token !== TOKEN && token !== MALFORMED_TOKEN) {
      return send(response, 401, { detail: "private diagnostic must not reach browser" });
    }
    return send(response, 200, sessionSummary);
  }
  if (url === "/api/v1/auth/logout" && request.method === "POST") {
    return send(response, 204, {}, { "Set-Cookie": CLEAR_COOKIE });
  }
  if (url === "/api/v1/sponsor/approvals" && request.method === "GET") {
    if (token !== TOKEN && token !== MALFORMED_TOKEN) {
      return send(response, 401, { detail: "private diagnostic must not reach browser" });
    }
    return send(response, 200, [approval]);
  }
  if (url === "/api/v1/security-cases" && request.method === "GET") {
    if (token !== TOKEN && token !== MALFORMED_TOKEN) {
      return send(response, 401, { detail: "private diagnostic must not reach browser" });
    }
    // The malformed token models an untrusted backend payload the relay must refuse.
    if (token === MALFORMED_TOKEN) {
      return send(response, 200, { cases: [{ ...securityCase, state: "OPENED" }] });
    }
    return send(response, 200, { cases: [securityCase] });
  }

  if (url !== "/api/v1/agent/messages" || request.method !== "POST") {
    return send(response, 404, {});
  }
  let text = "";
  for await (const chunk of request) text += chunk;
  const body = JSON.parse(text);
  received = { body, cookie: request.headers.cookie, origin: request.headers.origin, actorHeader: request.headers["x-actor-id"], authorization: request.headers.authorization };
  if (body.message === "expired-session") {
    return send(response, 401, { detail: "private diagnostic must not reach browser" });
  }
  send(response, 200, {
    run_id: "run_test_001", message: "Scoped response from the test backend.", requested_action: "TUITION",
    tool_events: [], resources: [],
  });
}).listen(8101, "127.0.0.1");
