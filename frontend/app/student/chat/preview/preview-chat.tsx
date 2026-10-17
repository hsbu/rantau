"use client";

import { useMemo, useState } from "react";
import { ChatWorkspace } from "../chat-workspace";
import { fixtureTransport, scenarios } from "./fixtures";
import type { Scenario } from "./fixtures";
import styles from "../chat.module.css";

export function PreviewChat() {
  const [scenario, setScenario] = useState<Scenario>("tuition");
  const [revision, setRevision] = useState(0);
  const transport = useMemo(() => fixtureTransport(scenario), [scenario, revision]);
  return <ChatWorkspace key={`${scenario}-${revision}`} transport={transport} preview prompts={scenarios[scenario].prompts}>
    <div className={styles.previewControls}>
      <label htmlFor="sample-scenario">Sample scenario</label>
      <select id="sample-scenario" value={scenario} onChange={event => setScenario(event.target.value as Scenario)}>
        {Object.entries(scenarios).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}
      </select>
      <button type="button" onClick={() => setRevision(value => value + 1)}>Restart scenario ↺</button>
    </div>
  </ChatWorkspace>;
}
