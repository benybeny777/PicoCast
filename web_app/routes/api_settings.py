from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from datetime import datetime
from web_app.services.status_service import get_settings_status
from web_app.services.config_service import get_editable_config, save_config
from web_app.services.status_service import invalidate_settings_status_cache
from web_app.services.settings_preload_service import (
    get_cached_ollama_models,
    get_cached_bgm_files,
    invalidate_bgm_files_cache,
)
from web_app.services.secrets_service import (
    save_secrets,
    save_api_key,
    save_client_secrets,
    delete_api_key,
    delete_youtube_secret,
    get_secret_status,
    get_legacy_file_status,
    delete_legacy_file,
)
from web_app.routes.errors import raise_api_error

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status")
def api_settings_status():
    """設定診断。秘密値（APIキー本体）は返さない。"""
    return get_settings_status()


@router.post("/status/refresh")
def api_refresh_status():
    """サービスチェックを再実行してキャッシュを更新する。"""
    from web_app.services.status_service import refresh_settings_status
    return refresh_settings_status()


@router.post("/aquestalk/test")
def api_aquestalk_test():
    """AquesTalkの短いテスト音声を生成する。秘密値は返さない。"""
    try:
        from core.audio_backends import AudioSpeaker, generate_aquestalk_audio
        from core.channel_profile import get_active_profile
        from config import config

        profile = get_active_profile()
        profile_id = profile.profile_id if profile else None
        from core.runtime_env import app_base_dir
        out_dir = os.path.join(app_base_dir(), "dev", "aquestalk_tests")  # 書き込み先。exe では exe 隣
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"reimu_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
        speaker = AudioSpeaker(
            backend="aquestalk",
            speaker=getattr(config, "AQUESTALK_REIMU_SPEAKER_KEY", "yukkuri_reimu"),
            voice_type=getattr(config, "AQUESTALK_REIMU_VOICE_TYPE", "reimu"),
            speed=config.AQUESTALK_DEFAULT_SPEED,
            pitch=config.AQUESTALK_DEFAULT_PITCH,
            volume=config.AQUESTALK_DEFAULT_VOLUME,
            character_name="霊夢",
        )
        generate_aquestalk_audio(
            text=config.AQUESTALK_TEST_TEXT,
            speaker=speaker,
            output_path=out_path,
            profile_id=profile_id,
        )
        return {"ok": True, "path": out_path}
    except Exception as exc:
        raise_api_error(exc, status_code=422, action="AquesTalkテスト音声生成")


@router.get("/config")
def api_get_config():
    """編集可能な設定項目と現在値を返す。"""
    return get_editable_config()


@router.get("/runtime/log-poll-interval")
def api_get_log_poll_interval():
    """ログ画面が再起動・再読み込みなしで現在の更新間隔を取得する。"""
    from config import config
    return {"interval_ms": int(config.WEB_LOG_POLL_INTERVAL_MS)}


@router.post("/config")
def api_save_config(updates: dict[str, str]):
    """設定を DB に保存し、可能なものは現在プロセスへ反映する。"""
    errors = save_config(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_bgm_files_cache()
    return {"saved": list(updates.keys()), "note": "保存しました。"}


@router.get("/output-base")
def api_get_output_base():
    """現在の出力ベースディレクトリ・既定値・カスタム指定かを返す。"""
    from web_app.services.output_dir_service import get_output_base_info
    return get_output_base_info()


class OutputBaseRequest(BaseModel):
    path: str
    confirmed: bool = False
    move: bool = True


@router.post("/output-base")
def api_change_output_base(req: OutputBaseRequest):
    """出力ベースディレクトリを変更し既存データを移動する。confirmed=true 必須。

    実行中/待機中ジョブがある場合は 409 で拒否する。
    """
    from web_app.services.output_dir_service import change_output_base
    try:
        result = change_output_base(req.path, confirmed=req.confirmed, move=req.move)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    invalidate_settings_status_cache()
    return result


@router.get("/fixed-comment-task")
def api_fixed_comment_task_status():
    """固定コメント自動投稿タスク（OSスケジューラ）の登録状態と不整合(stale/orphans)を返す。"""
    from core.fixed_comment_task import inspect
    return inspect()


@router.post("/fixed-comment-task/repair")
def api_fixed_comment_task_repair():
    """exe 移動などで生じたタスクのズレ・迷子を修正する（再登録＋迷子削除）。"""
    from core.fixed_comment_task import repair
    try:
        return repair()
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class FixedCommentTaskRequest(BaseModel):
    enabled: bool


@router.post("/fixed-comment-task")
def api_fixed_comment_task(req: FixedCommentTaskRequest):
    """固定コメント自動投稿タスクを登録/解除する。

    アプリ非起動でも、予約スロット時刻に未投稿の固定コメントを投稿する OS タスクを作る。
    """
    from core.fixed_comment_task import register, unregister
    try:
        return register() if req.enabled else unregister()
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/secrets")
def api_save_secrets(updates: dict[str, str]):
    """APIキーを DB へ暗号化保存する（後方互換エンドポイント）。値はレスポンスに含めない。"""
    errors = save_secrets(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"saved": list(updates.keys())}


# ── 認証情報管理エンドポイント ────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    secret_type: str
    value: str
    profile_id: str | None = None


class ClientSecretsRequest(BaseModel):
    json_text: str
    profile_id: str | None = None


class DeleteSecretRequest(BaseModel):
    secret_type: str
    profile_id: str | None = None
    confirmed: bool = False


class DeleteLegacyFileRequest(BaseModel):
    filename: str
    confirmed: bool = False


@router.get("/secrets/status")
def api_secret_status(profile_id: str | None = None):
    """各シークレットの登録状態を返す（値は一切返さない）。"""
    db_status = get_secret_status(profile_id=profile_id)
    legacy_status = get_legacy_file_status()
    return {
        "secrets": db_status,
        "legacy_files": legacy_status,
    }


@router.post("/secrets/api-key")
def api_save_api_key(req: ApiKeyRequest):
    """APIキー（google_api_key / openai_api_key / hf_token）を DB へ暗号化保存する。"""
    errors = save_api_key(req.secret_type, req.value, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"saved": req.secret_type, "profile_id": req.profile_id}


@router.post("/secrets/client-secrets")
def api_save_client_secrets(req: ClientSecretsRequest):
    """YouTube client_secrets JSON を DB へ暗号化保存する。"""
    errors = save_client_secrets(req.json_text, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"saved": "youtube_client_secrets", "profile_id": req.profile_id}


@router.delete("/secrets/api-key")
def api_delete_api_key(req: DeleteSecretRequest):
    """APIキーを DB から削除する。confirmed=true 必須。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    errors = delete_api_key(req.secret_type, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"deleted": req.secret_type}


@router.delete("/secrets/youtube")
def api_delete_youtube_secret(req: DeleteSecretRequest):
    """YouTube シークレットを DB から削除する。confirmed=true 必須。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    errors = delete_youtube_secret(req.secret_type, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"deleted": req.secret_type, "profile_id": req.profile_id}


@router.delete("/secrets/legacy-file")
def api_delete_legacy_file(req: DeleteLegacyFileRequest):
    """
    旧認証ファイルを削除する。
    confirmed=true 必須。DB 未移行の値がある場合は拒否する。
    """
    result = delete_legacy_file(req.filename, confirmed=req.confirmed)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "削除失敗"))
    return result


@router.get("/bgm-files")
def api_bgm_files():
    """assets/bgm/ 内の音声ファイル一覧を返す。"""
    return get_cached_bgm_files()


class ReadingDictEntry(BaseModel):
    word: str
    reading: str


@router.get("/reading-dict")
def api_get_reading_dict():
    """よみがな辞書（同梱・ユーザー）を返す。"""
    from core import reading_dictionary_store
    data = reading_dictionary_store.load_all()
    entries = []
    for dict_type, values in data.items():
        for word, reading in values.items():
            entries.append({"dict_type": dict_type, "word": word, "reading": reading})
    entries.sort(key=lambda x: (x["dict_type"], x["word"]))
    return {"base": data["base"], "user": data["user"], "entries": entries}


@router.post("/reading-dict/base")
def api_add_reading_dict_base(entry: ReadingDictEntry):
    """同梱辞書にエントリを追加/上書きする。"""
    from core import reading_dictionary_store
    word = entry.word.strip()
    reading = entry.reading.strip()
    if not word or not reading:
        raise HTTPException(status_code=422, detail="word と reading は必須です")
    reading_dictionary_store.upsert_entry("base", word, reading)
    return {"saved": word, "reading": reading}


@router.delete("/reading-dict/base/{word:path}")
def api_delete_reading_dict_base(word: str):
    """同梱辞書からエントリを削除する。"""
    from core import reading_dictionary_store
    if not reading_dictionary_store.delete_entry("base", word):
        raise HTTPException(status_code=404, detail=f"'{word}' が辞書にありません")
    return {"deleted": word}


@router.delete("/reading-dict/user/{word:path}")
def api_delete_reading_dict_user(word: str):
    """ユーザー辞書からエントリを削除する。"""
    from core import reading_dictionary_store
    if not reading_dictionary_store.delete_entry("user", word):
        raise HTTPException(status_code=404, detail=f"'{word}' が辞書にありません")
    return {"deleted": word}


@router.get("/debug-log")
def api_debug_log():
    """デバッグログの末尾行を返す。"""
    from web_app.services.debug_log_service import recent_debug_log
    return recent_debug_log()


@router.get("/ollama-models")
def api_ollama_models():
    """Ollama が起動していれば利用可能なモデル一覧を返す。"""
    return get_cached_ollama_models()


class LicenseRequest(BaseModel):
    edition: str
    license_id: str = ""


class SetupCompleteRequest(BaseModel):
    completed: bool = True


class BackupRequest(BaseModel):
    passphrase: str = ""


class RestoreBackupRequest(BaseModel):
    backup_path: str
    confirmed: bool = False
    passphrase: str = ""


@router.get("/legal-consent")
def api_legal_consent_status():
    """法務文書（利用規約・EULA・プライバシーポリシー）への同意状態を返す。"""
    from core.legal_consent import consent_status
    return consent_status()


@router.post("/legal-consent")
def api_accept_legal_consent():
    """法務文書への同意を記録する。"""
    from core.legal_consent import accept_consent
    return accept_consent()


@router.get("/setup")
def api_setup_status():
    """初回セットアップ状態を返す。"""
    from core.setup_state import setup_gate_status
    return setup_gate_status()


@router.get("/setup-readiness")
def api_setup_readiness():
    """セットアップ完了に必要な最小構成（チャンネル/VOICEVOX/ffmpeg）の充足状況を返す。"""
    from web_app.services.status_service import setup_readiness
    return setup_readiness()


@router.post("/setup")
def api_setup_complete(req: SetupCompleteRequest):
    """初回セットアップ完了状態を保存する。完了には法務文書への同意が必須。"""
    from core.setup_state import set_setup_completed, setup_gate_status
    if req.completed:
        from core.legal_consent import is_consent_accepted
        if not is_consent_accepted():
            raise HTTPException(status_code=422, detail="先に利用規約・使用許諾（EULA）・プライバシーポリシーへの同意が必要です。")
        from web_app.services.status_service import setup_readiness
        readiness = setup_readiness()
        if not readiness["ready"]:
            raise HTTPException(status_code=422, detail="セットアップ完了に必要な項目が未完了です：\n- " + "\n- ".join(readiness["missing"]))
    set_setup_completed(req.completed)
    return setup_gate_status()


@router.get("/product-info")
def api_product_info():
    """サポート問い合わせ先・更新確認の有効状態など製品情報を返す（秘密値なし）。"""
    from config import config
    from core.update_check import is_update_check_enabled
    from core.gui_support import build_app_version
    return {
        "app_version": build_app_version(),
        "support_url": (config.PRODUCT_SUPPORT_URL or "").strip(),
        "support_email": (config.PRODUCT_SUPPORT_EMAIL or "").strip(),
        "update_check_enabled": is_update_check_enabled(),
    }


@router.post("/check-update")
def api_check_update():
    """更新確認を実行する。URL未設定時はネットワークアクセスしない。"""
    from core.update_check import check_for_update
    return check_for_update()


@router.get("/license")
def api_license_status():
    """ライセンス状態を返す。購入者情報や秘密値は返さない。"""
    from core.license_manager import get_license_info
    return get_license_info()


@router.post("/license")
def api_save_license(req: LicenseRequest):
    """ライセンス edition を保存する。"""
    try:
        from core.license_manager import save_license
        return save_license(req.edition, req.license_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/diagnostics")
def api_create_diagnostics():
    """秘密情報を含めない診断パッケージを作成する。"""
    from web_app.services.diagnostics_service import create_diagnostics_package
    return create_diagnostics_package()


@router.post("/backup")
def api_create_backup(req: BackupRequest | None = None):
    """settings.db と profile 別 metadata.db のバックアップを作成する。

    passphrase を指定すると認証情報を再暗号化して同梱し、別PCでも復元できる。
    """
    from web_app.services.backup_service import create_backup
    passphrase = req.passphrase if req else ""
    return create_backup(passphrase=passphrase)


@router.post("/restore")
def api_restore_backup(req: RestoreBackupRequest):
    """バックアップZIPから復元する。confirmed=true 必須。

    認証情報を同梱したバックアップは passphrase を指定して別PCでも復元できる。
    """
    try:
        from web_app.services.backup_service import restore_backup
        return restore_backup(req.backup_path, confirmed=req.confirmed, passphrase=req.passphrase)
    except Exception as exc:
        raise_api_error(exc, status_code=422, action="バックアップ復元")


class ApplyDetectedRequest(BaseModel):
    config: dict


@router.post("/detect-services")
def api_detect_services():
    """起動中プロセス・既知ポートから VOICEVOX / Ollama / Stable Diffusion WebUI / ffmpeg を走査する。"""
    from core.service_detector import detect_services
    return detect_services()


@router.post("/detect-services/apply")
def api_apply_detected_services(req: ApplyDetectedRequest):
    """走査で得たパス/URLを設定へ適用する。"""
    from core.service_detector import apply_detected
    errors = apply_detected(req.config)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return {"applied": {k: v for k, v in req.config.items()}}
