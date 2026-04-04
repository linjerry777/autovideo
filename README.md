# AutoVideo | Python AI 全自動短影音系統

Fully automated AI video generation and multi-platform publishing pipeline.

從 Prompt 生成 → 影片生成 → 後製 → 多平台發布，全程無人工介入。

## 功能 Features

- **AI 腳本生成** — OpenAI GPT-4o 自動產生影片腳本、標題、Hashtag
- **AI 影片生成** — Seedance API 生成高品質短影音（5s / 10s，9:16 豎版）
- **ffmpeg 後製** — 音訊正規化、浮水印、解析度標準化
- **多平台發布** — 一鍵同步 TikTok / YouTube Shorts / Instagram Reels
- **定時排程** — APScheduler 每日定時自動執行
- **FastAPI 後台** — REST API 查看任務歷史、手動觸發、成本統計

## 技術棧 Tech Stack

| 項目 | 技術 |
|------|------|
| 語言 | Python 3.11+ |
| AI 腳本 | OpenAI GPT-4o |
| AI 影片 | Seedance API (via AI/ML API) |
| 後製 | ffmpeg-python |
| 排程 | APScheduler |
| 後台 API | FastAPI + Uvicorn |
| 資料庫 | SQLite |
| 設定管理 | Pydantic Settings + python-dotenv |

## 快速開始 Getting Started

```bash
# 安裝依賴（需先安裝 ffmpeg）
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 填入 API keys

# 初始化資料庫
python -c "from modules.db import init_db; init_db()"

# 手動測試一次
python main.py run --topic "Tokyo street food"

# 啟動排程器
python main.py scheduler

# 啟動管理後台 → http://localhost:8000/docs
python main.py api
```

## 環境變數 Environment Variables

```env
OPENAI_API_KEY=sk-...
AIMLAPI_KEY=...           # Seedance 影片生成
UPLOAD_POST_KEY=...       # 多平台發布
DAILY_VIDEO_COUNT=3
SCHEDULE_HOUR=8
```

## 費用估算 Cost Estimate

每日產 3 支影片約 **$0.17 USD / 日（約 $5 / 月）**

| 服務 | 費用 |
|------|------|
| OpenAI GPT-4o | ~$0.015/日 |
| Seedance 1.0 Lite | ~$0.15/日 |
| Upload-Post.com | ~$0.33/月均 |

## 詳細架構

請參閱 [AutoVideo Pipeline.md](./AutoVideo%20Pipeline.md)
