"""
動画生成ジョブサービス。
run_pipeline をサブプロセス（worker_pipeline.py）で実行してメモリを解放する。
1本生成完了ごとにワーカープロセスが終了するため、GUIプロセスにメモリが蓄積しない。
"""
import os
from typing import Any

from core.cta_policy import apply_topic_request_cta_policy_to_scripts
from core.gui_support import split_input_scripts
from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import safe_output_path
from web_app.worker_runner import run_in_worker


def submit_generate_job(
    script: str,
    image_style: str = "通常",
    background_engine: str = "nanobanana",
    comfyui_preset: str = "anime_standard",
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
        background_engine,
        comfyui_preset,
        reuse_backgrounds,
        long_thumbnail_ab_test,
        long_budget_mode,
        sd_size_mode,
    )


def _submit_generate_job_prepared(
    script: str,
    image_style: str = "通常",
    background_engine: str = "nanobanana",
    comfyui_preset: str = "anime_standard",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
) -> str:
    """CTA方針反映済み台本を生成ジョブへ登録する。"""
    mgr = get_job_manager()
    job = mgr.create_job("generate")
    _log(job, "生成ジョブを登録しました", "info")
    mgr.submit(job, _run_generate, script, image_style, background_engine, comfyui_preset, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render)
    return job.job_id


def submit_batch_generate_jobs(
    scripts: list[str],
    image_style: str = "通常",
    background_engine: str = "nanobanana",
    comfyui_preset: str = "anime_standard",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
) -> list[str]:
    """複数台本の生成ジョブを登録してjob_id一覧を返す。"""
    job_ids = []
    for script in apply_topic_request_cta_policy_to_scripts(scripts):
        job_ids.append(_submit_generate_job_prepared(script, image_style, background_engine, comfyui_preset, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render))
    return job_ids


def submit_history_regenerate_jobs(
    history_names: list[str],
    image_style: str = "通常",
    background_engine: str = "nanobanana",
    comfyui_preset: str = "anime_standard",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
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
    return submit_batch_generate_jobs(scripts, image_style, background_engine, comfyui_preset, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render)


def _run_generate(
    job: Job,
    script: str,
    image_style: str,
    background_engine: str,
    comfyui_preset: str,
    reuse_backgrounds: bool,
    long_thumbnail_ab_test: bool,
    long_budget_mode: bool,
    sd_size_mode: bool,
    with_render: bool = False,
) -> dict[str, Any]:
    """バックグラウンドスレッドから呼ばれる。worker_pipeline.py をサブプロセスで起動する。"""
    from core.parser import ScriptParser

    _log(job, "台本を解析中...", "info")
    try:
        items = ScriptParser.parse_string(script)
        meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
        topic = meta.get("video_title", "").strip() or "unknown"
    except Exception:
        topic = "unknown"

    _log(job, f"動画生成開始: {topic}", "info")

    worker_result = run_in_worker(
        "worker_pipeline.py",
        {
            "topic": topic,
            "pregenerated_script": script,
            "image_style": image_style,
            "background_engine": background_engine,
            "comfyui_preset": comfyui_preset,
            "reuse_backgrounds": reuse_backgrounds,
            "long_thumbnail_ab_test": long_thumbnail_ab_test,
            "long_budget_mode": long_budget_mode,
            "sd_size_mode": sd_size_mode,
        },
        job,
    )

    status = worker_result.get("status")
    if status == "cancelled":
        return {"cancelled": True}
    if status == "failed":
        raise RuntimeError(worker_result.get("error", "ワーカーエラー"))

    msg = worker_result.get("message", "")
    if str(msg).lstrip().startswith("❌"):
        raise RuntimeError(msg)
    theme_dir = os.path.join(OUTPUT_DIR, _safe_dirname(topic))
    result = {
        "topic": topic,
        "message": msg,
        "theme_dir": theme_dir,
        "elapsed_sec": worker_result.get("elapsed_sec"),
    }

    _log(job, msg, "success" if "完了" in msg or "success" in msg.lower() else "info")

    if with_render and ("完了" in msg or "success" in msg.lower()):
        from web_app.services.render_service import submit_render_job
        history_name = _safe_dirname(topic)
        try:
            render_job_id = submit_render_job(history_name)
            _log(job, f"🎬 レンダージョブを登録しました (job_id={render_job_id[:8]}…)", "info")
        except Exception as _re:
            _log(job, f"⚠ レンダージョブの登録に失敗: {_re}", "warning")

    return result


def split_scripts(raw: str) -> list[str]:
    return split_input_scripts(raw)


def _safe_dirname(title: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|]', '_', title)[:80]
