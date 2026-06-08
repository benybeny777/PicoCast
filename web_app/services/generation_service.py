"""動画生成ジョブサービス。"""

import time
from dataclasses import dataclass

from core.cta_policy import apply_topic_request_cta_policy_to_scripts
from core.gui_support import split_input_scripts
from web_app.job_manager import _log, get_job_manager


@dataclass(frozen=True)
class _GenerateOptions:
    image_style: str = "通常"
    background_engine: str = ""
    reuse_backgrounds: bool = False
    long_thumbnail_ab_test: bool = False
    long_budget_mode: bool = False
    with_render: bool = False
    bgm_mode: str = "profile_default"
    bgm_id: str | None = None
    bgm_volume_db: float | None = None
    reuse_audio: bool = False


def _current_worker_limit() -> int:
    """生成・レンダーの同時実行数設定を返す。"""
    from config import JOB_MAX_CONCURRENT_WORKERS
    from core.settings_store import get_all

    raw_limit = get_all().get("JOB_MAX_CONCURRENT_WORKERS", str(JOB_MAX_CONCURRENT_WORKERS))
    try:
        return max(1, int(raw_limit))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"JOB_MAX_CONCURRENT_WORKERS が整数ではありません: {raw_limit}") from exc


def _active_runnable_count() -> int:
    """生成・レンダーの queued/running 件数を返す。"""
    from config import JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC
    from core.metadata_db import discard_orphan_running_jobs, load_jobs_from_db, reap_stale_running_jobs

    discard_orphan_running_jobs(("generate", "render"))
    reap_stale_running_jobs(JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC)
    jobs = load_jobs_from_db(max_n=5000)
    return sum(
        1
        for j in jobs
        if j.get("type") in ("generate", "render")
        and (
            j.get("status") == "queued"
            or (j.get("status") == "running" and j.get("runner_pid") is not None)
        )
    )


def _queue_wait_note() -> str:
    """登録直後に、runner待ちが発生しそうなら画面ログへ出す補足を作る。"""
    active_count = _active_runnable_count()
    limit = _current_worker_limit()
    if active_count <= limit:
        return ""
    ahead = active_count - 1
    return f"⏳ キュー待機中: 前に {ahead} 件あります（同時実行数 {limit}）"


def _job_is_done(job_id: str) -> bool:
    """DB上の子ジョブが終了状態なら True。"""
    mgr = get_job_manager()
    child = mgr.get_job(job_id)
    if child is None:
        return False
    return child.status in ("success", "failed", "cancelled")


def _wait_for_available_generate_slot(job, *, limit: int, poll_interval: float) -> None:
    """生成・レンダー枠が空くまで待つ。"""
    last_count: int | None = None
    while not job.cancel_event.is_set() and _active_runnable_count() >= limit:
        active_count = _active_runnable_count()
        if active_count != last_count:
            _log(job, f"次の生成投入待ち: 実行/待機中 {active_count} 件 / 同時実行数 {limit}", "info")
            last_count = active_count
        time.sleep(poll_interval)


def _submit_child_generate_job(script: str, options: _GenerateOptions) -> str:
    return _submit_generate_job_prepared(
        script,
        options.image_style,
        options.background_engine,
        options.reuse_backgrounds,
        options.long_thumbnail_ab_test,
        options.long_budget_mode,
        options.with_render,
        options.bgm_mode,
        options.bgm_id,
        options.bgm_volume_db,
        options.reuse_audio,
    )


def _run_batch_generate(job, scripts: list[str], options: _GenerateOptions) -> dict:
    """複数生成を同時実行数ぶんだけ順次DBキューへ投入する。"""
    from config import JOB_RUNNER_POLL_INTERVAL_SEC

    limit = _current_worker_limit()
    poll_interval = max(0.5, float(JOB_RUNNER_POLL_INTERVAL_SEC))
    child_ids: list[str] = []
    total = len(scripts)
    _log(job, f"複数生成を開始: {total}件（同時投入数 {limit}）", "info")

    for index, script in enumerate(scripts, start=1):
        _wait_for_available_generate_slot(job, limit=limit, poll_interval=poll_interval)
        if job.cancel_event.is_set():
            _log(job, f"キャンセル要求により未投入 {total - index + 1}件を中止", "warning")
            return {"cancelled": True, "job_ids": child_ids, "submitted": len(child_ids), "total": total}
        child_id = _submit_child_generate_job(script, options)
        child_ids.append(child_id)
        _log(job, f"子生成ジョブを投入: {index}/{total} ({child_id})", "info")

    while not job.cancel_event.is_set() and any(not _job_is_done(child_id) for child_id in child_ids):
        done = sum(1 for child_id in child_ids if _job_is_done(child_id))
        _log(job, f"子生成ジョブ完了待ち: {done}/{len(child_ids)}", "info")
        time.sleep(poll_interval)

    if job.cancel_event.is_set():
        _log(job, "キャンセル要求により複数生成の監視を終了", "warning")
        return {"cancelled": True, "job_ids": child_ids, "submitted": len(child_ids), "total": total}

    _log(job, f"複数生成の投入・完了確認が終了: {len(child_ids)}/{total}件", "success")
    return {"job_ids": child_ids, "submitted": len(child_ids), "total": total}


def submit_generate_job(
    script: str,
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
    reuse_audio: bool = False,
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
        with_render,
        bgm_mode,
        bgm_id,
        bgm_volume_db,
        reuse_audio,
    )


def _submit_generate_job_prepared(
    script: str,
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
    reuse_audio: bool = False,
) -> str:
    """CTA方針反映済み台本を生成ジョブへ登録する。"""
    mgr = get_job_manager()
    job = mgr.create_job("generate", params={
        "script": script,
        "image_style": image_style,
        "background_engine": background_engine,
        "reuse_backgrounds": reuse_backgrounds,
        "reuse_audio": reuse_audio,
        "long_thumbnail_ab_test": long_thumbnail_ab_test,
        "long_budget_mode": long_budget_mode,
        "with_render": with_render,
        "bgm_mode": bgm_mode,
        "bgm_id": bgm_id,
        "bgm_volume_db": bgm_volume_db,
    })
    _log(job, "生成ジョブを登録しました", "info")
    note = _queue_wait_note()
    if note:
        _log(job, note, "info")
    return job.job_id


def submit_batch_generate_jobs(
    scripts: list[str],
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
    reuse_audio: bool = False,
) -> list[str]:
    """複数台本を親ジョブへ登録し、同時実行数ぶんだけ順次子ジョブ投入する。"""
    prepared = apply_topic_request_cta_policy_to_scripts(scripts)
    if not prepared:
        return []
    options = _GenerateOptions(
        image_style=image_style,
        background_engine=background_engine,
        reuse_backgrounds=reuse_backgrounds,
        long_thumbnail_ab_test=long_thumbnail_ab_test,
        long_budget_mode=long_budget_mode,
        with_render=with_render,
        bgm_mode=bgm_mode,
        bgm_id=bgm_id,
        bgm_volume_db=bgm_volume_db,
        reuse_audio=reuse_audio,
    )
    mgr = get_job_manager()
    job = mgr.create_job("generate_batch", params={
        "count": len(prepared),
        "options": options.__dict__,
    })
    _log(job, f"複数生成ジョブを登録しました: {len(prepared)}件", "info")
    mgr.submit(job, _run_batch_generate, prepared, options)
    return [job.job_id]


def submit_history_regenerate_jobs(
    history_names: list[str],
    image_style: str = "通常",
    background_engine: str = "",
    reuse_backgrounds: bool = False,
    long_thumbnail_ab_test: bool = False,
    long_budget_mode: bool = False,
    with_render: bool = False,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
    reuse_audio: bool = False,
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
    return submit_batch_generate_jobs(scripts, image_style, background_engine, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, with_render, bgm_mode, bgm_id, bgm_volume_db, reuse_audio)


def split_scripts(raw: str) -> list[str]:
    return split_input_scripts(raw)
