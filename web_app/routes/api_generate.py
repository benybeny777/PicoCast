from fastapi import APIRouter, HTTPException
from web_app.schemas import GenerateRequest, BatchGenerateRequest
from web_app.services.generation_service import (
    submit_generate_job,
    submit_batch_generate_jobs,
    split_scripts,
)

router = APIRouter(prefix="/api/generate", tags=["generate"])


@router.post("")
def api_generate(req: GenerateRequest):
    """台本1本分または複数台本の動画生成ジョブを登録する。"""
    # 複数台本が混在している場合は自動分割してバッチ処理
    scripts = split_scripts(req.script)
    if not scripts:
        raise HTTPException(status_code=400, detail="台本が空です")

    if len(scripts) == 1:
        job_id = submit_generate_job(
            scripts[0],
            req.image_style,
            req.background_engine,
            req.reuse_backgrounds,
            req.long_thumbnail_ab_test,
            req.long_budget_mode,
            req.sd_size_mode,
            req.with_render,
            req.bgm_mode,
            req.bgm_id,
            req.bgm_volume_db,
        )
        return {"job_ids": [job_id], "count": 1}
    else:
        job_ids = submit_batch_generate_jobs(
            scripts,
            req.image_style,
            req.background_engine,
            req.reuse_backgrounds,
            req.long_thumbnail_ab_test,
            req.long_budget_mode,
            req.sd_size_mode,
            req.with_render,
            req.bgm_mode,
            req.bgm_id,
            req.bgm_volume_db,
        )
        return {"job_ids": job_ids, "count": len(job_ids)}


@router.post("/batch")
def api_batch_generate(req: BatchGenerateRequest):
    """明示的に複数台本を指定して生成ジョブを登録する。"""
    if not req.scripts:
        raise HTTPException(status_code=400, detail="台本リストが空です")
    job_ids = submit_batch_generate_jobs(
        req.scripts,
        req.image_style,
        req.background_engine,
        req.reuse_backgrounds,
        req.long_thumbnail_ab_test,
        req.long_budget_mode,
        req.sd_size_mode,
        req.with_render,
        req.bgm_mode,
        req.bgm_id,
        req.bgm_volume_db,
    )
    return {"job_ids": job_ids, "count": len(job_ids)}
