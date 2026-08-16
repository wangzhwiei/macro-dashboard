import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const projectRoot = resolve(import.meta.dirname, "..");
const distRoot = resolve(projectRoot, "dist");

await mkdir(resolve(distRoot, "server"), { recursive: true });
await mkdir(resolve(distRoot, ".openai"), { recursive: true });

await copyFile(
  resolve(projectRoot, "worker", "static-site.js"),
  resolve(distRoot, "server", "index.js"),
);
await copyFile(
  resolve(projectRoot, ".openai", "hosting.json"),
  resolve(distRoot, ".openai", "hosting.json"),
);
