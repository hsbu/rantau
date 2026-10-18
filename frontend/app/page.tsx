import type { components } from "../lib/api-contracts/generated";
import Link from "next/link";

// Compile-time consumer of the shared Python contract, not a hand-copied enum.
const intents: components["schemas"]["Intent"][] = [
  "ASK_POLICY", "TUITION", "ALLOWANCE", "TRACK", "RECOVER", "VERIFY_MESSAGE",
];

export default function Home() {
  return <main>
    <p className="eyebrow">Rantau / Development preview</p>
    <h1>A clearer path<br />from home to campus.</h1>
    <p className="description">A financial agent for students abroad and the people supporting them.</p>
    <p><Link href="/student/chat">Open student chat →</Link> · <Link href="/student/chat/preview">Explore the sample conversation →</Link> · <Link href="/sponsor">Sponsor approvals →</Link></p>
    <section aria-labelledby="status"><h2 id="status">Foundation in progress</h2>
      <p>All quotes, payments and university records in this project are simulated.
        The sponsor workspace is included; financial services are awaiting integration.</p>
      <p>No payment actions are available in this preview.</p>
      <ul>{intents.map(intent => <li key={intent}>{intent.replaceAll("_", " ").toLowerCase()}</li>)}</ul>
    </section>
  </main>;
}
