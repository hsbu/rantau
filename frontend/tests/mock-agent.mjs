// Local transport test double. Never imported by application or container runtime.
import { createServer } from "node:http";

let received;
createServer(async (request, response) => {
  response.setHeader("Content-Type", "application/json");
  if (request.url === "/health") return response.end("{}");
  if (request.url === "/inspect") return response.end(JSON.stringify(received));
  if (request.url !== "/api/v1/agent/messages" || request.method !== "POST") {
    response.statusCode = 404; return response.end("{}");
  }
  let text = "";
  for await (const chunk of request) text += chunk;
  const body = JSON.parse(text);
  received = { body, cookie: request.headers.cookie, origin: request.headers.origin, actorHeader: request.headers["x-actor-id"], authorization: request.headers.authorization };
  if (body.message === "expired-session") {
    response.statusCode = 401; return response.end(JSON.stringify({ detail: "private diagnostic must not reach browser" }));
  }
  response.end(JSON.stringify({
    run_id: "run_test_001", message: "Scoped response from the test backend.", requested_action: "TUITION",
    tool_events: [], resources: [],
  }));
}).listen(8101, "127.0.0.1");
