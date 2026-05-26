"""
ローカルWeb UIエントリポイント。

起動方法:
  python web_app/app.py
  python -m web_app.app

アクセス: http://127.0.0.1:8000

127.0.0.1のみにバインドし、外部からアクセスできない。
"""
import os
import sys

# プロジェクトルートをパスに追加（web_app/ から実行されても動くように）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from core.gui_support import build_app_version

# ── アプリ生成 ────────────────────────────────────────────────────────────
app = FastAPI(
    title="動画ファクトリー — Web UI",
    version=build_app_version(),
    description="ずんだもんとめたんの食べ物雑学堂 ローカルWeb UI",
)

# 静的ファイル
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ── ルート登録 ────────────────────────────────────────────────────────────
from web_app.routes.pages import router as pages_router
from web_app.routes.api_status import router as status_router
from web_app.routes.api_jobs import router as jobs_router
from web_app.routes.api_history import router as history_router
from web_app.routes.api_generate import router as generate_router
from web_app.routes.api_check import router as check_router
from web_app.routes.api_images import router as images_router
from web_app.routes.api_analytics import router as analytics_router
from web_app.routes.api_schedule import router as schedule_router
from web_app.routes.api_upload import router as upload_router
from web_app.routes.api_fixed_comment import router as fixed_comment_router
from web_app.routes.api_settings import router as settings_router
from web_app.routes.api_prompt import router as prompt_router

app.include_router(pages_router)
app.include_router(status_router)
app.include_router(jobs_router)
app.include_router(history_router)
app.include_router(generate_router)
app.include_router(check_router)
app.include_router(images_router)
app.include_router(analytics_router)
app.include_router(schedule_router)
app.include_router(upload_router)
app.include_router(fixed_comment_router)
app.include_router(settings_router)
app.include_router(prompt_router)

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url="/static/favicon.svg", status_code=301)


# /health はシンプルにトップレベルにも置く
@app.get("/health")
def health():
    return {"status": "ok"}


# ── グローバル例外ハンドラ（秘密値をログに出さない） ──────────────────────────
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # スタックトレースは内部ログのみ。レスポンスには詳細を最小限にする
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"error": "サーバーエラーが発生しました", "detail": type(exc).__name__},
    )


# ── 起動 ──────────────────────────────────────────────────────────────────
def main():
    import argparse
    from config import WEB_UI_HOST, WEB_UI_PORT
    parser = argparse.ArgumentParser(description="Video Factory Web UI")
    parser.add_argument("--host", default=WEB_UI_HOST, help=f"bind host (default: {WEB_UI_HOST})")
    parser.add_argument("--port", type=int, default=WEB_UI_PORT, help=f"port (default: {WEB_UI_PORT})")
    parser.add_argument("--open-browser", action="store_true", help="open browser on startup")
    parser.add_argument("--reload", action="store_true", help="auto-reload on file change (dev)")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        print(
            f"警告: ホスト '{args.host}' を指定しています。"
            " 外部からのアクセスに注意してください。"
        )

    url = f"http://{args.host}:{args.port}"
    print(f"Web UI を起動しています: {url}")
    print("終了するには Ctrl+C を押してください。")

    if args.open_browser:
        import threading
        import webbrowser
        import time
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        "web_app.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
