"""
ローカルWeb UIエントリポイント。

起動方法:
  python web_app/app.py
  python -m web_app.app

アクセス: http://127.0.0.1:58080

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

from config import config
from core.debug_logging import setup_debug_logging
from core.gui_support import build_app_version

setup_debug_logging(role="web")

_runner_proc = None
_runner_stop_event = None

# ── アプリ生成 ────────────────────────────────────────────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    import threading
    from web_app.services.auto_fixed_comment_service import start_auto_watcher
    from web_app.services.status_service import refresh_settings_status
    from web_app.services.settings_preload_service import preload_settings_screen_cache
    from core.external_service_check import log_external_services
    from core.app_shutdown import register_shutdown_hook, run_lifespan_shutdown
    from core.metadata_db import close_all_connections

    from core.metadata_db import initialize_db
    initialize_db()  # 起動時に DB を確実に初期化しログを残す
    _start_job_runner()
    register_shutdown_hook("job_runner", _stop_job_runner)
    register_shutdown_hook("metadata_db", close_all_connections)

    # channel profile にテンプレートが未投入であればファイルから seed する
    try:
        from core.prompt_template_seeder import seed_all_profiles
        seed_all_profiles()
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning("[TemplateSeed] 起動時 seed でエラー: %s", _e)

    # キャラクター設定の分離・移行: 全チャンネルにキャラ設定を保証し、
    # 旧テンプレートに直書きされたキャラ設定の長文を除去する（既存チャンネルの移行）。
    try:
        from core.character_profiles_seed import (
            ensure_character_profiles_all,
            migrate_strip_character_rules_from_templates,
        )
        ensure_character_profiles_all()
        migrate_strip_character_rules_from_templates()
    except Exception as _e:
        import logging
        logging.getLogger(__name__).error("[CharacterSeed] 起動時キャラ設定の移行でエラー: %s", _e, exc_info=True)

    start_auto_watcher()
    threading.Thread(target=refresh_settings_status, daemon=True).start()
    threading.Thread(target=preload_settings_screen_cache, daemon=True, name="settings-screen-preload").start()
    threading.Thread(target=log_external_services, daemon=True).start()
    yield
    # ── shutdown フェーズ（Ctrl+C / SIGTERM / /api/shutdown すべてここを通る） ──
    run_lifespan_shutdown()


def _start_job_runner() -> None:
    """Web UI 起動に合わせて job-runner 常駐プロセスを起動・監視する。"""
    global _runner_proc, _runner_stop_event
    if os.environ.get("NVF_DISABLE_JOB_RUNNER", "").strip().lower() in ("1", "true", "yes", "on"):
        return
    import logging
    import subprocess
    import threading
    import time

    logger = logging.getLogger(__name__)
    _runner_stop_event = threading.Event()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    # POSIX は専用プロセスグループにして終了時に子（ffmpeg等）ごと killpg できるようにする
    if sys.platform == "win32":
        popen_extra = {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        popen_extra = {"start_new_session": True}

    # frozen(exe)時は `python -m workers.runner` が使えない（sys.executable が exe 自身）。
    # exe を `--run-runner` 付きで再起動して runner を別プロセス起動する。
    from core.runtime_env import is_frozen
    runner_cmd = [sys.executable, "--run-runner"] if is_frozen() else [sys.executable, "-m", "workers.runner"]

    def _spawn():
        return subprocess.Popen(
            runner_cmd,
            cwd=_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_extra,
        )

    _runner_proc = _spawn()
    logger.info("job-runner 起動 pid=%s", _runner_proc.pid)

    def _watch():
        global _runner_proc
        while not _runner_stop_event.wait(2.0):
            proc = _runner_proc
            if proc is None:
                continue
            if proc.poll() is not None:
                logger.error("job-runner が終了しました exit=%s。再起動します", proc.returncode)
                time.sleep(1.0)
                if not _runner_stop_event.is_set():
                    _runner_proc = _spawn()
                    logger.info("job-runner 再起動 pid=%s", _runner_proc.pid)

    threading.Thread(target=_watch, daemon=True, name="job-runner-watch").start()


def _stop_job_runner() -> None:
    global _runner_proc, _runner_stop_event
    if _runner_stop_event is not None:
        _runner_stop_event.set()
    proc = _runner_proc
    _runner_proc = None
    if proc is None or proc.poll() is not None:
        return
    _kill_process_tree(proc)


def _kill_process_tree(proc) -> None:
    """runner とその子（ffmpeg 等）をツリーごと終了し、孤児プロセスを残さない。"""
    import subprocess
    pid = proc.pid
    try:
        if sys.platform == "win32":
            # taskkill /T で子プロセスツリーごと強制終了する
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
        else:
            import os as _os
            import signal
            try:
                _os.killpg(_os.getpgid(pid), signal.SIGTERM)
                proc.wait(timeout=10)
            except Exception:
                _os.killpg(_os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

app = FastAPI(
    title=f"{config.WEB_APP_NAME} — Web UI",
    version=build_app_version(),
    description=f"{config.WEB_APP_NAME} ローカルWeb UI",
    lifespan=_lifespan,
)

# 静的ファイル
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.middleware("http")
async def setup_redirect_middleware(request: Request, call_next):
    """初回起動（active channel が未登録）のときだけ /setup へ誘導する。

    active channel が存在すれば、セットアップ未完了でも通常画面には入れる
    （生成・アップロードは各ルートの setup_gate / license で別途ブロックする）。
    設定画面はどの状態でも入れるよう除外する。
    """
    path = request.url.path
    if request.method == "GET" and not (
        path == "/setup"
        or path.startswith("/static")
        or path.startswith("/api")
        or path.startswith("/legal")
        or path in ("/favicon.ico", "/health", "/settings")
    ):
        from core.channel_profile import get_active_profile
        if get_active_profile() is None:
            return RedirectResponse(url="/setup", status_code=303)
    return await call_next(request)

# ── ルート登録 ────────────────────────────────────────────────────────────
from web_app.routes.pages import router as pages_router
from web_app.routes.api_status import router as status_router
from web_app.routes.api_jobs import router as jobs_router
from web_app.routes.api_history import router as history_router
from web_app.routes.api_generate import router as generate_router
from web_app.routes.api_check import router as check_router
from web_app.routes.api_images import router as images_router
from web_app.routes.api_bgm import router as bgm_router
from web_app.routes.api_analytics import router as analytics_router
from web_app.routes.api_schedule import router as schedule_router
from web_app.routes.api_upload import router as upload_router
from web_app.routes.api_fixed_comment import router as fixed_comment_router
from web_app.routes.api_settings import router as settings_router
from web_app.routes.api_prompt import router as prompt_router
from web_app.routes.api_sd_models import router as sd_models_router
from web_app.routes.api_shutdown import router as shutdown_router
from web_app.routes.api_db import router as db_router
from web_app.routes.api_channel import router as channel_router
from web_app.routes.api_channels import router as channels_router
from web_app.routes.api_prompt_templates import router as prompt_templates_router
from web_app.routes.api_character_profiles import router as character_profiles_router

app.include_router(pages_router)
app.include_router(status_router)
app.include_router(jobs_router)
app.include_router(history_router)
app.include_router(generate_router)
app.include_router(check_router)
app.include_router(images_router)
app.include_router(bgm_router)
app.include_router(analytics_router)
app.include_router(schedule_router)
app.include_router(upload_router)
app.include_router(fixed_comment_router)
app.include_router(settings_router)
app.include_router(prompt_router)
app.include_router(sd_models_router)
app.include_router(shutdown_router)
app.include_router(db_router)
app.include_router(channel_router)
app.include_router(channels_router)
app.include_router(prompt_templates_router)
app.include_router(character_profiles_router)

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url="/static/favicon.svg", status_code=301)


# /health はシンプルにトップレベルにも置く。
# service マーカーで「ポートを使っているのが自分自身か」を起動時に判別できるようにする。
_HEALTH_SERVICE_ID = "native-video-factory"


@app.get("/health")
def health():
    return {"status": "ok", "service": _HEALTH_SERVICE_ID, "app": config.WEB_APP_NAME}


# ── グローバル例外ハンドラ（秘密値をログに出さない） ──────────────────────────
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # スタックトレースは内部ログのみ。レスポンスには詳細を最小限にする
    import logging
    import traceback
    from core.error_codes import AppError
    logging.getLogger(__name__).exception("未処理例外: %s %s", request.method, request.url.path)
    traceback.print_exc()
    # AppError はエラーコードと対処手順を持つので、ユーザーに対処を提示する
    if isinstance(exc, AppError):
        return JSONResponse(
            status_code=422,
            content={
                "error": exc.user_message(),
                "code": exc.code,
                "remediation": exc.remediation,
                "retry_recommended": exc.retry_recommended,
            },
        )
    return JSONResponse(
        status_code=500,
        content={"error": "サーバーエラーが発生しました", "detail": type(exc).__name__},
    )


# ── ポートユーティリティ ──────────────────────────────────────────────────
def _is_port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_free_port(host: str, start: int, limit: int = 20) -> int | None:
    for port in range(start, start + limit):
        if _is_port_free(host, port):
            return port
    return None


def _probe_existing_instance(host: str, port: int) -> bool:
    """指定 host:port で稼働しているのが本アプリ自身かを /health で判定する。

    多重起動の検出に使う。別アプリが使っているポートと区別するため、
    /health の service マーカーが一致するときだけ True を返す。
    """
    import json
    import urllib.error
    import urllib.request
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as res:
            if res.status != 200:
                return False
            data = json.loads(res.read().decode("utf-8"))
            return data.get("service") == _HEALTH_SERVICE_ID
    except (OSError, TimeoutError, ValueError, urllib.error.URLError):
        return False


def _open_browser_to(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


# ── 起動 ──────────────────────────────────────────────────────────────────
def main():
    import argparse
    from config import WEB_UI_HOST, WEB_UI_PORT

    # frozen(exe)時の job-runner エントリ: exe 自身を `--run-runner` で起動すると
    # Web アプリではなく runner ループを実行する（python -m workers.runner の代替）。
    if "--run-runner" in sys.argv:
        from workers.runner import main as runner_main
        runner_main()
        return
    parser = argparse.ArgumentParser(description=f"{config.WEB_APP_NAME} Web UI")
    parser.add_argument("--host", default=WEB_UI_HOST, help=f"bind host (default: {WEB_UI_HOST})")
    parser.add_argument("--port", type=int, default=None,
                        help=f"使用するポート番号。省略時は config の WEB_UI_PORT ({WEB_UI_PORT}) を使用")
    parser.add_argument("--auto-port", action="store_true",
                        help="指定ポートが使用中の場合、自動で空きポートを探して起動する")
    parser.add_argument("--open-browser", action="store_true", help="起動後にブラウザを開く")
    parser.add_argument("--reload", action="store_true", help="ファイル変更時に自動リロード（開発用）")
    args = parser.parse_args()

    host = args.host
    port = args.port if args.port is not None else WEB_UI_PORT

    if host not in ("127.0.0.1", "localhost"):
        print(f"警告: ホスト '{host}' を指定しています。外部からのアクセスに注意してください。")

    # ポート競合チェック（多重起動の検出 → 自己回復）
    if not _is_port_free(host, port):
        existing_url = f"http://{host}:{port}"
        # ① 多重起動: 同じポートで本アプリが既に動いていれば、二重起動せずブラウザだけ開く
        if _probe_existing_instance(host, port):
            print(f"{config.WEB_APP_NAME} は既に起動しています: {existing_url}")
            print("二重起動はせず、既存のウィンドウを開きます。")
            if args.open_browser:
                _open_browser_to(existing_url)
            return
        # ② 別アプリがポートを使用中
        free = _find_free_port(host, port + 1)
        explicit_port = args.port is not None
        if explicit_port and not args.auto_port:
            # 明示的に --port 指定したポートは黙って変更しない（ユーザー意図を尊重）
            suggestion = f"  別のポートで起動: python web_app/app.py --port {free}" if free else ""
            print(
                f"エラー: ポート {port} は別のアプリが使用中です。\n"
                f"  自動で空きポートを探す: python web_app/app.py --auto-port\n"
                f"{suggestion}"
            )
            sys.exit(1)
        # 既定ポート（または --auto-port）は自己回復で空きポートへ退避する
        if free is None:
            print(f"エラー: ポート {port}〜{port + 19} がすべて使用中です。--port で別のポートを指定してください。")
            sys.exit(1)
        print(f"ポート {port} は別のアプリが使用中のため、{free} で起動します。")
        port = free

    url = f"http://{host}:{port}"
    print(f"Web UI を起動しています: {url}")
    print("終了するには Ctrl+C を押してください。")

    if args.open_browser:
        import threading
        import webbrowser
        import time
        import urllib.error
        import urllib.request
        def _open():
            health_url = f"{url}/health"
            for _ in range(50):
                try:
                    with urllib.request.urlopen(health_url, timeout=0.3) as res:
                        if res.status == 200:
                            webbrowser.open(url)
                            return
                except (OSError, TimeoutError, urllib.error.URLError):
                    # フォールバック許可: サーバー起動待ちの疎通失敗は短時間リトライする
                    time.sleep(0.2)
                    continue
                time.sleep(0.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    # Windows (Python 3.11) では ProactorEventLoop が I/O 待機中に Ctrl+C を
    # 受け取れないため、SelectorEventLoop に切り替える
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if args.reload:
        # --reload モードでは uvicorn.run() を使う（Server 参照は取れないが開発専用なので許容）
        uvicorn.run(
            "web_app.app:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=["web_app", "core", "config", "workers"],
            log_level="info",
        )
    else:
        # 通常起動: uvicorn.Server を直接使い should_exit で安全停止できるようにする
        import asyncio
        from core.app_shutdown import set_uvicorn_server

        def _serve_on(bind_port: int) -> None:
            uv_config = uvicorn.Config(
                "web_app.app:app",
                host=host,
                port=bind_port,
                log_level="info",
            )
            server = uvicorn.Server(uv_config)
            set_uvicorn_server(server)
            asyncio.run(server.serve())

        try:
            _serve_on(port)
        except KeyboardInterrupt:
            pass
        except OSError as exc:
            # 起動直前のレースでポートを奪われた場合の自己回復: 空きポートで1度だけ再試行する
            free = _find_free_port(host, port + 1)
            if free is None:
                print(f"エラー: ポート {port} の確保に失敗しました（{exc}）。空きポートも見つかりません。")
                sys.exit(1)
            print(f"ポート {port} の確保に失敗したため、{free} で起動し直します（{exc}）。")
            try:
                _serve_on(free)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
