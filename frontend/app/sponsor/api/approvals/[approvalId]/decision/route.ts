import { relay } from "../../../relay";

export async function POST(
  request: Request,
  context: { params: Promise<{ approvalId: string }> },
) {
  const { approvalId } = await context.params;
  return relay(request, { kind: "decision", approvalId });
}
