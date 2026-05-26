"""
動画生成ジョブサービス。
既存の run_pipeline をジョブ化して実行する。
gui.py の生成動作を壊さないよう、run_pipeline のインターフェースをそのまま使う。
"""
import os
from typing import Any

from core.gui_support import split_input_scripts
from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager


def submit_generate_job(script: str, image_style: str = "通常", reuse_backgrounds: bool = False) -> str:
    """台本1本分の生成ジョブを登録してjob_idを返す。"""
    mgr = get_job_manager()
    job = mgr.create_job("generate")
    _log(job, "生成ジョブを登録しました", "info")
    mgr.submit(job, _run_generate, script, image_style, reuse_backgrounds)
    return job.job_id


def submit_batch_generate_jobs(scripts: list[str], image_style: str = "通常", reuse_backgrounds: bool = False) -> list[str]:
    """複数台本の生成ジョブを登録してjob_id一覧を返す。"""
    job_ids = []
    for script in scripts:
        job_ids.append(submit_generate_job(script, image_style, reuse_backgrounds))
    return job_ids


def _run_generate(job: Job, script: str, image_style: str, reuse_backgrounds: bool) -> dict[str, Any]:
    """バックグラウンドスレッドで呼ばれる生成ロジック。"""
    from main import run_pipeline
    from core.parser import ScriptParser

    def progress(msg: str, tag: str = "info"):
        _log(job, msg, tag)
        if job.cancel_event.is_set():
            raise _CancelledError()

    _log(job, "台本を解析中...", "info")

    # topicをparserで取得
    try:
        items = ScriptParser.parse_string(script)
        meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
        topic = meta.get("video_title", "").strip() or "unknown"
    except Exception:
        topic = "unknown"

    _log(job, f"動画生成開始: {topic}", "info")

    try:
        msg, report = run_pipeline(
            topic=topic,
            pregenerated_script=script,
            image_style=image_style,
            reuse_backgrounds=reuse_backgrounds,
            cancel_event=job.cancel_event,
            progress_callback=progress,
        )
    except _CancelledError:
        return {"cancelled": True}

    # 結果ファイルの存在確認
    theme_dir = os.path.join(OUTPUT_DIR, _safe_dirname(topic))
    result = {
        "topic": topic,
        "message": msg,
        "theme_dir": theme_dir,
        "elapsed_sec": getattr(report, "elapsed_sec", None),
    }

    _log(job, msg, "success" if "完了" in msg or "success" in msg.lower() else "info")
    return result


def split_scripts(raw: str) -> list[str]:
    return split_input_scripts(raw)


def _safe_dirname(title: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|]', '_', title)[:80]


class _CancelledError(Exception):
    pass
