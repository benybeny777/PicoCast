"""
動画生成ジョブサービス。
既存の run_pipeline をジョブ化して実行する。
Web UI は run_pipeline を唯一の生成入口として使う。
"""
import os
from typing import Any

from core.cta_policy import apply_topic_request_cta_policy_to_scripts
from core.gui_support import split_input_scripts
from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import safe_output_path


def submit_generate_job(
    script: str,
    image_style: str = "通常",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
) -> str:
    """台本1本分の生成ジョブを登録してjob_idを返す。"""
    prepared = apply_topic_request_cta_policy_to_scripts([script])
    script = prepared[0] if prepared else script
    return _submit_generate_job_prepared(
        script,
        image_style,
        reuse_backgrounds,
        long_thumbnail_ab_test,
        long_budget_mode,
        sd_size_mode,
    )


def _submit_generate_job_prepared(
    script: str,
    image_style: str = "通常",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
) -> str:
    """CTA方針反映済み台本を生成ジョブへ登録する。"""
    mgr = get_job_manager()
    job = mgr.create_job("generate")
    _log(job, "生成ジョブを登録しました", "info")
    mgr.submit(job, _run_generate, script, image_style, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode)
    return job.job_id


def submit_batch_generate_jobs(
    scripts: list[str],
    image_style: str = "通常",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
) -> list[str]:
    """複数台本の生成ジョブを登録してjob_id一覧を返す。"""
    job_ids = []
    for script in apply_topic_request_cta_policy_to_scripts(scripts):
        job_ids.append(_submit_generate_job_prepared(script, image_style, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode))
    return job_ids


def submit_history_regenerate_jobs(
    history_names: list[str],
    image_style: str = "通常",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
) -> list[str]:
    scripts: list[str] = []
    for name in history_names:
        if ".." in name or "/" in name or "\\" in name:
            continue
        theme_dir = safe_output_path(name)
        script_path = os.path.join(theme_dir, "script.txt")
        if not os.path.isfile(script_path):
            continue
        with open(script_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            scripts.append(text)
    return submit_batch_generate_jobs(scripts, image_style, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode)


def _run_generate(
    job: Job,
    script: str,
    image_style: str,
    reuse_backgrounds: bool,
    long_thumbnail_ab_test: bool,
    long_budget_mode: bool,
    sd_size_mode: bool,
) -> dict[str, Any]:
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
            long_thumbnail_ab_test=long_thumbnail_ab_test,
            long_budget_mode=long_budget_mode,
            sd_size_mode=sd_size_mode,
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
