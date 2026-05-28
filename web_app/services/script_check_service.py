"""
LLM/尺チェックサービス。
既存 opening_quality.py の各関数をジョブとして実行する。
"""
from typing import Any

from core.gui_support import split_input_scripts
from core.parser import ScriptParser
from web_app.job_manager import Job, _log, get_job_manager


def submit_check_job(script: str) -> str:
    mgr = get_job_manager()
    job = mgr.create_job("check")
    _log(job, "チェックジョブを登録しました", "info")
    mgr.submit(job, _run_check, script)
    return job.job_id


def _run_check(job: Job, script: str) -> list[dict[str, Any]]:
    from core.opening_quality import (
        local_opening_review,
        llm_opening_review,
        duration_review,
        duration_status_label,
        final_chatgpt_review,
    )
    from config import config

    scripts = split_input_scripts(script)
    if not scripts:
        scripts = [script]

    results = []
    for i, sc in enumerate(scripts, 1):
        if job.cancel_event.is_set():
            break

        _log(job, f"台本 {i}/{len(scripts)} をチェック中...", "info")
        items = ScriptParser.parse_string(sc)
        meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
        dialogue_items = [it for it in items if it["type"] == "dialogue"]
        video_format = meta.get("video_format", "Shorts")
        is_shorts = "long" not in video_format.lower()
        title = meta.get("video_title", f"台本{i}")

        # ローカルチェック
        local_result = {}
        try:
            local_result = local_opening_review(items, is_shorts=is_shorts)
        except Exception as e:
            local_result = {"error": str(e)}

        # 尺レビュー
        dur_result = {}
        try:
            dur_result = duration_review(items, is_shorts=is_shorts)
        except Exception as e:
            dur_result = {"error": str(e)}

        # LLMチェック（Ollama）
        llm_result = {}
        if config.OPENING_REVIEW_USE_LLM:
            try:
                llm_result = llm_opening_review(items, is_shorts=is_shorts)
            except Exception as e:
                llm_result = {"error": str(e), "skipped": True}

        # ChatGPT最終レビュー
        final_result = {}
        if config.OPENAI_FINAL_REVIEW_ENABLED:
            try:
                final_result = final_chatgpt_review(
                    items,
                    is_shorts=is_shorts,
                    opening_review_result=local_result,
                    duration_result=dur_result,
                )
            except Exception as e:
                final_result = {"error": str(e), "skipped": True}

        local_score = local_result.get("overall_score") or local_result.get("score")
        llm_score = llm_result.get("overall_score")
        final_score = final_result.get("final_score")
        best_score = final_score or llm_score or local_score

        entry = {
            "title": title,
            "video_format": video_format,
            "is_shorts": is_shorts,
            "dialogue_count": len(dialogue_items),
            "local_review": local_result,
            "duration_review": dur_result,
            "duration_label": duration_status_label(dur_result.get("status", "")) if dur_result else "",
            "estimated_seconds": dur_result.get("seconds"),
            "llm_review": llm_result,
            "final_review": final_result,
            "opening_score": best_score,
            "must_fix": (
                local_result.get("must_fix", []) +
                llm_result.get("must_fix", []) +
                final_result.get("must_fix", [])
            ),
            "warnings": (
                local_result.get("warnings", []) +
                llm_result.get("warnings", [])
            ),
            "script": sc,
        }
        results.append(entry)
        _log(job, f"台本 {i} チェック完了: スコア={best_score}", "success" if best_score and best_score >= 70 else "warning")

    return results
