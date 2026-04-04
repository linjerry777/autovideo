# 🎬 AutoVideo Pipeline

## Python 全自動 AI 影片生成 × 多平台發布系統

### 架構設計文件 v1.0

---

## 技術棧總覽

| 項目       | 技術 / 服務                                |
| ---------- | ------------------------------------------ |
| 語言       | Python 3.11+                               |
| 影片生成   | Seedance API（via AI/ML API 或 Wavespeed） |
| 腳本生成   | OpenAI GPT-4o                              |
| 排程       | APScheduler                                |
| 後台管理   | FastAPI + SQLite                           |
| 影片後處理 | ffmpeg-python                              |
| 多平台發布 | Upload-Post.com API 或各平台官方 API       |

---

## 1. 系統概覽

AutoVideo Pipeline 是一套以 Python 驅動的本地自動化系統，目標是從零到多平台發布全程無人工介入。整個系統可在個人電腦（Windows / macOS / Linux）上運行，僅需網路連線呼叫外部 AI API 服務。

### 1.1 核心目標

- 每日自動產出 N 支短影片（TikTok / YouTube Shorts / Instagram Reels）
- 全程無人工介入：從 prompt 生成 → 影片生成 → 後製 → 發布
- 本地運行，資料完全自控，無授權費用限制
- 模組化設計，方便日後包裝成 SaaS 產品

### 1.2 系統流程總覽

```
① APScheduler 排程觸發（每日定時）
        │
        ▼
② OpenAI GPT-4o 生成影片腳本 + Prompt + 標題 + Hashtag
        │
        ▼
③ Seedance API 送出影片生成任務（非同步）
        │
        ▼
④ Polling 機制輪詢任務狀態，直到 completed
        │
        ▼
⑤ 下載影片到本地 output/ 目錄
        │
        ▼
⑥ ffmpeg 後處理：加字幕、浮水印、音訊正規化（可選）
        │
        ▼
⑦ Upload-Post API 同步推送到 TikTok / YouTube / Instagram
        │
        ▼
⑧ 寫入 SQLite 記錄任務結果、成本、狀態
        │
        ▼
⑨ FastAPI 後台可查看任務歷史與監控
```

---

## 2. 專案目錄結構

```
autovideo/
├── main.py                  # 程式進入點，啟動排程器與 FastAPI
├── config.py                # 所有 API Key 與設定集中管理
├── scheduler.py             # APScheduler 排程邏輯
│
├── modules/
│   ├── prompt_gen.py        # GPT-4o 生成腳本與 prompt
│   ├── video_gen.py         # Seedance API 呼叫與 polling
│   ├── video_process.py     # ffmpeg 後處理（字幕、浮水印）
│   ├── publisher.py         # 多平台發布邏輯
│   └── db.py                # SQLite 資料庫操作
│
├── api/
│   └── routes.py            # FastAPI 路由（管理後台）
│
├── output/                  # 生成的影片暫存
├── logs/                    # 執行 log
├── data/
│   └── pipeline.db          # SQLite 資料庫
│
├── requirements.txt
└── .env                     # 環境變數（API Keys）
```

---

## 3. 核心模組設計

### 3.1 config.py — 設定管理

所有 API Key 與可調整參數集中於此，透過 python-dotenv 從 .env 載入，避免硬編碼敏感資訊。

**環境變數：** `OPENAI_API_KEY`, `AIMLAPI_KEY`, `UPLOAD_POST_KEY`, `DB_PATH`, `OUTPUT_DIR`, `SCHEDULE_HOUR`, `DAILY_COUNT`

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
    aimlapi_key: str            # Seedance API key
    upload_post_key: str        # 多平台發布 API key
    seedance_model: str = 'bytedance/seedance-1-0-lite-t2v'
    daily_video_count: int = 3  # 每日產幾支
    schedule_hour: int = 8      # 幾點觸發（24h）
    output_dir: str = './output'
    db_path: str = './data/pipeline.db'

    class Config:
        env_file = '.env'

settings = Settings()
```

---

### 3.2 modules/prompt_gen.py — 腳本生成

呼叫 OpenAI GPT-4o，根據主題或隨機產生影片腳本，輸出結構化 JSON 供後續模組使用。

**輸出欄位：**

| 欄位              | 說明                       | 範例                              |
| ----------------- | -------------------------- | --------------------------------- |
| `topic`           | 影片主題                   | `"Tokyo street food at midnight"` |
| `seedance_prompt` | 給 Seedance 的詳細鏡頭描述 | `"Cinematic tracking shot of..."` |
| `title`           | 平台標題（含 emoji）       | `"🍜 Tokyo Midnight Eats"`        |
| `description`     | 說明文字                   | `"Exploring hidden gems..."`      |
| `hashtags`        | Hashtag 列表               | `"#Tokyo #FoodTok #Travel"`       |
| `duration`        | 影片秒數                   | `5` 或 `10`                       |
| `aspect_ratio`    | 長寬比                     | `"9:16"`（豎版）                  |

```python
# modules/prompt_gen.py
import openai, json
from config import settings

SYSTEM_PROMPT = '''你是一個專業的短影音內容策略師。
請根據給定主題，產生一個 JSON 物件，包含：
topic, seedance_prompt, title, description, hashtags,
duration (5或10), aspect_ratio ("9:16")'''

def generate_video_metadata(topic: str | None = None) -> dict:
    client = openai.OpenAI(api_key=settings.openai_api_key)
    user_msg = f'主題：{topic}' if topic else '請自由發揮一個熱門短影音主題'
    resp = client.chat.completions.create(
        model='gpt-4o',
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_msg}
        ]
    )
    return json.loads(resp.choices[0].message.content)
```

---

### 3.3 modules/video_gen.py — Seedance 影片生成

呼叫 Seedance API，送出生成任務後進入非同步 polling 等待完成，完成後下載影片至本地。

- **API 端點：** `POST https://api.aimlapi.com/v2/generate/video/bytedance/generation`
- **Polling 邏輯：** 每 10 秒查詢一次狀態（queued → generating → completed），5 秒影片約 40~60 秒完成

```python
# modules/video_gen.py
import requests, time, httpx
from pathlib import Path
from config import settings

BASE_URL = 'https://api.aimlapi.com/v2'

def create_video_task(prompt: str, duration: int = 5,
                      aspect_ratio: str = '9:16') -> str:
    """送出生成任務，回傳 generation_id"""
    resp = requests.post(
        f'{BASE_URL}/generate/video/bytedance/generation',
        headers={'Authorization': f'Bearer {settings.aimlapi_key}'},
        json={
            'model': settings.seedance_model,
            'prompt': prompt,
            'duration': str(duration),
            'aspect_ratio': aspect_ratio,
        }
    )
    resp.raise_for_status()
    return resp.json()['id']

def poll_until_done(gen_id: str, timeout: int = 600) -> str:
    """輪詢直到完成，回傳影片 URL"""
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(
            f'{BASE_URL}/generate/video/bytedance/generation',
            headers={'Authorization': f'Bearer {settings.aimlapi_key}'},
            params={'generation_id': gen_id}
        )
        data = r.json()
        status = data.get('status')
        if status == 'completed':
            return data['video']['url']
        elif status == 'failed':
            raise RuntimeError(f'Generation failed: {data}')
        time.sleep(10)  # 每 10 秒查一次
    raise TimeoutError('Video generation timed out')

def download_video(url: str, filename: str) -> Path:
    """下載影片到 output 目錄"""
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(exist_ok=True)
    path = out_dir / filename
    with httpx.stream('GET', url) as r:
        with open(path, 'wb') as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return path
```

---

### 3.4 modules/video_process.py — ffmpeg 後處理

使用 ffmpeg-python 對影片進行後製，包含浮水印、字幕疊加、音訊正規化等。此步驟為可選，可依需求啟用或跳過。

| 處理項目     | 說明                            | 預設     |
| ------------ | ------------------------------- | -------- |
| 浮水印       | 右下角疊加頻道 Logo 或文字      | 可選     |
| 字幕         | 硬字幕燒入（SRT → ASS）         | 可選     |
| 音訊正規化   | 調整音量到 -14 LUFS（平台標準） | 建議開啟 |
| 解析度標準化 | 確保輸出 1080x1920（9:16）      | 建議開啟 |
| 格式轉換     | 統一輸出 H.264 / AAC mp4        | 必要     |

```python
# modules/video_process.py
import ffmpeg
from pathlib import Path

def process_video(input_path: Path, output_path: Path,
                  watermark_text: str = None) -> Path:
    stream = ffmpeg.input(str(input_path))

    # 音訊正規化
    audio = stream.audio.filter('loudnorm', I=-14, TP=-2, LRA=11)

    # 視訊：確保 1080x1920
    video = stream.video.filter('scale', 1080, 1920,
                               force_original_aspect_ratio='decrease')

    # 浮水印（可選）
    if watermark_text:
        video = video.drawtext(
            text=watermark_text,
            fontsize=36, fontcolor='white@0.7',
            x='w-tw-20', y='h-th-20'
        )

    ffmpeg.output(
        video, audio, str(output_path),
        vcodec='libx264', acodec='aac', crf=23
    ).overwrite_output().run(quiet=True)

    return output_path
```

---

### 3.5 modules/publisher.py — 多平台發布

使用 Upload-Post.com 的統一 API，一次呼叫同時發布到多個平台，免去分別串接各平台 OAuth 的複雜度。

- **推薦：** Upload-Post.com — 一個 API Key，支援 TikTok / YouTube / Instagram / Facebook / LinkedIn / Threads / X
- **備選：** 各平台官方 API（TikTok Content Publishing API、YouTube Data API v3、Instagram Graph API）

```python
# modules/publisher.py
import requests
from pathlib import Path
from config import settings

UPLOAD_POST_URL = 'https://api.upload-post.com/api/upload'

def publish_video(
    video_path: Path,
    title: str,
    description: str,
    hashtags: str,
    platforms: list[str] = ['tiktok', 'youtube', 'instagram']
) -> dict:
    """上傳影片並發布到指定平台"""
    with open(video_path, 'rb') as f:
        resp = requests.post(
            UPLOAD_POST_URL,
            headers={'Authorization': f'Bearer {settings.upload_post_key}'},
            data={
                'title': title,
                'description': f'{description}\n\n{hashtags}',
                'platforms': ','.join(platforms),
            },
            files={'video': f}
        )
    resp.raise_for_status()
    return resp.json()
```

---

### 3.6 modules/db.py — 資料庫 Schema

使用 SQLite 記錄每個任務的完整生命週期，支援後台查詢、成本追蹤與錯誤重試。

| 欄位              | 型別       | 說明                                         |
| ----------------- | ---------- | -------------------------------------------- |
| `id`              | INTEGER PK | 自增主鍵                                     |
| `created_at`      | DATETIME   | 任務建立時間                                 |
| `topic`           | TEXT       | 影片主題                                     |
| `seedance_prompt` | TEXT       | 送給 Seedance 的 prompt                      |
| `generation_id`   | TEXT       | Seedance 任務 ID                             |
| `video_url`       | TEXT       | 生成的影片 URL                               |
| `local_path`      | TEXT       | 本地儲存路徑                                 |
| `title`           | TEXT       | 發布標題                                     |
| `hashtags`        | TEXT       | Hashtag                                      |
| `platforms`       | TEXT       | 發布平台（JSON）                             |
| `publish_result`  | TEXT       | 各平台發布結果（JSON）                       |
| `status`          | TEXT       | `pending` / `generating` / `done` / `failed` |
| `error`           | TEXT       | 錯誤訊息（如有）                             |
| `cost_credits`    | REAL       | 消耗 credits 數量                            |

```python
# modules/db.py
import sqlite3, json
from datetime import datetime
from config import settings

def get_conn():
    return sqlite3.connect(settings.db_path)

def init_db():
    with get_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                topic TEXT,
                seedance_prompt TEXT,
                generation_id TEXT,
                video_url TEXT,
                local_path TEXT,
                title TEXT,
                hashtags TEXT,
                platforms TEXT,
                publish_result TEXT,
                status TEXT DEFAULT 'pending',
                error TEXT,
                cost_credits REAL
            )
        ''')

def save_task(**kwargs) -> int:
    kwargs['created_at'] = datetime.now().isoformat()
    cols = ', '.join(kwargs.keys())
    placeholders = ', '.join(['?'] * len(kwargs))
    with get_conn() as conn:
        cur = conn.execute(
            f'INSERT INTO tasks ({cols}) VALUES ({placeholders})',
            list(kwargs.values())
        )
        return cur.lastrowid

def update_task(task_id: int, **kwargs):
    sets = ', '.join([f'{k}=?' for k in kwargs])
    with get_conn() as conn:
        conn.execute(
            f'UPDATE tasks SET {sets} WHERE id=?',
            [*kwargs.values(), task_id]
        )
```

---

### 3.7 scheduler.py — 排程邏輯

```python
# scheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler
from modules.prompt_gen import generate_video_metadata
from modules.video_gen import create_video_task, poll_until_done, download_video
from modules.video_process import process_video
from modules.publisher import publish_video
from modules.db import save_task, update_task
from config import settings
from pathlib import Path
import logging, datetime

logger = logging.getLogger(__name__)

def run_pipeline(topic: str = None):
    """一次完整的影片生成與發布流程"""
    task_id = save_task(status='pending')
    try:
        # Step 1: 生成 metadata
        meta = generate_video_metadata(topic)
        update_task(task_id, status='generating', **meta)

        # Step 2: 送出 Seedance 任務
        gen_id = create_video_task(
            meta['seedance_prompt'],
            duration=meta['duration'],
            aspect_ratio=meta['aspect_ratio']
        )
        update_task(task_id, generation_id=gen_id)

        # Step 3: 等待完成
        video_url = poll_until_done(gen_id)

        # Step 4: 下載
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_path = download_video(video_url, f'raw_{ts}.mp4')

        # Step 5: 後製
        final_path = raw_path.parent / f'final_{ts}.mp4'
        process_video(raw_path, final_path)

        # Step 6: 發布
        result = publish_video(
            final_path, meta['title'],
            meta['description'], meta['hashtags']
        )
        update_task(task_id, status='done',
                    local_path=str(final_path),
                    publish_result=str(result))
        logger.info(f'Task {task_id} completed: {meta["title"]}')

    except Exception as e:
        update_task(task_id, status='failed', error=str(e))
        logger.error(f'Task {task_id} failed: {e}')

def start_scheduler():
    sched = BlockingScheduler()
    for i in range(settings.daily_video_count):
        # 每支影片間隔 30 分鐘
        minute = i * 30
        sched.add_job(run_pipeline, 'cron',
                      hour=settings.schedule_hour,
                      minute=minute)
    sched.start()
```

---

## 4. FastAPI 管理後台

提供 REST API 供本地查看任務狀態、手動觸發任務、查詢成本統計。

| 端點                 | 方法   | 說明                               |
| -------------------- | ------ | ---------------------------------- |
| `/tasks`             | GET    | 列出所有任務（支援分頁、狀態篩選） |
| `/tasks/{id}`        | GET    | 查詢單一任務詳情                   |
| `/tasks/trigger`     | POST   | 手動觸發一次影片生成               |
| `/stats`             | GET    | 成本統計、成功率、各平台發布數     |
| `/tasks/{id}/output` | DELETE | 刪除本地影片檔案（節省空間）       |

```python
# api/routes.py
from fastapi import FastAPI, BackgroundTasks
from modules.db import get_conn
from scheduler import run_pipeline

app = FastAPI(title='AutoVideo Pipeline')

@app.get('/tasks')
def list_tasks(status: str = None, limit: int = 20):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                'SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?',
                [status, limit]
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM tasks ORDER BY id DESC LIMIT ?', [limit]
            ).fetchall()
    return rows

@app.post('/tasks/trigger')
def trigger(topic: str = None, background_tasks: BackgroundTasks = None):
    background_tasks.add_task(run_pipeline, topic)
    return {'message': 'Pipeline triggered', 'topic': topic}

@app.get('/stats')
def stats():
    with get_conn() as conn:
        total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='failed'").fetchone()[0]
    return {'total': total, 'done': done, 'failed': failed,
            'success_rate': f'{done/total*100:.1f}%' if total else '0%'}
```

---

## 5. 安裝與執行

### 5.1 requirements.txt

```
openai>=1.30.0
httpx>=0.27.0
requests>=2.31.0
ffmpeg-python>=0.2.0
apscheduler>=3.10.0
fastapi>=0.110.0
uvicorn>=0.29.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
sqlalchemy>=2.0.0
typer>=0.12.0
tenacity>=8.2.0        # retry 機制
```

### 5.2 .env 範本

```env
OPENAI_API_KEY=sk-...
AIMLAPI_KEY=...             # Seedance via AI/ML API
UPLOAD_POST_KEY=...         # Upload-Post.com API Key
DAILY_VIDEO_COUNT=3
SCHEDULE_HOUR=8
OUTPUT_DIR=./output
DB_PATH=./data/pipeline.db
```

### 5.3 main.py 進入點

```python
# main.py
import typer
app = typer.Typer()

@app.command()
def scheduler():
    from scheduler import start_scheduler
    start_scheduler()

@app.command()
def api():
    import uvicorn
    uvicorn.run('api.routes:app', host='0.0.0.0', port=8000, reload=True)

@app.command()
def run(topic: str = None):
    from scheduler import run_pipeline
    run_pipeline(topic)

if __name__ == '__main__':
    app()
```

### 5.4 啟動指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 確保 ffmpeg 已安裝
# Windows:  winget install ffmpeg
# macOS:    brew install ffmpeg
ffmpeg -version

# 初始化資料庫
python -c "from modules.db import init_db; init_db()"

# 手動觸發一次測試
python main.py run --topic "Tokyo street food"

# 啟動排程器（背景執行）
python main.py scheduler

# 啟動管理後台 → http://localhost:8000/docs
python main.py api
```

---

## 6. API 費用估算

> 以每日產 3 支影片估算：

| 服務                   | 用量                  | 單價             | 每日費用               |
| ---------------------- | --------------------- | ---------------- | ---------------------- |
| OpenAI GPT-4o          | 3 次呼叫 ~1000 tokens | $0.005/1K tokens | ~$0.015                |
| Seedance 1.0 Lite (5s) | 3 支影片              | ~$0.05/支        | ~$0.15                 |
| Upload-Post.com        | 3 次發布              | 方案起 $10/月    | ~$0.33/月均            |
| **合計**               | —                     | —                | **~$0.17/日 / ~$5/月** |

> 💡 AI/ML API 新用戶有免費 credits 可測試；Seedance 1.0 Lite 品質足以應付 TikTok / Shorts，Seedance Pro / 2.0 品質更好但費用較高。

---

## 7. 擴充方向

### 7.1 短期優化

- 加入 Prompt 模板庫（旅遊、美食、科技、療癒等不同風格）
- 支援 Image-to-Video（Seedance i2v），產品圖片自動生成廣告影片
- 整合 ElevenLabs TTS，為影片加入 AI 配音
- Telegram Bot 介面：傳 `/generate` 直接觸發並回傳影片

### 7.2 中期擴充

- 多帳號管理：同一 pipeline 發布到多個 TikTok / YouTube 帳號
- 成效追蹤：串接各平台 Analytics API，記錄觀看數、互動率
- A/B 測試：同一主題產兩個不同 prompt，比較效果
- React 管理介面：視覺化任務看板與成本圖表

### 7.3 長期 SaaS 化

- 將核心邏輯包裝成 REST API Service
- 多租戶支援：每個客戶獨立的帳號設定與 API Key
- 訂閱制計費：按每月發布數或影片數計費
- 換掉 SQLite → PostgreSQL，支援更高並發

---

## 8. 注意事項

### 8.1 平台政策

- TikTok Content Publishing API 需要申請開發者資格，審核可能需要數週
- 各平台對 AI 生成內容有不同揭露要求，建議說明欄加上 `#AIGenerated`
- Upload-Post.com 使用官方 OAuth，比 Cookie-based 方案更穩定且符合規範

### 8.2 技術注意

- Seedance API 生成時間約 40~120 秒，timeout 建議設 600 秒
- 影片 URL 有效期通常 24 小時，需在期限內下載
- ffmpeg 需另行安裝，Windows 用 `winget` / `chocolatey`，macOS 用 `brew`
- 建議加入重試機制（`tenacity` 套件），應對網路不穩或 API 暫時失敗

### 8.3 Claude Code 開發建議

- 將此文件放入專案根目錄命名為 `ARCHITECTURE.md`，Claude Code 會自動參考
- 建議逐模組開發：先 `video_gen.py` → 測試成功 → 再串 `prompt_gen.py`
- 先用 `python main.py run --topic 'test'` 手動測試，確認再設排程
- 每完成一個模組就 commit，方便 debug

---

_AutoVideo Pipeline v1.0 · 準備好了嗎？打開 Claude Code，讓我們開始建造 🚀_
