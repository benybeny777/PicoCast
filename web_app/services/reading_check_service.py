"""生成前の読みチェック（台本を貼った段階で、読みが分かれる語を調べる）。

台本の元の文（漢字のまま）を VOICEVOX の audio_query に渡して VOICEVOX の読みを取り、
core/reading_check.py で形態素解析の読みと比べる。音声の合成はしないので数秒で終わる。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from web_app.job_manager import Job, _log, get_job_manager

_logger = logging.getLogger(__name__)


def submit_script_check(script: str) -> str:
    from core.channel_profile import require_active_profile

    if not script.strip():
        raise ValueError("台本が空です")
    require_active_profile()
    mgr = get_job_manager()
    job = mgr.create_job("reading_check")
    mgr.submit(job, _run_script_check, script)
    return job.job_id


def _voicevox_chunks(script: str, profile_id: str) -> list[dict]:
    """台本から VOICEVOX で読む文を、生成時と同じ区切りで取り出す。"""
    from core.audio_backends import resolve_audio_speaker
    from workers.pipeline_helpers import split_at_punctuation
    from core.parser import ScriptParser

    chunks = []
    for item in ScriptParser.parse_string(script):
        if item["type"] != "dialogue":
            continue
        speaker = resolve_audio_speaker(profile_id, item["character"], item.get("emotion", "ノーマル"))
        if speaker.backend != "voicevox":
            continue  # AquesTalk は VOICEVOX の読みを持たない
        for text in split_at_punctuation(item["text"]):
            chunks.append({"text": text, "speaker_id": speaker.speaker_id})
    return chunks


def _run_script_check(job: Job, script: str) -> dict:
    from config import config as cfg
    from core.error_codes import AppError
    from core.reading_check import check_and_record, describe
    from core.voicevox import VoicevoxAPI

    if not job.profile_id:
        raise AppError("E-PROFILE-MISSING")
    chunks = _voicevox_chunks(script, job.profile_id)
    if not chunks:
        return {"checked": 0, "findings": []}
    vv = VoicevoxAPI()
    if not vv.check_connection():
        _logger.error("読みチェック: VOICEVOX に接続できません: url=%s", cfg.VOICEVOX_URL)
        raise AppError("E-VOICEVOX-DOWN", "読みチェックには VOICEVOX の起動が必要です。")
    _log(job, f"VOICEVOX の読みを取得中...（{len(chunks)}文）", "info")

    def query(chunk):
        _query, kana = vv.audio_query_only(chunk["text"], chunk["speaker_id"])
        return chunk["text"], kana

    workers = max(1, min(cfg.VOICEVOX_QUERY_WORKERS, len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pairs = list(pool.map(query, chunks))
    findings = check_and_record(pairs, source="生成前チェック")
    _log(job, f"読み違いの可能性: {len(findings)}件", "warning" if findings else "info")
    for finding in findings:
        _log(job, f"  - {describe(finding)}", "warning")
    return {
        "checked": len(chunks),
        "findings": [
            {"word": f.word, "voicevox_reading": f.voicevox_reading, "expected_reading": f.expected_reading, "text": f.text}
            for f in findings
        ],
    }
