"""動画生成ジョブサービス。"""

from core.cta_policy import apply_topic_request_cta_policy_to_scripts
from core.gui_support import split_input_scripts
from web_app.job_manager import _log, get_job_manager


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
        sd_size_mode,
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
    sd_size_mode: bool = False,
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
        "sd_size_mode": sd_size_mode,
        "with_render": with_render,
        "bgm_mode": bgm_mode,
        "bgm_id": bgm_id,
        "bgm_volume_db": bgm_volume_db,
    })
    _log(job, "生成ジョブを登録しました", "info")
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
    reuse_audio: bool = False,
) -> list[str]:
    """複数台本の生成ジョブを登録してjob_id一覧を返す。"""
    job_ids = []
    for script in apply_topic_request_cta_policy_to_scripts(scripts):
        job_ids.append(_submit_generate_job_prepared(script, image_style, background_engine, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render, bgm_mode, bgm_id, bgm_volume_db, reuse_audio))
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
    return submit_batch_generate_jobs(scripts, image_style, background_engine, reuse_backgrounds, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, with_render, bgm_mode, bgm_id, bgm_volume_db, reuse_audio)


def split_scripts(raw: str) -> list[str]:
    return split_input_scripts(raw)
