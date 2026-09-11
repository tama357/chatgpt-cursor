const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const CHROME =
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const ROOT = path.resolve(__dirname, "..");
const SHOT_DIR = path.join(ROOT, "screenshots");
const RAW_DIR = path.join(ROOT, "_raw");

const VIDEOS = [
  { id: "P8z-8GQ-9P4", slug: "01_hai", duration: 69 },
  { id: "Is2l0WeCwSI", slug: "02_haregasuki", duration: 68 },
  { id: "YKvmjMleB8U", slug: "03_kami", duration: 58 },
  { id: "-hRRVIE4ZZc", slug: "04_himitsu", duration: 59 },
  { id: "BOhOYs2EUkQ", slug: "05_sannin", duration: 55 },
];

function timesFor(duration) {
  const times = [];
  for (let t = 0; t <= 5.0 + 1e-9; t += 0.2) times.push(Number(t.toFixed(2)));
  for (let t = 5.5; t < duration; t += 1.0) times.push(Number(t.toFixed(2)));
  times.push(Number(duration.toFixed(2)));
  return [...new Set(times)].sort((a, b) => a - b);
}

function pad(t) {
  return String(t.toFixed(2)).replace(".", "p").padStart(6, "0");
}

async function dismissConsent(page) {
  const selectors = [
    'button[aria-label="Accept all"]',
    'button[aria-label="すべて同意"]',
    'button[aria-label="Agree to the use of cookies and other data for the purposes described"]',
    "button#accept-button",
    "form[action*='consent'] button",
  ];
  for (const sel of selectors) {
    const el = await page.$(sel);
    if (el) {
      await el.click().catch(() => {});
      await new Promise((r) => setTimeout(r, 800));
    }
  }
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll("button")];
    const hit = buttons.find((b) =>
      /同意|Accept all|I agree|Agree/i.test((b.innerText || "").trim())
    );
    if (hit) hit.click();
  });
}

async function waitForVideo(page) {
  await page.waitForFunction(
    () => {
      const v = document.querySelector("video.html5-main-video, video");
      return v && v.readyState >= 2 && v.videoWidth > 0;
    },
    { timeout: 45000 }
  );
}

async function seek(page, t) {
  await page.evaluate((time) => {
    const v = document.querySelector("video.html5-main-video, video");
    if (!v) throw new Error("no video");
    v.muted = true;
    v.pause();
    v.currentTime = time;
  }, t);
  await page.waitForFunction(
    (time) => {
      const v = document.querySelector("video.html5-main-video, video");
      if (!v) return false;
      const okTime = Math.abs(v.currentTime - time) < 0.12 || v.ended;
      return okTime && v.readyState >= 2;
    },
    { timeout: 15000 },
    t
  );
  await new Promise((r) => setTimeout(r, 180));
}

async function captureOne(browser, video) {
  const dir = path.join(SHOT_DIR, video.slug);
  fs.mkdirSync(dir, { recursive: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 540, height: 960, deviceScaleFactor: 2 });
  await page.setUserAgent(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
  );
  const url = `https://www.youtube.com/shorts/${video.id}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await dismissConsent(page);
  await new Promise((r) => setTimeout(r, 1500));
  try {
    await waitForVideo(page);
  } catch (e) {
    await page.screenshot({
      path: path.join(dir, "_page_fail.png"),
      fullPage: false,
    });
    const html = await page.content();
    fs.writeFileSync(path.join(RAW_DIR, `${video.id}.page.html`), html);
    throw e;
  }

  const meta = await page.evaluate(() => {
    const v = document.querySelector("video.html5-main-video, video");
    const rect = v.getBoundingClientRect();
    const title =
      document.querySelector("h2 yt-formatted-string, h1 yt-formatted-string, #title")
        ?.innerText || document.title;
    const channel =
      document.querySelector("ytd-channel-name, #channel-name, yt-formatted-string#text")
        ?.innerText || "";
    return {
      duration: v.duration,
      videoWidth: v.videoWidth,
      videoHeight: v.videoHeight,
      element: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
      title,
      channel,
      pageTitle: document.title,
      url: location.href,
    };
  });
  fs.writeFileSync(
    path.join(RAW_DIR, `${video.id}.meta.json`),
    JSON.stringify(meta, null, 2),
    "utf8"
  );

  const times = timesFor(Math.min(video.duration, Math.floor(meta.duration || video.duration)));
  const log = [];
  for (const t of times) {
    try {
      await seek(page, t);
      const handle = await page.$("video.html5-main-video, video");
      if (!handle) throw new Error("video handle missing");
      const file = path.join(dir, `t${pad(t)}.png`);
      await handle.screenshot({ path: file });
      const info = await page.evaluate(() => {
        const v = document.querySelector("video.html5-main-video, video");
        return {
          currentTime: v.currentTime,
          paused: v.paused,
          videoWidth: v.videoWidth,
          videoHeight: v.videoHeight,
        };
      });
      log.push({ t, file: path.basename(file), ...info, ok: true });
      process.stdout.write(`  ${video.slug} ${t.toFixed(2)}s ok\n`);
    } catch (err) {
      log.push({ t, ok: false, error: String(err) });
      process.stdout.write(`  ${video.slug} ${t.toFixed(2)}s FAIL ${err}\n`);
    }
  }
  fs.writeFileSync(
    path.join(RAW_DIR, `${video.id}.capture.json`),
    JSON.stringify({ video, meta, log }, null, 2),
    "utf8"
  );
  await page.close();
  return log.filter((x) => x.ok).length;
}

(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.mkdirSync(RAW_DIR, { recursive: true });
  const only = process.argv[2];
  const list = only ? VIDEOS.filter((v) => v.slug === only || v.id === only) : VIDEOS;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: [
      "--autoplay-policy=no-user-gesture-required",
      "--mute-audio",
      "--no-sandbox",
      "--disable-blink-features=AutomationControlled",
      "--window-size=540,960",
    ],
  });
  const summary = [];
  for (const video of list) {
    process.stdout.write(`START ${video.slug}\n`);
    try {
      const n = await captureOne(browser, video);
      summary.push({ id: video.id, slug: video.slug, shots: n, ok: true });
    } catch (err) {
      summary.push({ id: video.id, slug: video.slug, ok: false, error: String(err) });
      process.stdout.write(`FAIL ${video.slug} ${err}\n`);
    }
  }
  fs.writeFileSync(
    path.join(RAW_DIR, "capture-summary.json"),
    JSON.stringify(summary, null, 2),
    "utf8"
  );
  await browser.close();
  console.log(JSON.stringify(summary, null, 2));
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
