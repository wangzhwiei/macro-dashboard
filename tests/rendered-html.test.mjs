import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: {
        fetch: async (request) => {
          const pathname = new URL(request.url).pathname;
          if (pathname === "/data/dashboard.json") {
            return new Response(
              await readFile(
                new URL("../public/data/dashboard.json", import.meta.url),
              ),
              { headers: { "content-type": "application/json" } },
            );
          }
          return new Response("Not found", { status: 404 });
        },
      },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the macro dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>宏观脉搏 · 高频观测<\/title>/i);
  assert.match(html, /正在整理今日宏观信号/);
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /react-loading-skeleton/);
});

test("ships generated dashboard data and removes starter preview", async () => {
  const dashboard = JSON.parse(
    await readFile(new URL("../public/data/dashboard.json", import.meta.url)),
  );
  assert.equal(dashboard.categories.length, 9);
  assert.ok(dashboard.indicators.length >= 100);
  assert.ok(dashboard.indicators.some((indicator) => !indicator.core));
  assert.ok(
    dashboard.indicators.every(
      (indicator) =>
        Array.isArray(indicator.series) && indicator.series.length > 10,
    ),
  );
  assert.ok(dashboard.overall.breadthDetail.total === 9);
  assert.ok(dashboard.dates.length >= 52);
  assert.equal(
    dashboard.dates.length,
    dashboard.categories[0].weeklyScores.length,
  );
  assert.ok(
    dashboard.indicators.every(
      (indicator) =>
        indicator.methodology?.formula &&
        indicator.methodology?.steps?.length &&
        indicator.methodology?.components?.length,
    ),
  );
  const metro = dashboard.indicators.find(
    (indicator) => indicator.id === "metro_composite",
  );
  assert.match(metro.methodology.formula, /MA7/);
  assert.equal(metro.methodology.components.length, 2);
  await assert.rejects(
    access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)),
  );
});
