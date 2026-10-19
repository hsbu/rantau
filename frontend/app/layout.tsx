import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rantau", description: "A simulated financial agent for students abroad.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><a className="skipLink" href="#main-content">Skip to main content</a>{children}</body></html>;
}
