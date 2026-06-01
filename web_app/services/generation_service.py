"""
動画生成ジョブサービス。
run_pipeline をサブプロセス（worker_pipeline.py）で実行してメモリを解放する。
1本生成完了ごとにワーカープロセスが終了するため、GUIプロセスにメモリが蓄積しない。
"""
import os
from typing import Any

from core.cta_policy import apply_topic_request_cta_policy_to_scripts
from core.gui_support import split_input_scripts
from core.output_paths import get_output_videos_dir
from web_app.job_manager import Job, _log, get_job_manager
from web_app.worker_runner import run_in_worker


def submit_generate_job(
    script: str,
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
) -> str:
    """台本1本分の生成ジョブを登録してjob_idを返す。"""
    prepared = apply_topic_request_cta_policy_to_scripts([script])
    script = prepared[0] if prepared else script
    return _submit_generate_job_prepared(
        script,
        image_style,
        background_engine,
        reuse_backgrounds,
        long_thumbnail_ab_test,
        long_budget_mode,
        sd_size_mode,
        with_render,
        bgm_mode,
        bgm_id,
        bgm_volume_db,
    )


def _submit_generate_job_prepared(
    script: str,
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
) -> str:
    """CTA方針反映済み台本を生成ジョブへ登録する。"""
    mgr = get_job_manager()
    job = mgr.create_job("generate")
    _log(job, "生成ジョブを登録しました", "info")
    mgr.submit(job, _run_generate, script, image_style, background_engine, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render, bgm_mode, bgm_id, bgm_volume_db)
    return job.job_id


def submit_batch_generate_jobs(
    scripts: list[str],
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
) -> list[str]:
    """複数台本の生成ジョブを登録してjob_id一覧を返す。"""
    job_ids = []
    for script in apply_topic_request_cta_policy_to_scripts(scripts):
        job_ids.append(_submit_generate_job_prepared(script, image_style, background_engine, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render, bgm_mode, bgm_id, bgm_volume_db))
    return job_ids


def submit_history_regenerate_jobs(
    history_names: list[str],
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    sd_size_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
) -> list[str]:
    from core.metadata_db import get_script_content

    scripts: list[str] = []
    for name in history_names:
        if ".." in name or "/" in name or "\\" in name:
            continue
        # 台本本文は metadata.db (videos.script_content) を正本として取得する。
        # 旧実装はディスクの script.txt を読んでいたが、DB の output_dir が
        # 旧パスのままだと参照先が外れて 404 になっていた（local_id=フォルダ名で引く）。
        text = get_script_content(name)
        if text and text.strip():
            scripts.append(text.strip())
    return submit_batch_generate_jobs(scripts, image_style, background_engine, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render, bgm_mode, bgm_id, bgm_volume_db)


def _run_generate(
    job: Job,
    script: str,
    image_style: str,
    background_engine: str,
    reuse_backgrounds: bool,
    long_thumbnail_ab_test: bool,
    long_budget_mode: bool,
    sd_size_mode: bool,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
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
        "workers/worker_pipeline.py",
        {
            "topic": topic,
            "pregenerated_script": script,
            "image_style": image_style,
            "background_engine": background_engine,
            "reuse_backgrounds": reuse_backgrounds,
            "long_thumbnail_ab_test": long_thumbnail_ab_test,
            "long_budget_mode": long_budget_mode,
            "sd_size_mode": sd_size_mode,
            "bgm_mode": bgm_mode,
            "bgm_id": bgm_id,
            "bgm_volume_db": bgm_volume_db,
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
    history_name = worker_result.get("history_name") or _safe_dirname(topic)
    theme_dir = os.path.join(get_output_videos_dir(), history_name)
    result = {
        "topic": topic,
        "message": msg,
        "theme_dir": theme_dir,
        "elapsed_sec": worker_result.get("elapsed_sec"),
    }

    _log(job, msg, "success" if status == "success" else "info")

    if with_render and status == "success":
        from web_app.services.render_service import submit_render_job
        try:
            render_job_id = submit_render_job(history_name, bgm_mode, bgm_id, bgm_volume_db)
            result["render_job_id"] = render_job_id
            _log(job, f"🎬 レンダージョブを登録しました (job_id={render_job_id[:8]}…)", "info")
        except Exception as _re:
            _log(job, f"⚠ レンダージョブの登録に失敗: {_re}", "warning")

    return result


def split_scripts(raw: str) -> list[str]:
    return split_input_scripts(raw)


def _safe_dirname(title: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|]', '_', title)[:80]
