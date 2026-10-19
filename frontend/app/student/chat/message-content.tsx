import type { ReactNode } from "react";
import styles from "./chat.module.css";

function inline(text: string): ReactNode[] {
  const pieces = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https:\/\/[^)\s]+\))/g);
  return pieces.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\((https:\/\/[^)]+)\)$/.exec(part);
    if (link) {
      try {
        const url = new URL(link[2]);
        if (["iczu.zju.edu.cn", "cwcx.zju.edu.cn"].includes(url.hostname) && !url.username && !url.password
          && !url.port && !url.search && !url.hash) {
          return <a key={index} href={url.href} target="_blank" rel="noopener noreferrer">{link[1]}</a>;
        }
      } catch { /* Untrusted or unsupported links stay plain text. */ }
    }
    return part;
  });
}

// A deliberately small text format: paragraphs, lists, emphasis and commands.
// HTML is always React-escaped; no HTML parser or arbitrary links are supported.
export function MessageContent({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  for (let i = 0; i < lines.length;) {
    if (!lines[i].trim()) { i++; continue; }
    const ordered = /^\d+\.\s/.test(lines[i]);
    const bullet = /^-\s/.test(lines[i]);
    if (ordered || bullet) {
      const start = ordered ? Math.max(1, Math.min(100, Number(/^\d+/.exec(lines[i])?.[0]))) : 1;
      const marker = ordered ? /^\d+\.\s/ : /^-\s/;
      const items: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        if (marker.test(lines[i])) items.push(lines[i].replace(marker, ""));
        else if (/^(?:\d+\.|-)\s/.test(lines[i])) break;
        else items[items.length - 1] += "\n" + lines[i];
        i++;
      }
      const children = items.map((item, n) => <li key={n}>{inline(item)}</li>);
      blocks.push(ordered ? <ol key={blocks.length} start={start}>{children}</ol> : <ul key={blocks.length}>{children}</ul>);
    } else {
      const paragraph: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^(?:\d+\.|-)\s/.test(lines[i])) paragraph.push(lines[i++]);
      blocks.push(<p key={blocks.length}>{inline(paragraph.join("\n"))}</p>);
    }
  }
  return <div className={styles.reply}>{blocks}</div>;
}
