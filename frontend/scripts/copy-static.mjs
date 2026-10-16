// Next standalone servers need the static asset tree alongside the server bundle.
import { cpSync } from "node:fs";

cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
