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
    from workers.main import _estimate_script_duration
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
        thumbnail_text = meta.get("thumbnail_text", "")
        fixed_comment = meta.get("fixed_comment", "")

        # 尺レビュー
        estimated_sec = None
        dur_result: dict[str, Any] = {}
        _log(job, f"台本 {i}: 尺レビューを実行中...", "info")
        estimated_sec, _line_count, _avg_chars = _estimate_script_duration(items, is_shorts)
        dur_result = duration_review(float(estimated_sec or 0.0), is_shorts=is_shorts)
        _log(job, f"台本 {i}: 尺レビュー完了 ({dur_result.get('seconds', '—')}秒)", "info")

        # Ollamaレビューの前提になるローカル冒頭チェック
        local_result: dict[str, Any] = {}
        _log(job, f"台本 {i}: ローカル冒頭チェックを実行中...", "info")
        local_result = local_opening_review(items, title, thumbnail_text, is_shorts)
        _log(job, f"台本 {i}: ローカル冒頭チェック完了", "info")

        # LLMチェック（Ollama）
        llm_result: dict[str, Any] | None = {}
        if config.OPENING_REVIEW_USE_LLM:
            _log(job, f"台本 {i}: Ollamaレビューを実行中...", "info")
            llm_result = llm_opening_review(
                local_result,
                title,
                thumbnail_text,
                "Shorts" if is_shorts else "Long",
                "38-50秒" if is_shorts else "5-8分",
            ) or {"skipped": True, "reason": "Ollamaレビュー結果なし"}
            if (llm_result or {}).get("skipped"):
                _log(job, f"台本 {i}: Ollamaレビューをスキップ ({(llm_result or {}).get('reason', '理由なし')})", "warning")
            else:
                _log(job, f"台本 {i}: Ollamaレビュー完了", "info")
        else:
            llm_result = {"skipped": True, "reason": "OPENING_REVIEW_USE_LLM is false"}
            _log(job, f"台本 {i}: Ollamaレビューをスキップ (設定OFF)", "info")

        # ChatGPT最終レビュー
        final_result: dict[str, Any] | None = {}
        if config.OPENAI_FINAL_REVIEW_ENABLED:
            _log(job, f"台本 {i}: ChatGPT最終レビューを実行中...", "info")
            final_result = final_chatgpt_review(
                title=title,
                thumbnail_text=thumbnail_text,
                fixed_comment=fixed_comment,
                script_content=sc,
                items=items,
                is_shorts=is_shorts,
                estimated_duration=float(estimated_sec or 0.0),
                local_review=local_result,
                ollama_review=llm_result,
                duration_result=dur_result,
            ) or {"skipped": True, "reason": "ChatGPTレビュー結果なし"}
            if (final_result or {}).get("skipped"):
                _log(job, f"台本 {i}: ChatGPT最終レビューをスキップ ({(final_result or {}).get('reason', '理由なし')})", "warning")
            else:
                _log(job, f"台本 {i}: ChatGPT最終レビュー完了", "info")
        else:
            final_result = {"skipped": True, "reason": "OPENAI_FINAL_REVIEW_ENABLED is false"}
            _log(job, f"台本 {i}: ChatGPT最終レビューをスキップ (設定OFF)", "info")

        ollama_score = (llm_result or {}).get("score")
        chatgpt_score = (final_result or {}).get("final_score")

        entry = {
            "title": title,
            "video_format": video_format,
            "is_shorts": is_shorts,
            "dialogue_count": len(dialogue_items),
            "duration_label": duration_status_label(dur_result.get("status", "")) if dur_result else "",
            "duration_status": dur_result.get("status", ""),
            "estimated_seconds": dur_result.get("seconds"),
            "duration_error": dur_result.get("error", ""),
            "ollama_score": ollama_score,
            "ollama_status": (llm_result or {}).get("status", ""),
            "ollama_model": (llm_result or {}).get("model", ""),
            "ollama_skipped": bool((llm_result or {}).get("skipped")),
            "ollama_error": (llm_result or {}).get("error", ""),
            "ollama_enabled": bool(config.OPENING_REVIEW_USE_LLM),
            "chatgpt_score": chatgpt_score,
            "chatgpt_status": (final_result or {}).get("status", ""),
            "chatgpt_model": (final_result or {}).get("model", ""),
            "chatgpt_skipped": bool((final_result or {}).get("skipped")),
            "chatgpt_error": (final_result or {}).get("error", ""),
            "chatgpt_enabled": bool(config.OPENAI_FINAL_REVIEW_ENABLED),
        }
        results.append(entry)
        score_parts = []
        if ollama_score is not None:
            score_parts.append(f"Ollama={ollama_score}点")
        if chatgpt_score is not None:
            score_parts.append(f"ChatGPT={chatgpt_score}点")
        score_text = " / ".join(score_parts) if score_parts else "点数なし"
        _log(job, f"台本 {i} チェック完了: 尺={dur_result.get('seconds', '—')}秒 / {score_text}", "success")

    return results
