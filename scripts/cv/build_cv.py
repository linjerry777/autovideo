#!/usr/bin/env python3
"""
Build Jerry Lin's CV PDF (English) for Japan/Singapore/international applications.

Reads canonical resume data from `Intro/lib/constants.ts` (single source of truth)
+ adds emphasis on the AI/AutoVideo work the Intro page underplays.

Output: data/output/cv/jerry-lin-cv-en.pdf
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = REPO_ROOT / "data" / "output" / "cv"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "jerry-lin-cv-en.pdf"

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Jerry Lin — Full-Stack Engineer</title>
<style>
  @page { size: A4; margin: 14mm 16mm; }
  * { box-sizing: border-box; }
  body {
    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #1f2937;
    margin: 0;
  }
  h1 { font-size: 22pt; margin: 0 0 2pt; letter-spacing: -0.01em; color: #0f172a; }
  .role { font-size: 11pt; color: #475569; margin: 0 0 8pt; font-weight: 500; }
  .contact { font-size: 9.2pt; color: #475569; margin: 0 0 14pt; }
  .contact a { color: #475569; text-decoration: none; }
  .contact .sep { color: #cbd5e1; margin: 0 6pt; }

  h2 {
    font-size: 11pt;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #f97316;
    border-bottom: 1px solid #fed7aa;
    padding-bottom: 3pt;
    margin: 14pt 0 8pt;
  }

  .summary { color: #334155; margin: 0 0 4pt; }

  .item { margin: 0 0 10pt; page-break-inside: avoid; }
  .item-head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin: 0 0 2pt;
  }
  .item-title { font-weight: 600; color: #0f172a; }
  .item-company { color: #64748b; font-size: 9.5pt; }
  .item-meta { color: #64748b; font-size: 9pt; white-space: nowrap; margin-left: 8pt; }
  .item ul { margin: 2pt 0 4pt 14pt; padding: 0; }
  .item li { margin: 1pt 0; color: #334155; }
  .stack {
    font-size: 8.8pt; color: #64748b;
    background: #f8fafc;
    padding: 2pt 6pt;
    border-radius: 3px;
    display: inline-block;
    margin-top: 2pt;
  }

  /* Projects */
  .proj-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6pt 14pt; }
  .proj-grid .item { margin-bottom: 6pt; }
  .proj-name { font-weight: 600; color: #0f172a; }
  .proj-desc { color: #475569; font-size: 9.5pt; margin: 1pt 0 2pt; }

  /* Skills compact */
  .skills-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2pt 14pt; font-size: 9.5pt; }
  .skills-grid .row { color: #334155; }
  .skills-grid .label { font-weight: 600; color: #0f172a; min-width: 96pt; display: inline-block; }

  /* Print tweaks */
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
</head>
<body>

<h1>Jerry Lin <span style="color:#94a3b8; font-weight:500;">林帛賢</span></h1>
<p class="role">Full-Stack Engineer · AI Integration · Next.js / TypeScript / Python</p>
<div class="contact">
  Taoyuan, Taiwan
  <span class="sep">·</span>
  <a href="mailto:g9898152@gmail.com">g9898152@gmail.com</a>
  <span class="sep">·</span>
  +886 903-512-453
  <span class="sep">·</span>
  <a href="https://github.com/linjerry777">github.com/linjerry777</a>
  <span class="sep">·</span>
  <a href="https://intro-blond-one.vercel.app/">intro-blond-one.vercel.app</a>
</div>

<h2>Summary</h2>
<p class="summary">
  Full-stack engineer with 3 years of professional experience and 5+ shipped production AI side
  products. Day job: TSMC IoT systems at Wistron Software. Solo: Next.js + Supabase + Stripe SaaS,
  Python AI pipelines (FastAPI + ffmpeg + GPT-4o), and Claude/OpenAI integration end-to-end.
  Open to relocation (Japan / Singapore) or remote roles. Bilingual ZH/EN; learning Japanese.
</p>

<h2>Experience</h2>

<div class="item">
  <div class="item-head">
    <div>
      <span class="item-title">Software Engineer</span> ·
      <span class="item-company">Wistron Software (緯創軟體)</span>
    </div>
    <div class="item-meta">Aug 2025 – Present · Hsinchu, TW</div>
  </div>
  <ul>
    <li>Maintain and optimise TSMC IoT data pipelines: SQL query tuning, schema redesign, and observability tooling.</li>
    <li>Operate a Vector / Grafana / Prometheus stack for system metrics, logs, and analytics dashboards.</li>
  </ul>
  <span class="stack">Golang · PHP · MySQL · Docker · Vector · Grafana · Prometheus</span>
</div>

<div class="item">
  <div class="item-head">
    <div>
      <span class="item-title">IT / Backend Engineer</span> ·
      <span class="item-company">Yongjiajie Technology (永佳捷科技)</span>
    </div>
    <div class="item-meta">Aug 2024 – Present · Taoyuan, TW</div>
  </div>
  <ul>
    <li>Resolved 140 / 500 internal tickets (28%); shipped 28 / 143 successful projects independently.</li>
    <li>Integrated ERP &amp; financial APIs to auto-sync data — reduced manual workload by 50%.</li>
    <li>Built budget / purchase-order modules with Laravel Eloquent and SQL query optimisation (~30% faster reports).</li>
    <li>Rolled out Jenkins + Docker CI/CD for Laravel APIs — deployment efficiency up ~50%.</li>
  </ul>
  <span class="stack">Laravel · PHP · MySQL · Jenkins · Docker · Alpine.js · Datatables.js</span>
</div>

<div class="item">
  <div class="item-head">
    <div>
      <span class="item-title">IT / Frontend Engineer</span> ·
      <span class="item-company">Tai Ye Technology (太業科技)</span>
    </div>
    <div class="item-meta">Mar 2023 – Jul 2024 · Yangmei, TW</div>
  </div>
  <ul>
    <li>Built CRUD admin interfaces with jQuery + Datatables.js; financial dashboards with Chart.js.</li>
    <li>Implemented automated notification flows for project completion / event triggers.</li>
    <li>Developed features for a WordPress B2B platform; daily ERP maintenance &amp; bug fixes.</li>
  </ul>
  <span class="stack">PHP · Laravel · MySQL · MSSQL · jQuery · Vue.js · WordPress</span>
</div>

<h2>Featured Projects</h2>

<div class="proj-grid">

  <div class="item">
    <div class="proj-name">ai_lesson — Live Subscription Platform</div>
    <div class="proj-desc">Next.js 14 + Supabase Auth + Stripe Checkout course platform; ships at NT$2,640.</div>
    <span class="stack">Next.js 14 · TS · Supabase · Stripe · Google OAuth</span>
  </div>

  <div class="item">
    <div class="proj-name">AutoVideo — Python AI Short-Video Pipeline</div>
    <div class="proj-desc">FastAPI orchestrating GPT-4o + Seedance + ffmpeg, auto-publishes to TikTok / YT / IG / FB / Threads / LinkedIn.</div>
    <span class="stack">Python · FastAPI · APScheduler · ffmpeg · GPT-4o · Playwright</span>
  </div>

  <div class="item">
    <div class="proj-name">chat-mvp — AI Customer Support MVP</div>
    <div class="proj-desc">Next.js 16 + OpenAI chatbot with lead capture &amp; admin dashboard.</div>
    <span class="stack">Next.js 16 · TS · OpenAI · Supabase · Tailwind</span>
  </div>

  <div class="item">
    <div class="proj-name">open-carrusel — Claude-Driven Carousel Builder</div>
    <div class="proj-desc">Next.js 16 + Claude CLI subprocess + Puppeteer for IG carousel generation, scheduled publish, and ManyChat hub.</div>
    <span class="stack">Next.js 16 · TS · Claude CLI · Puppeteer</span>
  </div>

  <div class="item">
    <div class="proj-name">ai-wrapper — Multi-Model AI SaaS</div>
    <div class="proj-desc">Next.js 16 + Tailwind v4 + Groq Llama 3.3 / Mixtral; 6 free AI tools + streaming chat + structured-output demo.</div>
    <span class="stack">Next.js 16 · TS · Tailwind v4 · Groq · Llama 3.3</span>
  </div>

  <div class="item">
    <div class="proj-name">LINE Checkin — Production Attendance System</div>
    <div class="proj-desc">LINE LIFF + Bot + Google Sheets backend with GPS validation, payroll auto-calc, and admin console.</div>
    <span class="stack">Node.js · LINE LIFF · LINE Messaging API · Google Sheets API</span>
  </div>

  <div class="item">
    <div class="proj-name">mortgage-funnel — US Mortgage Lead Funnel</div>
    <div class="proj-desc">Next.js 16 multi-step lead-gen funnel for FHA / VA / DSCR loans with API capture + thank-you flows.</div>
    <span class="stack">Next.js 16 · TS · Tailwind</span>
  </div>

  <div class="item">
    <div class="proj-name">upwork-scout — AI Job Discovery CLI</div>
    <div class="proj-desc">Python CLI with Chrome bridge + Claude API ranking + auto-generated cover letters; multi-platform.</div>
    <span class="stack">Python · Claude API · Playwright</span>
  </div>

</div>

<h2>Technical Stack</h2>

<div class="skills-grid">
  <div class="row"><span class="label">Languages</span> TypeScript · JavaScript · Python · PHP · Go · SQL</div>
  <div class="row"><span class="label">Frontend</span> Next.js 14/16 · React · Vue 3 · Tailwind CSS · shadcn/ui</div>
  <div class="row"><span class="label">Backend</span> Node.js · FastAPI · Laravel · Express · NestJS (familiar)</div>
  <div class="row"><span class="label">Database</span> PostgreSQL · MySQL · MSSQL · Supabase · Redis</div>
  <div class="row"><span class="label">AI / LLM</span> Claude API · OpenAI · Groq · Llama 3.3 · GPT-4o · MCP</div>
  <div class="row"><span class="label">DevOps</span> Vercel · Docker · Jenkins · Railway · Render · GitHub Actions</div>
  <div class="row"><span class="label">Payments / Auth</span> Stripe Checkout / Webhook · Supabase Auth · Google OAuth</div>
  <div class="row"><span class="label">Other</span> Playwright · Puppeteer · ffmpeg · APScheduler · LINE LIFF / Bot</div>
</div>

<h2>Education</h2>
<div class="item">
  <div class="item-head">
    <div>
      <span class="item-title">B.S. Computer Science &amp; Information Engineering</span> ·
      <span class="item-company">National Chin-Yi University of Technology</span>
    </div>
    <div class="item-meta">Sep 2016 – Jun 2020 · Taichung, TW</div>
  </div>
</div>

<h2>Languages</h2>
<div class="skills-grid">
  <div class="row"><span class="label">Mandarin Chinese</span> Native</div>
  <div class="row"><span class="label">English</span> Business level (read/write/speak)</div>
  <div class="row"><span class="label">Japanese</span> Beginner (learning)</div>
</div>

</body>
</html>
"""

print("Rendering CV PDF…")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content(HTML, wait_until="networkidle")
    page.emulate_media(media="print")
    page.pdf(
        path=str(OUT_PATH),
        format="A4",
        print_background=True,
        margin={"top": "14mm", "right": "16mm", "bottom": "14mm", "left": "16mm"},
        prefer_css_page_size=True,
    )
    browser.close()

size = OUT_PATH.stat().st_size
print(f"OK → {OUT_PATH} ({size:,} bytes)")
