"""
動画レンダリング ワーカープロセス。
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

    history_name: str = params["history_name"]
    theme_dir: str = params["theme_dir"]
    bgm_mode: str = params.get("bgm_mode", "profile_default")
    bgm_id: str | None = params.get("bgm_id")
    bgm_volume_db = params.get("bgm_volume_db")

    result: dict = {"status": "failed", "error": "不明なエラー"}
    try:
        from core.native_renderer import render_native_test  # noqa: PLC0415

        if _cancel_event.is_set():
            result = {"status": "cancelled"}
        else:
            render_result = render_native_test(
                output_dir=theme_dir,
                progress_callback=lambda msg, tag="info": _emit(tag or "info", msg),
                bgm_mode=bgm_mode,
                bgm_id=bgm_id,
                bgm_volume_db=bgm_volume_db,
            )
            output_path = (
                render_result.output_path
                if hasattr(render_result, "output_path")
                else str(render_result)
            )
            result = {
                "status": "success",
                "output_path": output_path,
                "history_name": history_name,
            }
    except Exception as e:
        tb = traceback.format_exc()
        result = {"status": "failed", "error": str(e)}
        _emit("error", f"レンダリングエラー: {e}")
        if tb:
            _emit("error", tb)  # トレースバックを stdout JSONL 経由でジョブログに渡す
    finally:
        with open(args.result, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
