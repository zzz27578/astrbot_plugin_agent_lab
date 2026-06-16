// webui 无头截图预览：内嵌静态服务器 + mock /api，渲染真实 app.js/style.css 并截图到 _preview/。
// 先跑 scripts/preview/setup_chromium.sh 准备好 /tmp/pw 里的 chromium。
// 用法：LD_LIBRARY_PATH=/tmp/pw/libs node scripts/preview/preview.js [route...]
//   route 省略=默认拍 workflow/integrations/canvas/monitor；也可传 workflow 等只拍指定页。
const { chromium } = require("/tmp/pw/node_modules/playwright-core");
const http = require("http");
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const REPO = path.resolve(HERE, "../..");
const WEBUI = path.join(REPO, "webui");
const OUT = path.join(REPO, "_preview");
const CHROME = "/tmp/pw/chromium/chrome-linux/chrome";
const mock = fs.readFileSync(path.join(HERE, "mockstate.json"), "utf8");
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

const routes = process.argv.slice(2);
const PLAN = routes.length ? routes.map((r) => [r, r]) : [
  ["workflow", "workflow"], ["integrations", "integrations"], ["canvas", "scheme"], ["monitor", "monitor"], ["memory", "memory"],
];

const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  if (url.startsWith("/api/")) {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(url.includes("/api/state") ? mock : JSON.stringify({ ok: true }));
  }
  const f = url === "/" ? "/index.html" : url;
  const fp = path.join(WEBUI, f);
  if (!fp.startsWith(WEBUI) || !fs.existsSync(fp)) { res.writeHead(404); return res.end("nf"); }
  res.writeHead(200, { "Content-Type": MIME[path.extname(fp)] || "text/plain" });
  fs.createReadStream(fp).pipe(res);
});

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  await new Promise((r) => server.listen(8099, "127.0.0.1", r));
  const browser = await chromium.launch({
    executablePath: CHROME, headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--force-color-profile=srgb"],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.route(/raw\.githubusercontent\.com|cdnjs|fonts\.googleapis|githubusercontent/, (r) => r.abort());
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("http://127.0.0.1:8099/index.html", { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  for (const [routeId, name] of PLAN) {
    try { await page.click(`[data-route="${routeId}"]`, { timeout: 3000 }); } catch (e) {}
    await page.waitForTimeout(700);
    if (routeId === "workflow") { await page.click('[data-action="auto-layout-workflow"]').catch(() => {}); await page.click('[data-action="workflow-focus-content"]').catch(() => {}); await page.waitForTimeout(500); }
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log("shot", name);
  }
  await browser.close();
  server.close();
  console.log("DONE. pageerrors:", errors.length);
  if (errors.length) console.log(errors.slice(0, 5).join("\n"));
})().catch((e) => { console.error("FAIL:", e.message); try { server.close(); } catch {} ; process.exit(1); });
