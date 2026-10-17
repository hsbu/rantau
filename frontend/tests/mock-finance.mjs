// Local transport test double for the finance routes. Never imported by application code.
import { createServer } from "node:http";

const calls = [];
const detail = {
  id: "obl_2026_demo_01", student_id: "stu_001", university_id: "uni_cn_01", currency: "CNY",
  amount_due_minor: 2000000, posted_minor: 0, balance_minor: 2000000,
  due_at: "2026-11-21T09:00:00Z", policy_id: "cn_demo_v1", state: "EXCEPTION",
  provider_status: { payment_id: "transfer_001", transfer_status: "DELIVERED" },
  posting_deadline_at: null, active_case_id: null, shortfall_minor: 0, topup_permitted: false,
};
const payment = {
  payment_id: "transfer_001", intent_id: "intent_001", provider_reference: "sim_ref_001",
  transfer_status: "DELIVERED", receipt_reference: "receipt_001", audit_event_id: "audit_001",
};

createServer(async (request, response) => {
  response.setHeader("Content-Type", "application/json");
  const url = request.url ?? "";
  if (url === "/health") return response.end("{}");
  if (url === "/__calls") return response.end(JSON.stringify(calls));
  const signedIn = (request.headers.cookie ?? "").includes("session=ok");
  const admin = (request.headers.cookie ?? "").includes("admin=ok");
  if (request.method === "POST") {
    let text = "";
    for await (const chunk of request) text += chunk;
    calls.push({ url, origin: request.headers.origin, body: text });
  }
  if (url.startsWith("/api/v1/demo/")) {
    if (!admin) { response.statusCode = 404; return response.end(JSON.stringify({ detail: "Resource unavailable" })); }
    if (url === "/api/v1/demo/scenarios") return response.end(JSON.stringify([{ id: "tuition_happy_path", description: "Happy path" }]));
    if (url === "/api/v1/demo/audit") return response.end(JSON.stringify([{
      audit_event_id: "audit_9", run_no: 1, action: "PAYMENT_DEBITED", resource_id: "transfer_001",
      decision: "ALLOW", reason_code: null, created_at: "2026-10-17T09:00:00Z",
    }]));
    response.statusCode = url.endsWith("/reset") ? 200 : 204;
    return response.end(url.endsWith("/reset") ? JSON.stringify({ scenario_id: "tuition_happy_path", run_no: 2 }) : "");
  }
  if (!signedIn) { response.statusCode = 401; return response.end("{}"); }
  if (url === "/api/v1/tuition/obligations") return response.end(JSON.stringify([detail]));
  if (url === "/api/v1/transfers/transfer_001") return response.end(JSON.stringify(payment));
  if (url.endsWith("/recheck")) return response.end(JSON.stringify(detail));
  if (url === "/api/v1/reconciliations") {
    response.statusCode = 201;
    return response.end(JSON.stringify({ case_id: "case_001", status: "READY", evidence_missing: [] }));
  }
  response.statusCode = 404;
  response.end("{}");
}).listen(8102, "127.0.0.1");
