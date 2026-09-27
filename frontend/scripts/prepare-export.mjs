import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Static export cannot include route handlers. Vercel builds keep the proxy.
if (process.env.NEXT_OUTPUT !== "export") {
  process.exit(0);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/app/api");
fs.rmSync(root, { recursive: true, force: true });
