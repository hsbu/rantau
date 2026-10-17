import { relay } from "../relay";

export function GET(request: Request) {
  return relay(request, "approvals");
}
