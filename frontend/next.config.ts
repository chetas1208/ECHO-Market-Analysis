import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { NextConfig } from "next";

/**
 * NEXT_PUBLIC_API_URL is defined in the repo-root .env (one level above this
 * package). Read just that one key from ../.env when it is not already set in
 * the process environment, so `pnpm dev` works from frontend/ with or without
 * the root file. Falls back to http://localhost:8100 in lib/api.ts.
 */
function readRootEnv(key: string): string | undefined {
  // Next runs with cwd = frontend/ (pnpm/npm scripts), so the root file is one level up.
  const file = resolve(process.cwd(), "..", ".env");
  if (!existsSync(file)) return undefined;
  for (const raw of readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0 || line.slice(0, eq).trim() !== key) continue;
    return line.slice(eq + 1).trim().replace(/^(['"])(.*)\1$/, "$2") || undefined;
  }
  return undefined;
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? readRootEnv("NEXT_PUBLIC_API_URL");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  agentRules: false,
  devIndicators: false,
  poweredByHeader: false,
  allowedDevOrigins: ["127.0.0.1"],
  env: apiUrl ? { NEXT_PUBLIC_API_URL: apiUrl } : {},
};

export default nextConfig;
