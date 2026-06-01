"""
動画生成パイプライン ワーカープロセス。
GUIプロセスから subprocess で起動し、完了後にプロセスを終了してメモリを解放する。

標準出力: {"tag": "info"|"success"|"warning"|"error", "message": "..."} の JSONL
標準入力: "cancel\\n" でキャンセル要求
結果ファイル (--result): {"status": "success"|"cancelled"|"failed", ...}
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import argparse
import json
import threading
import traceback


_cancel_event = threading.Event()


def _is_failure_message(message: str) -> bool:
    return str(message).lstrip().startswith("❌")


def _stdin_watcher() -> None:
    """stdin から "cancel" を受け取ったらキャンセルイベントをセットする。"""
    try:
        for line in sys.stdin:
            if line.strip() == "cancel":
                _cancel_event.set()
                break
    except Exception:
        raise


def _emit(tag: str, message: str) -> None:
    print(json.dumps({"tag": tag, "message": message}, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="入力パラメータ JSON ファイルパス")
    parser.add_argument("--result", required=True, help="結果を書き出す JSON ファイルパス")
    args = parser.parse_args()

    threading.Thread(target=_stdin_watcher, daemon=True).start()

    with open(args.input, "r", encoding="utf-8") as f:
        params = json.load(f)

    result: dict = {"status": "failed", "error": "不明なエラー"}
    try:
        from workers.main import run_pipeline  # noqa: PLC0415

        def progress(msg: str, tag: str = "info") -> None:
            _emit(tag, msg)

        msg, report = run_pipeline(
            topic=params["topic"],
            pregenerated_script=params.get("pregenerated_script"),
            image_style=params.get("image_style", "通常"),
            background_engine=params.get("background_engine"),
            reuse_backgrounds=params.get("reuse_backgrounds", False),
            reuse_audio=params.get("reuse_audio", False),
            cancel_event=_cancel_event,
            progress_callback=progress,
            long_thumbnail_ab_test=params.get("long_thumbnail_ab_test"),
            long_budget_mode=params.get("long_budget_mode"),
            sd_size_mode=params.get("sd_size_mode", False),
            bgm_mode=params.get("bgm_mode", "profile_default"),
            bgm_id=params.get("bgm_id"),
            bgm_volume_db=params.get("bgm_volume_db"),
        )

        if _cancel_event.is_set():
            result = {"status": "cancelled"}
        elif _is_failure_message(msg):
            result = {
                "status": "failed",
                "error": msg,
                "elapsed_sec": getattr(report, "elapsed_sec", None),
            }
        else:
            theme_dir = getattr(report, "theme_dir", "")
            result = {
                "status": "success",
                "message": msg,
                "elapsed_sec": getattr(report, "elapsed_sec", None),
                "history_name": os.path.basename(theme_dir) if theme_dir else "",
            }
    except Exception as e:
        tb = traceback.format_exc()
        result = {"status": "failed", "error": str(e)}
        _emit("error", f"パイプラインエラー: {e}")
        if tb:
            _emit("error", tb)  # トレースバックを stdout JSONL 経由でジョブログに渡す
    finally:
        with open(args.result, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
