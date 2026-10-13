"""既存生成パイプラインをつなぐ、段階保存型のフルオート運用。"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime

from core import autopilot_store as store
from core.autopilot_budget import budget_scope
from core.channel_profile import require_active_profile
from core.error_codes import AppError
from core.metadata_db import ManagedConnection

_logger = logging.getLogger(__name__)
_STAGES = ("analytics", "topic", "script", "generate", "render", "review", "upload", "analysis", "complete")


def _json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise AppError("E-AUTO-HOLD", "AIの応答がJSONオブジェクトではありません")
    return value


def _generate_text(prompt: str, *, grounded: bool = False) -> str:
    from config import config as cfg
    from core.ai_generator import AIGenerator
    with AIGenerator() as generator:
        if generator.client is None:
            raise AppError("E-SECRET-MISSING")
        config = {"tools": [{"google_search": {}}]} if grounded else None
        response = generator.client.models.generate_content(model=cfg.GEMINI_MODEL, contents=prompt, config=config)
        if not response.text:
            raise AppError("E-AUTO-HOLD", "AIから本文が返りませんでした")
        return response.text


def _choose_topic(run: dict) -> dict:
    from core.script_prompts import build_title_prompt
    from core.analytics_score import build_performance_summary, to_tsv
    from web_app.services.prompt_service import _collect_all_titles
    from web_app.services.analytics_service import load_latest_analytics_full
    data = load_latest_analytics_full()
    items = data.get("items") or []
    summary = build_performance_summary(items, meta=data) if items else "まだ実績データはありません。新規テーマを選定してください。"
    titles = _collect_all_titles()
    with ManagedConnection() as conn:
        titles += [row[0] for row in conn.execute("SELECT topic FROM autopilot_runs WHERE topic IS NOT NULL")]
    prompt = build_title_prompt(titles, analytics_tsv=summary + "\n" + to_tsv(items))
    prompt += (f"\n今回の自動運用は{run['video_type']}を1本だけ作成します。\n"
               "候補を比較し、既存・予約済みテーマと重複しない1本を選んでください。実績不足を成功パターンと断定しないでください。\n"
               '最終出力はJSONのみ: {"title":"選んだタイトル","reason":"選定理由"}')
    topic = _json_object(_generate_text(prompt))
    title = topic.get("title")
    if not isinstance(title, str) or not title.strip() or title.strip().casefold() in {t.strip().casefold() for t in titles}:
        raise AppError("E-AUTO-HOLD", "ネタ選定結果が空、または既存タイトルと重複しています")
    return {"topic": title.strip()}


def _write_script(run: dict) -> dict:
    from core.parser import ScriptParser
    from core.playlist_resolver import resolve_video_type
    from core.ng_words import apply_ng_word_replacements
    from web_app.services.prompt_service import get_script_generation_prompt
    prompt = get_script_generation_prompt()["prompt"]
    prompt += (f"\n今回作るのは{run['video_type']}の台本1本だけです。\n"
               f"動画タイトルは正確に次の文字列にしてください: {run['topic']}\n"
               "他の動画・候補一覧・会議台本を出さないでください。指定形式の動画形式メタデータと台本本文だけを出力してください。\n"
               "事実は確認できる根拠に基づき、怪談・伝承・噂は事実と区別してください。")
    script = _generate_text(prompt, grounded=True).strip()
    if script.startswith("```"):
        script = script.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    script = apply_ng_word_replacements(script)
    items = ScriptParser.parse_string(script)
    valid, _ = ScriptParser.validate(items)
    meta = {item["type"]: item["text"] for item in items if item["type"] in ScriptParser.META_TYPES}
    if (not valid or not meta.get("video_format") or meta.get("video_title") != run["topic"]
            or resolve_video_type(meta["video_format"], meta.get("screen_format", "")) != run["video_type"]):
        raise AppError("E-AUTO-HOLD", "台本の形式・タイトル・動画種別の検証に失敗しました")
    return {"script": script}


def _generate_assets(run: dict, job: dict, cancel_event, log) -> dict:
    from core.disk_check import assert_enough_disk
    from core.license_manager import assert_can_generate
    from core.cta_policy import apply_topic_request_cta_policy_to_scripts
    from workers.runner import _run_generate, _result_error_message
    assert_can_generate(1)
    assert_enough_disk()
    prepared = apply_topic_request_cta_policy_to_scripts([run["script"]])
    result = _run_generate({**job, "params": {"script": prepared[0], "with_render": False}}, cancel_event, log)
    if cancel_event.is_set():
        raise AppError("E-AUTO-HOLD", "生成を停止しました")
    if _result_error_message(result) or not result.get("theme_dir"):
        raise AppError("E-AUTO-HOLD", "音声・画像の生成が完了しませんでした。ジョブログを確認してください")
    history_name = os.path.basename(result["theme_dir"])
    from web_app.security import find_history_dir
    from core.metadata_db import get_script_content, get_render_info
    if find_history_dir(history_name) is None or not get_script_content(history_name) or not get_render_info(history_name):
        raise AppError("E-AUTO-HOLD", "生成結果のDB保存を確認できませんでした")
    return {"history_name": history_name}


def _render(run: dict, job: dict, cancel_event, log) -> dict:
    from web_app.security import find_history_dir
    from workers.runner import _run_render
    theme_dir = find_history_dir(run["history_name"])
    if theme_dir is None:
        raise AppError("E-AUTO-HOLD", "生成フォルダが見つかりません")
    result = _run_render({**job, "params": {"history_name": run["history_name"], "theme_dir": theme_dir}}, cancel_event, log)
    if result.get("cancelled"):
        raise AppError("E-AUTO-HOLD", "レンダーを停止しました")
    if not os.path.isfile(result["output_path"]) or os.path.getsize(result["output_path"]) == 0:
        raise AppError("E-AUTO-HOLD", "MP4の実ファイルを確認できません")
    return {}


def _review(run: dict) -> dict:
    from config import config as cfg
    from core.metadata_db import get_script_content, get_render_info
    from core.opening_quality import _post_ollama, local_opening_review, duration_review
    from core.parser import ScriptParser
    from web_app.security import find_history_dir
    from web_app.services.upload_service import _find_mp4
    info = get_render_info(run["history_name"])
    script = get_script_content(run["history_name"])
    theme_dir = find_history_dir(run["history_name"])
    if not theme_dir or not script or not info:
        raise AppError("E-AUTO-HOLD", "品質判定に必要な成果物・台本・メタデータがありません")
    mp4 = _find_mp4(theme_dir)
    if not mp4 or not os.path.getsize(mp4):
        raise AppError("E-AUTO-HOLD", "完成MP4がありません")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", mp4],
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=cfg.NATIVE_FFPROBE_TIMEOUT_SEC)
    probe = json.loads(result.stdout)
    kinds = {s.get("codec_type") for s in probe.get("streams", [])}
    duration = float(probe["format"]["duration"])
    duration_result = duration_review(duration, run["video_type"] == "shorts", estimated=False)
    items = ScriptParser.parse_string(script)
    local = local_opening_review(items, info.get("video_title", ""), info.get("thumbnail_text", ""), run["video_type"] == "shorts")
    if not {"video", "audio"} <= kinds or duration <= 0 or duration_result["status"] in ("needs_review", "warning") or local.get("critical_errors"):
        raise AppError("E-AUTO-HOLD", "音声・映像・実尺・必須品質条件を満たしませんでした")
    prompt = ("次の台本を公開前に厳格に判定してください。事実と噂・創作の区別、説明密度、タイトルとの一致、誤解を招く断定を確認してください。\n"
              "映像は未視聴です。映像を確認したと主張せず、台本と以下の実測情報で判定してください。\n"
              f"タイトル: {info.get('video_title')}\n動画種別: {run['video_type']}\n実尺: {duration}\n台本:\n{script}\n"
              'JSONだけを出力: {"score":85,"publish_ok":true,"must_fix":[],"reason":"判定理由"}')
    review = _json_object(_post_ollama(prompt, cfg.OLLAMA_REVIEW_MODEL, json_only=True))
    store.update_run(run["run_id"], review_json=json.dumps(review, ensure_ascii=False))
    if (type(review.get("score")) is not int or not 0 <= review["score"] <= 100
            or review["score"] < run["policy"]["min_score"] or review.get("publish_ok") is not True
            or review.get("must_fix") != []):
        raise AppError("E-AUTO-HOLD", "公開品質基準を満たしませんでした。判定内容を確認してください")
    return {}


def _upload(run: dict, log) -> dict:
    from core.setup_state import require_setup_completed_for
    from core.license_manager import assert_can_upload
    from core.channel_info import get_channel_info
    from core.metadata_db import get_render_info, upsert_youtube_status
    from core.upload_scheduler import assign_slots_from_youtube
    from core.youtube_uploader import upload_video, get_video_statuses
    from web_app.security import find_history_dir
    from web_app.services.upload_service import _find_mp4
    require_setup_completed_for("自動投稿予約")
    assert_can_upload()
    if not get_channel_info()["upload_allowed"]:
        raise AppError("E-AUTO-CONFIG", "チャンネル設定が不足しています")
    store.assert_authorized(run)
    with ManagedConnection() as conn:
        known = conn.execute("SELECT youtube_video_id FROM youtube_status WHERE local_id=?", (run["history_name"],)).fetchone()
    if run["video_id"] or (known and known["youtube_video_id"]):
        raise AppError("E-AUTO-HOLD", "既存のYouTube動画IDがあるため再アップロードを停止しました")
    info = get_render_info(run["history_name"])
    theme_dir = find_history_dir(run["history_name"])
    if not theme_dir:
        raise AppError("E-AUTO-HOLD", "投稿対象の成果物が見つかりません")
    mp4 = _find_mp4(theme_dir)
    if not mp4:
        raise AppError("E-AUTO-HOLD", "投稿対象MP4が見つかりません")
    slots = assign_slots_from_youtube(1, run["video_type"])
    if not slots:
        raise AppError("E-AUTO-HOLD", "投稿予約枠が見つかりません")
    slot = slots[0]

    def record_uploaded(video_id):
        # サムネ設定などの後処理より先に、確定したIDを両方の正本へ残す。
        store.update_run(run["run_id"], video_id=video_id)
        with ManagedConnection() as conn:
            upsert_youtube_status(conn, run["history_name"], {
                "video_id": video_id, "publish_status": "private", "uploaded_at": store.now_iso(),
            })
            conn.commit()

    thumbnail = os.path.join(theme_dir, "thumbnails", "thumbnail.png")
    video_id = upload_video(mp4, info.get("video_title", ""), info.get("description", ""), info.get("tags") or [],
                            thumbnail_path=thumbnail if os.path.isfile(thumbnail) else None, publish_at=slot,
                            progress_callback=lambda message: log.add(message), on_uploaded=record_uploaded)
    actual = get_video_statuses([video_id]).get(video_id)
    if (not actual or actual.get("privacyStatus") != "private" or not actual.get("publishAt")
            or datetime.fromisoformat(actual["publishAt"].replace("Z", "+00:00")) != slot):
        raise AppError("E-AUTO-HOLD", "YouTube側の予約日時を確認できません。再アップロードせずStudioで確認してください")
    log.add(f"投稿予約を確認しました: video_id={video_id} / {slot.isoformat()}", "success")
    with ManagedConnection() as conn:
        upsert_youtube_status(conn, run["history_name"], {
            "video_id": video_id, "publish_status": "scheduled", "publish_at": slot.isoformat(), "uploaded_at": store.now_iso(),
        })
        conn.commit()
    return {"video_id": video_id}


def _assert_autopilot_license() -> None:
    from core.license_manager import assert_can_use_autopilot
    try:
        assert_can_use_autopilot()
    except RuntimeError as exc:
        raise AppError("E-LICENSE-LIMIT", str(exc)) from exc


def execute_step(job: dict, cancel_event, log) -> dict:
    """1工程だけ実行する。次工程登録は、結果確定後のrunner巡回に任せる。"""
    from web_app.job_manager import Job
    from web_app.services.analytics_service import _run_refresh
    run_id = job["params"]["run_id"]
    run = store.get_run(run_id)
    if run["job_id"] != job["job_id"] or run["state"] != "ready":
        raise AppError("E-AUTO-HOLD", "工程の所有権が一致しません")
    try:
        store.assert_authorized(run)
        _assert_autopilot_license()
        store.update_run(run_id, state="working")
        if cancel_event.is_set():
            raise AppError("E-AUTO-HOLD", "自動運用を停止しました")
        stage = run["stage"]
        log.add(f"自動運用: {run['day']} / {run['video_type']} {run['ordinal'] + 1}本目 / {stage}")
        updates = {}
        with budget_scope(require_active_profile().profile_id, run) as budget:
            if stage in ("analytics", "analysis"):
                _run_refresh(Job.from_dict(job))
            elif stage == "topic":
                updates = _choose_topic(run)
            elif stage == "script":
                updates = _write_script(run)
            elif stage == "generate":
                updates = _generate_assets(run, job, cancel_event, log)
            elif stage == "render":
                updates = _render(run, job, cancel_event, log)
            elif stage == "review":
                updates = _review(run)
            elif stage == "upload":
                updates = _upload(run, log)
            else:
                raise AppError("E-AUTO-HOLD", "運用工程が不正です")
            if budget.denied.is_set():
                raise AppError("E-AUTO-BUDGET")
        if cancel_event.is_set():
            raise AppError("E-AUTO-HOLD", "自動運用を停止しました")
        store.assert_authorized(run)
        next_stage = _STAGES[_STAGES.index(stage) + 1]
        store.update_run(run_id, **updates, stage=next_stage, state="complete" if next_stage == "complete" else "ready")
        return {"message": f"✅ 自動運用の工程完了: {stage}", "run_id": run_id, "next_stage": next_stage}
    except Exception as exc:
        _logger.error("自動運用の工程を保留: run=%s stage=%s", run_id, run["stage"], exc_info=True)
        message = exc.user_message() if isinstance(exc, AppError) else AppError("E-AUTO-HOLD").user_message()
        store.update_run(run_id, state="held", error=message)
        raise AppError("E-AUTO-HOLD", message) from exc
