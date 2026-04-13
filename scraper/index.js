#!/usr/bin/env node
/**
 * AutoVideo Playwright Stealth Scraper
 * Usage: node index.js --pipe-dir "pipeline/2026-04-13/job_1"
 *
 * Reads:  {pipe-dir}/news.json
 * Writes: {pipe-dir}/screenshots/news_01.png
 *         {pipe-dir}/screenshots/news_01_img_0.jpg
 *         {pipe-dir}/screenshots/news_01_vid_0.mp4 (if downloadable)
 *         {pipe-dir}/screenshots/manifest.json
 */

const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

chromium.use(stealth());

// ── CLI args ──────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const pipeDirIdx = args.indexOf('--pipe-dir');
if (pipeDirIdx === -1 || !args[pipeDirIdx + 1]) {
  console.error('Usage: node index.js --pipe-dir <path>');
  process.exit(1);
}
const PIPE_DIR = path.resolve(args[pipeDirIdx + 1]);
const NEWS_FILE = path.join(PIPE_DIR, 'news.json');
const SHOTS_DIR = path.join(PIPE_DIR, 'screenshots');

if (!fs.existsSync(NEWS_FILE)) {
  console.error(`news.json not found: ${NEWS_FILE}`);
  process.exit(1);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http;
    const file = fs.createWriteStream(dest);
    const req = proto.get(url, { timeout: 15000 }, res => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        file.close();
        fs.unlink(dest, () => {});
        return downloadFile(res.headers.location, dest).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        file.close();
        fs.unlink(dest, () => {});
        return reject(new Error(`HTTP ${res.statusCode}`));
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    });
    req.on('error', err => {
      file.close();
      fs.unlink(dest, () => {});
      reject(err);
    });
  });
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function dismissPopups(page) {
  const selectors = [
    "button[id*='cookie']",
    "button[class*='close']",
    "button[aria-label*='Close']",
    "button[aria-label*='close']",
    "[class*='modal'] button",
    "[id*='popup'] button",
    "[class*='subscribe'] button[class*='close']",
  ];
  for (const sel of selectors) {
    try {
      const btn = await page.$(sel);
      if (btn && await btn.isVisible()) {
        await btn.click();
        await sleep(400);
        break;
      }
    } catch (_) {}
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });

  const newsData = JSON.parse(fs.readFileSync(NEWS_FILE, 'utf-8'));
  const items = newsData.items || [];

  console.log(`📰 處理 ${items.length} 篇新聞...`);

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 800 },
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
  });

  // 封鎖廣告 + 字體加速載入
  await context.route(/\.(woff2?|ttf|otf|gif|svg)(\?.*)?$/, r => r.abort());
  await context.route(/\/(ads|analytics|tracker|gtm)\//i, r => r.abort());

  const manifest = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const idx  = String(i + 1).padStart(2, '0');
    const url  = item.source_url || item.url || '';
    const title = item.title || item.hook || '';

    const entry = {
      index: i + 1,
      url,
      title,
      screenshot: null,
      images: [],
      videos: [],
      youtube_urls: [],
    };

    if (!url) {
      console.log(`[${idx}] 無 URL，跳過`);
      manifest.push(entry);
      continue;
    }

    const page = await context.newPage();
    try {
      console.log(`[${idx}] 訪問: ${url.slice(0, 80)}...`);
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await sleep(2500 + Math.random() * 1000);  // 模擬人類等待
      await dismissPopups(page);
      await page.evaluate(() => window.scrollTo(0, 0));

      // ── 截圖 ─────────────────────────────────────────────────────────────
      const shotPath = path.join(SHOTS_DIR, `news_${idx}.png`);
      await page.screenshot({ path: shotPath, fullPage: false });
      const shotSize = fs.statSync(shotPath).size;
      if (shotSize < 25000) {
        console.log(`  ⚠️  截圖疑似空白 (${Math.round(shotSize / 1024)}KB)，略過`);
        fs.unlinkSync(shotPath);
      } else {
        console.log(`  ✅ 截圖 ${Math.round(shotSize / 1024)}KB`);
        entry.screenshot = `screenshots/news_${idx}.png`;
      }

      // ── 抓頁面圖片（最多 3 張）──────────────────────────────────────────
      const imgSrcs = await page.evaluate(() => {
        const imgs = Array.from(document.querySelectorAll(
          'article img[src], .article img[src], main img[src], .content img[src], figure img[src]'
        ));
        return imgs
          .map(el => el.src)
          .filter(src =>
            src &&
            src.startsWith('http') &&
            !src.includes('icon') &&
            !src.includes('logo') &&
            !src.includes('avatar') &&
            !src.includes('1x1')
          )
          .slice(0, 3);
      });

      for (let j = 0; j < imgSrcs.length; j++) {
        const imgPath = path.join(SHOTS_DIR, `news_${idx}_img_${j}.jpg`);
        try {
          await downloadFile(imgSrcs[j], imgPath);
          const imgSize = fs.statSync(imgPath).size;
          if (imgSize > 10000) {
            entry.images.push(`screenshots/news_${idx}_img_${j}.jpg`);
            console.log(`  📷 圖片 ${j}: ${Math.round(imgSize / 1024)}KB`);
          } else {
            fs.unlinkSync(imgPath);
          }
        } catch (e) {
          console.log(`  ⚠️  圖片 ${j} 下載失敗: ${e.message}`);
          if (fs.existsSync(imgPath)) fs.unlinkSync(imgPath);
        }
      }

      // ── 抓嵌入影片 ───────────────────────────────────────────────────────
      const vidData = await page.evaluate(() => {
        const videoEls = Array.from(document.querySelectorAll('video[src], video source[src]'));
        const videoSrcs = videoEls.map(el => el.src).filter(Boolean).slice(0, 2);

        const iframes = Array.from(document.querySelectorAll('iframe[src]'));
        const ytUrls = iframes
          .map(el => el.src)
          .filter(src => src.includes('youtube.com') || src.includes('youtu.be'))
          .slice(0, 2);

        return { videoSrcs, ytUrls };
      });

      for (let j = 0; j < vidData.videoSrcs.length; j++) {
        const vidPath = path.join(SHOTS_DIR, `news_${idx}_vid_${j}.mp4`);
        try {
          await downloadFile(vidData.videoSrcs[j], vidPath);
          const vidSize = fs.statSync(vidPath).size;
          if (vidSize > 50000) {
            entry.videos.push(`screenshots/news_${idx}_vid_${j}.mp4`);
            console.log(`  🎬 影片 ${j}: ${Math.round(vidSize / 1024)}KB`);
          } else {
            fs.unlinkSync(vidPath);
          }
        } catch (e) {
          console.log(`  ⚠️  影片 ${j} 下載失敗: ${e.message}`);
          if (fs.existsSync(vidPath)) fs.unlinkSync(vidPath);
        }
      }

      entry.youtube_urls = vidData.ytUrls;
      if (vidData.ytUrls.length > 0) {
        console.log(`  🎥 YouTube: ${vidData.ytUrls.join(', ')}`);
      }

    } catch (e) {
      console.log(`  ❌ 失敗: ${e.message}`);
    } finally {
      await page.close();
    }

    manifest.push(entry);
  }

  await browser.close();

  const manifestPath = path.join(SHOTS_DIR, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
  console.log(`\n✅ 完成，manifest → ${manifestPath}`);
})();
