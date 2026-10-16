import { defineConfig, globalIgnores } from "eslint/config";
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default defineConfig([
  js.configs.recommended, ...tseslint.configs.recommended,
  globalIgnores([".next/**", "next-env.d.ts", "lib/api-contracts/generated.d.ts"]),
]);
