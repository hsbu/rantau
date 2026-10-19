import type { AgentResponse, ChatTransport } from "./chat-types";
import { ChatError, parseAgentResponse } from "./chat-types";
import { actionSummary, parseDetailSnapshot } from "./detail-types";

export const connectedTransport: ChatTransport = {
  async send(body, signal) {
    let response: Response;
    try {
      response = await fetch("/student/chat/api", {
        method: "POST", credentials: "same-origin", cache: "no-store", signal,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
    } catch {
      throw new ChatError("uncertain");
    }
    if (response.status === 401 || response.status === 403) throw new ChatError("session");
    if (!response.ok) throw new ChatError(response.status === 503 ? "unavailable" : "uncertain");
    let result: AgentResponse;
    try {
      result = parseAgentResponse(await response.json());
    } catch {
      throw new ChatError("invalid");
    }
    try {
      const params = new URLSearchParams({ conversation_id: body.conversation_id!, run_id: result.run_id });
      const details = await fetch(`/student/chat/api/details?${params}`, { method: "GET", credentials: "same-origin", cache: "no-store", signal });
      if (details.status === 401 || details.status === 403) throw new ChatError("session");
      if (!details.ok) return { response: result, detailsUnavailable: true };
      return { response: result, summary: actionSummary(parseDetailSnapshot(await details.json(), result.run_id)) };
    } catch (error) {
      if (error instanceof ChatError && error.kind === "session") throw error;
      return { response: result, detailsUnavailable: true };
    }
  },
};
