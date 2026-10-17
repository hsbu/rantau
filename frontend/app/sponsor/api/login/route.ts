import { relay } from "../relay";

export function POST(request: Request) {
  return relay(request, "login");
}
