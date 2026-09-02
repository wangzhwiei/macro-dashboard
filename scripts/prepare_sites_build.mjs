import { copyFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { extname, relative, resolve, sep } from "node:path";

const projectRoot = resolve(import.meta.dirname, "..");
const distRoot = resolve(projectRoot, "dist");

await mkdir(resolve(distRoot, "server"), { recursive: true });
await mkdir(resolve(distRoot, ".openai"), { recursive: true });

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
};
const textExtensions = new Set([".css", ".html", ".js", ".json", ".svg", ".txt"]);

async function collectFiles(directory) {
  const output = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (directory === distRoot && [".openai", "server"].includes(entry.name)) continue;
    const fullPath = resolve(directory, entry.name);
    if (entry.isDirectory()) output.push(...(await collectFiles(fullPath)));
    else output.push(fullPath);
  }
  return output;
}

const embeddedFiles = [];
for (const fullPath of await collectFiles(distRoot)) {
  const extension = extname(fullPath).toLowerCase();
  const body = await readFile(fullPath);
  embeddedFiles.push([
    `/${relative(distRoot, fullPath).split(sep).join("/")}`,
    [
      mimeTypes[extension] ?? "application/octet-stream",
      textExtensions.has(extension) ? "text" : "base64",
      textExtensions.has(extension) ? body.toString("utf8") : body.toString("base64"),
    ],
  ]);
}

const workerSource = `const FILES = new Map(${JSON.stringify(embeddedFiles)});

function responseFor(pathname, method) {
  const entry = FILES.get(pathname);
  if (!entry) return null;
  const [contentType, encoding, payload] = entry;
  const headers = new Headers({ "Content-Type": contentType });
  if (pathname.startsWith("/data/") || pathname === "/index.html") {
    headers.set("Cache-Control", "no-store");
  } else if (pathname.startsWith("/assets/")) {
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
  }
  if (method === "HEAD") return new Response(null, { status: 200, headers });
  const body = encoding === "base64"
    ? Uint8Array.from(atob(payload), (character) => character.charCodeAt(0))
    : payload;
  return new Response(body, { status: 200, headers });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const pathname = decodeURIComponent(url.pathname);
    const direct = responseFor(pathname === "/" ? "/index.html" : pathname, request.method);
    if (direct) return direct;
    if (!pathname.includes(".")) {
      const fallback = responseFor("/index.html", request.method);
      if (fallback) return fallback;
    }
    return new Response("Not found", { status: 404 });
  },
};
`;
await writeFile(resolve(distRoot, "server", "index.js"), workerSource, "utf8");
await copyFile(
  resolve(projectRoot, ".openai", "hosting.json"),
  resolve(distRoot, ".openai", "hosting.json"),
);
