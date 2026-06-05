"""
設定 DB（data/settings.db）による設定管理サービス。
APIキー・トークンなど認証情報は対象外（encrypted_secrets で管理）。
一部設定は保存直後に現在プロセスへ反映する。
"""
import os
import logging
from typing import Any
from config import config as cfg

_logger = logging.getLogger(__name__)

# 編集可能な設定項目の定義（秘密値は含めない）
EDITABLE_CONFIG: list[dict[str, Any]] = [
    # ── VOICEVOX ──
    {"key": "VOICEVOX_PATH",                   "type": "str",   "label": "VOICEVOX 実行ファイルパス (空=手動起動)", "default": str(cfg.VOICEVOX_PATH), "allow_empty": True,           "group": "VOICEVOX"},
    {"key": "VOICEVOX_URL",                    "type": "str",   "label": "VOICEVOX API URL",                       "default": str(cfg.VOICEVOX_URL),                                  "group": "VOICEVOX"},
    {"key": "VOICEVOX_CONNECTION_TIMEOUT_SEC", "type": "float", "label": "VOICEVOX 接続タイムアウト(秒)",          "default": str(cfg.VOICEVOX_CONNECTION_TIMEOUT_SEC), "min": 0.5, "max": 30.0,  "group": "タイムアウト", "admin": True},
    {"key": "VOICEVOX_QUERY_TIMEOUT_SEC",      "type": "float", "label": "VOICEVOX クエリタイムアウト(秒)",        "default": str(cfg.VOICEVOX_QUERY_TIMEOUT_SEC),      "min": 1.0, "max": 60.0,  "group": "タイムアウト", "admin": True},
    {"key": "VOICEVOX_SYNTHESIS_TIMEOUT_SEC",  "type": "float", "label": "VOICEVOX 合成タイムアウト(秒)",          "default": str(cfg.VOICEVOX_SYNTHESIS_TIMEOUT_SEC),  "min": 5.0, "max": 300.0, "group": "タイムアウト", "admin": True},
    {"key": "VOICEVOX_QUERY_WORKERS",         "type": "int",   "label": "VOICEVOX クエリ並列数",                   "default": str(cfg.VOICEVOX_QUERY_WORKERS),          "min": 1,   "max": 16,             "group": "VOICEVOX"},
    {"key": "VOICEVOX_SYNTH_WORKERS",         "type": "int",   "label": "VOICEVOX 合成並列数",                     "default": str(cfg.VOICEVOX_SYNTH_WORKERS),          "min": 1,   "max": 16,             "group": "VOICEVOX"},
    # ── AquesTalk ──
    {"key": "AQUESTALK_ENABLED",              "type": "bool",  "label": "AquesTalk有効",                           "default": "1" if cfg.AQUESTALK_ENABLED else "0",                                                "group": "AquesTalk"},
    {"key": "AQUESTALK_ENGINE_PATH",          "type": "str",   "label": "AquesTalkエンジン/ラッパーCLIパス",        "default": str(cfg.AQUESTALK_ENGINE_PATH),                    "allow_empty": True,             "group": "AquesTalk"},
    {"key": "AQUESTALK_LICENSE_CONFIRMED",    "type": "bool",  "label": "A-Quest公式ライセンス確認済み",             "default": "1" if cfg.AQUESTALK_LICENSE_CONFIRMED else "0",                                      "group": "AquesTalk"},
    {"key": "AQUESTALK_COMMAND_TEMPLATE",     "type": "str",   "label": "AquesTalkコマンドテンプレート",             "default": str(cfg.AQUESTALK_COMMAND_TEMPLATE),                                                   "group": "AquesTalk"},
    {"key": "AQUESTALK_DEFAULT_SPEED",        "type": "int",   "label": "AquesTalk既定速度",                       "default": str(cfg.AQUESTALK_DEFAULT_SPEED),       "min": 50, "max": 300,                 "group": "AquesTalk"},
    {"key": "AQUESTALK_DEFAULT_PITCH",        "type": "int",   "label": "AquesTalk既定高さ",                       "default": str(cfg.AQUESTALK_DEFAULT_PITCH),       "min": 50, "max": 300,                 "group": "AquesTalk"},
    {"key": "AQUESTALK_DEFAULT_VOLUME",       "type": "int",   "label": "AquesTalk既定音量",                       "default": str(cfg.AQUESTALK_DEFAULT_VOLUME),      "min": 0,  "max": 300,                 "group": "AquesTalk"},
    {"key": "AQUESTALK_TIMEOUT_SEC",          "type": "float", "label": "AquesTalk生成タイムアウト(秒)",             "default": str(cfg.AQUESTALK_TIMEOUT_SEC),         "min": 1,  "max": 300, "group": "タイムアウト", "admin": True},
    # ── 画像生成 ──
    {"key": "NANOBANANA_BG_WORKERS",          "type": "int",   "label": "Nano Banana 背景生成並列数",               "default": str(cfg.NANOBANANA_BG_WORKERS),           "min": 1,   "max": 10,             "group": "画像生成"},
    # ── 音声生成 ──
    {"key": "NATIVE_SHORTS_BODY_VOICE_SPEED",  "type": "float", "label": "Shorts 本編音声速度",       "default": str(cfg.NATIVE_SHORTS_BODY_VOICE_SPEED),  "min": 0.5, "max": 3.0, "group": "音声生成"},
    {"key": "NATIVE_SHORTS_INTRO_VOICE_SPEED", "type": "float", "label": "Shorts 冒頭音声速度",       "default": str(cfg.NATIVE_SHORTS_INTRO_VOICE_SPEED), "min": 0.5, "max": 3.0, "group": "音声生成"},
    {"key": "NATIVE_LONG_BODY_VOICE_SPEED",    "type": "float", "label": "Long 本編音声速度",          "default": str(cfg.NATIVE_LONG_BODY_VOICE_SPEED),    "min": 0.5, "max": 3.0, "group": "音声生成"},
    {"key": "NATIVE_LONG_INTRO_VOICE_SPEED",   "type": "float", "label": "Long 冒頭音声速度",          "default": str(cfg.NATIVE_LONG_INTRO_VOICE_SPEED),   "min": 0.5, "max": 3.0, "group": "音声生成"},
    # ── BGM ──
    {"key": "BGM_FILE",                        "type": "bgm_file", "label": "BGMファイル",             "default": str(cfg.BGM_FILE),                                              "group": "BGM"},
    {"key": "NATIVE_BGM_VOLUME_DB",            "type": "float",    "label": "BGM音量(dB)",             "default": str(cfg.NATIVE_BGM_VOLUME_DB),             "min": -60, "max": 0, "group": "BGM"},
    # ── エフェクト ──
    {"key": "NATIVE_ENABLE_MOTION_EFFECTS",    "type": "bool",  "label": "Shorts軽量エフェクト全体",   "default": "1" if cfg.NATIVE_ENABLE_MOTION_EFFECTS   else "0", "group": "エフェクト"},
    {"key": "NATIVE_ENABLE_BG_KEN_BURNS",      "type": "bool",  "label": "背景ズーム/パン",            "default": "1" if cfg.NATIVE_ENABLE_BG_KEN_BURNS     else "0", "group": "エフェクト"},
    {"key": "NATIVE_ENABLE_CHARACTER_BOUNCE",  "type": "bool",  "label": "キャラバウンス",             "default": "1" if cfg.NATIVE_ENABLE_CHARACTER_BOUNCE else "0", "group": "エフェクト"},
    {"key": "NATIVE_ENABLE_POP_TELOP",         "type": "bool",  "label": "テロップポップ",             "default": "1" if cfg.NATIVE_ENABLE_POP_TELOP        else "0", "group": "エフェクト"},
    {"key": "NATIVE_ENABLE_SHAKE",             "type": "bool",  "label": "ツッコミ/驚きシェイク",      "default": "1" if cfg.NATIVE_ENABLE_SHAKE            else "0", "group": "エフェクト"},
    {"key": "NATIVE_MAX_SHAKE_COUNT_SHORTS",   "type": "int",   "label": "シェイク上限 (Shorts)",      "default": str(cfg.NATIVE_MAX_SHAKE_COUNT_SHORTS),   "min": 0, "max": 10,  "group": "エフェクト"},
    {"key": "NATIVE_MAX_ICON_COUNT_SHORTS",    "type": "int",   "label": "疑問/驚きアイコン上限",      "default": str(cfg.NATIVE_MAX_ICON_COUNT_SHORTS),    "min": 0, "max": 10,  "group": "エフェクト"},
    {"key": "NATIVE_BG_ZOOM_MAX",              "type": "float", "label": "背景ズーム最大倍率",          "default": str(cfg.NATIVE_BG_ZOOM_MAX),              "min": 1.0, "max": 1.2, "group": "エフェクト"},
    {"key": "MAX_BACKGROUNDS_SHORTS",          "type": "int",   "label": "最大背景枚数 (Shorts)",      "default": str(cfg.MAX_BACKGROUNDS_SHORTS),          "min": 1, "max": 30,   "group": "エフェクト"},
    {"key": "MAX_BACKGROUNDS_LONG",            "type": "int",   "label": "最大背景枚数 (Long)",         "default": str(cfg.MAX_BACKGROUNDS_LONG),            "min": 1, "max": 200,  "group": "エフェクト"},
    {"key": "MAX_BACKGROUNDS_LONG_BUDGET",     "type": "int",   "label": "最大背景枚数 (Long節約)",     "default": str(cfg.MAX_BACKGROUNDS_LONG_BUDGET),     "min": 1, "max": 50,   "group": "エフェクト"},
    # ── YouTube ──
    {"key": "LONG_UPLOAD_PLAYLIST_NAME",       "type": "str",  "label": "Long追加先再生リスト名",      "default": str(cfg.LONG_UPLOAD_PLAYLIST_NAME), "allow_empty": True,           "group": "YouTube"},
    {"key": "TOPIC_REQUEST_CTA_EVERY_N",       "type": "int",  "label": "ネタ募集CTA間隔 (0=OFF)",     "default": str(cfg.TOPIC_REQUEST_CTA_EVERY_N), "min": 0, "max": 100,         "group": "YouTube"},
    {"key": "AUTO_FIXED_COMMENT_PROFILE_SCOPE","type": "select","label": "固定コメント 自動投稿対象（OSタスク）",    "default": str(cfg.AUTO_FIXED_COMMENT_PROFILE_SCOPE), "choices": [("all", "全チャンネル"), ("active", "アクティブのみ")], "group": "YouTube"},
    # ── AI / 画像生成 ──
    {"key": "GEMINI_MODEL",                    "type": "str",          "label": "Gemini 台本生成モデル",            "default": str(cfg.GEMINI_MODEL),                                                                                                                     "group": "AI / 画像生成"},
    {"key": "NANOBANANA_PRO_MODEL",            "type": "str",          "label": "画像生成モデル(高品質)",           "default": str(cfg.NANOBANANA_PRO_MODEL),                                                                                                             "group": "AI / 画像生成"},
    {"key": "NANOBANANA_FLASH_MODEL",          "type": "str",          "label": "画像生成モデル(高速)",             "default": str(cfg.NANOBANANA_FLASH_MODEL),                                                                                                           "group": "AI / 画像生成"},
    {"key": "IMAGE_BACKEND",                   "type": "select",       "label": "画像生成バックエンド",             "default": str(cfg.IMAGE_BACKEND), "choices": [("gemini", "Gemini / Nano Banana"), ("sd_webui", "Stable Diffusion WebUI / A1111")],                             "group": "AI / 画像生成"},
    {"key": "OLLAMA_BASE_URL",                 "type": "str",          "label": "Ollama API URL",                 "default": str(cfg.OLLAMA_BASE_URL),                                                                                                                  "group": "AI / 画像生成"},
    {"key": "OPENING_REVIEW_USE_LLM",          "type": "bool",         "label": "Ollama レビュー有効",             "default": "1" if cfg.OPENING_REVIEW_USE_LLM else "0",                                                                                                "group": "AI / 画像生成"},
    {"key": "OLLAMA_REVIEW_MODEL",             "type": "ollama_model", "label": "Ollama レビューモデル",           "default": str(cfg.OLLAMA_REVIEW_MODEL),                                                                                                              "group": "AI / 画像生成"},
    {"key": "OLLAMA_REWRITE_MODEL",            "type": "ollama_model", "label": "Ollama リライトモデル",           "default": str(cfg.OLLAMA_REWRITE_MODEL),                                                                                                             "group": "AI / 画像生成"},
    {"key": "OLLAMA_REWRITE_FALLBACK_MODEL",   "type": "ollama_model", "label": "Ollama リライト fallback モデル", "default": str(cfg.OLLAMA_REWRITE_FALLBACK_MODEL),                                                                                                    "group": "AI / 画像生成"},
    {"key": "OPENAI_FINAL_REVIEW_ENABLED",     "type": "bool",         "label": "ChatGPT 最終レビュー有効",        "default": "1" if cfg.OPENAI_FINAL_REVIEW_ENABLED else "0",                                                                                           "group": "AI / 画像生成"},
    {"key": "OPENAI_FINAL_REVIEW_MODEL",       "type": "str",          "label": "ChatGPT 最終レビューモデル",      "default": str(cfg.OPENAI_FINAL_REVIEW_MODEL),                                                                                                        "group": "AI / 画像生成"},
    # ── Stable Diffusion WebUI ──
    {"key": "SD_WEBUI_BASE_URL",          "type": "str",   "label": "Stable Diffusion WebUI API URL",                        "default": str(cfg.SD_WEBUI_BASE_URL),                                      "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_TIMEOUT_SEC",       "type": "int",   "label": "Stable Diffusion WebUI タイムアウト(秒)",               "default": str(cfg.SD_WEBUI_TIMEOUT_SEC),   "min": 10,  "max": 3600,        "group": "タイムアウト", "admin": True},
    {"key": "SD_WEBUI_MODEL",             "type": "str",   "label": "Stable Diffusion WebUI モデル名 (空=現在のモデル)",      "default": str(cfg.SD_WEBUI_MODEL),         "allow_empty": True,             "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_SAMPLER",           "type": "str",   "label": "Stable Diffusion WebUI サンプラー",                     "default": str(cfg.SD_WEBUI_SAMPLER),                                       "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_STEPS",             "type": "int",   "label": "Stable Diffusion WebUI ステップ数",                     "default": str(cfg.SD_WEBUI_STEPS),         "min": 1,   "max": 150,         "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_CFG_SCALE",         "type": "float", "label": "Stable Diffusion WebUI CFGスケール",                    "default": str(cfg.SD_WEBUI_CFG_SCALE),     "min": 1.0, "max": 30.0,        "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_WIDTH",             "type": "int",   "label": "Stable Diffusion WebUI 出力幅(px)",                     "default": str(cfg.SD_WEBUI_WIDTH),         "min": 64,  "max": 2048,        "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_HEIGHT",            "type": "int",   "label": "Stable Diffusion WebUI 出力高さ(px)",                   "default": str(cfg.SD_WEBUI_HEIGHT),        "min": 64,  "max": 2048,        "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_NEGATIVE_PROMPT",   "type": "str",   "label": "Stable Diffusion WebUI ネガティブプロンプト",           "default": str(cfg.SD_WEBUI_NEGATIVE_PROMPT),                               "group": "Stable Diffusion WebUI"},
    {"key": "SD_WEBUI_ROOT",              "type": "str",   "label": "Stable Diffusion WebUI インストールディレクトリ",        "default": str(cfg.SD_WEBUI_ROOT),          "allow_empty": True,             "group": "Stable Diffusion WebUI"},
    {"key": "SD_MODEL_MANIFEST_PATH",     "type": "str",   "label": "モデルマニフェストパス",                      "default": str(cfg.SD_MODEL_MANIFEST_PATH),                                 "group": "Stable Diffusion WebUI"},
    {"key": "AUTO_DOWNLOAD_SD_MODELS",    "type": "bool",  "label": "モデル自動ダウンロード",                      "default": "1" if cfg.AUTO_DOWNLOAD_SD_MODELS else "0",                     "group": "Stable Diffusion WebUI"},
    # ── よみがな ──
    {"key": "VOICE_READING_MODE",         "type": "select", "label": "よみがな補正モード", "default": str(cfg.VOICE_READING_MODE), "choices": [("off", "無効 (off)"), ("dictionary", "自前辞書のみ (dictionary)"), ("safe_auto", "安全自動補正 (safe_auto)")], "group": "よみがな"},
    # ── Web UI ──
    {"key": "WEB_APP_NAME",                       "type": "str",   "label": "Web UI 表示名",             "default": str(cfg.WEB_APP_NAME),                                              "group": "Web UI", "admin": True},
    {"key": "WEB_AUTO_OPEN_BROWSER",              "type": "bool",  "label": "起動時にブラウザを自動で開く", "default": "1" if cfg.WEB_AUTO_OPEN_BROWSER else "0",                         "group": "Web UI"},
    {"key": "WEB_DEFAULT_IMAGE_STYLE",            "type": "str",   "label": "Web既定画像スタイル",        "default": str(cfg.WEB_DEFAULT_IMAGE_STYLE),                                   "group": "Web UI"},
    {"key": "WEB_IMAGE_STYLE_CHOICES",            "type": "str",   "label": "Web画像スタイル選択肢",      "default": ",".join(cfg.WEB_IMAGE_STYLE_CHOICES),                              "group": "Web UI"},
    {"key": "WEB_DEFAULT_REUSE_BACKGROUNDS",      "type": "bool",  "label": "Web既定: 背景再利用",        "default": "1" if cfg.WEB_DEFAULT_REUSE_BACKGROUNDS          else "0",         "group": "Web UI"},
    {"key": "WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST", "type": "bool",  "label": "Web既定: LongサムネAB",     "default": "1" if cfg.WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST     else "0",         "group": "Web UI"},
    {"key": "WEB_DEFAULT_LONG_BUDGET_MODE",       "type": "bool",  "label": "Web既定: Long節約",          "default": "1" if cfg.WEB_DEFAULT_LONG_BUDGET_MODE           else "0",         "group": "Web UI"},
    {"key": "WEB_JOB_POLL_INTERVAL_MS",           "type": "int",   "label": "Webジョブ更新間隔(ms)",      "default": str(cfg.WEB_JOB_POLL_INTERVAL_MS),    "min": 500,  "max": 30000,    "group": "Web UI"},
    {"key": "WEB_LOG_POLL_INTERVAL_MS",           "type": "int",   "label": "ログ画面 更新間隔(ms)（長いほどコピペしやすい）", "default": str(cfg.WEB_LOG_POLL_INTERVAL_MS), "min": 1000, "max": 60000, "group": "Web UI"},
    {"key": "WEB_SUCCESS_RELOAD_DELAY_MS",        "type": "int",   "label": "Web成功後再読み込み待ち(ms)", "default": str(cfg.WEB_SUCCESS_RELOAD_DELAY_MS), "min": 0,    "max": 10000,    "group": "Web UI", "admin": True},
    {"key": "WEB_TOAST_VISIBLE_MS",               "type": "int",   "label": "Webトースト表示時間(ms)",    "default": str(cfg.WEB_TOAST_VISIBLE_MS),        "min": 500,  "max": 10000,    "group": "Web UI", "admin": True},
    {"key": "WEB_TOAST_HIDE_DELAY_MS",            "type": "int",   "label": "Webトースト非表示待ち(ms)",  "default": str(cfg.WEB_TOAST_HIDE_DELAY_MS),     "min": 0,    "max": 3000,     "group": "Web UI", "admin": True},
    {"key": "WEB_VOICEVOX_CHECK_TIMEOUT_SEC",     "type": "float", "label": "VOICEVOX確認タイムアウト(秒)", "default": str(cfg.WEB_VOICEVOX_CHECK_TIMEOUT_SEC), "min": 0.2, "max": 30,    "group": "タイムアウト", "admin": True},
    {"key": "WEB_FFMPEG_CHECK_TIMEOUT_SEC",       "type": "float", "label": "ffmpeg確認タイムアウト(秒)",   "default": str(cfg.WEB_FFMPEG_CHECK_TIMEOUT_SEC),   "min": 0.2, "max": 30,    "group": "タイムアウト", "admin": True},
    # ── 管理者設定 ──
    {"key": "JOB_MAX_CONCURRENT_WORKERS",          "type": "int",   "label": "生成・レンダー同時実行数",       "default": str(cfg.JOB_MAX_CONCURRENT_WORKERS),          "min": 1,    "max": int(cfg.JOB_RUNNER_EXECUTOR_CAPACITY), "group": "ジョブ実行", "admin": True},
    {"key": "JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC",    "type": "float", "label": "runner停止判定タイムアウト(秒)", "default": str(cfg.JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC),    "min": 10.0, "max": 600.0, "group": "タイムアウト", "admin": True},
    {"key": "JOB_LOG_MAX_JOBS",                    "type": "int",   "label": "ジョブ履歴保持件数",             "default": str(cfg.JOB_LOG_MAX_JOBS),                    "min": 50,   "max": 5000,  "group": "ジョブログ", "admin": True},
    {"key": "JOB_LOG_MAX_ENTRIES",                 "type": "int",   "label": "1ジョブのログ保持行数",          "default": str(cfg.JOB_LOG_MAX_ENTRIES),                 "min": 100,  "max": 20000, "group": "ジョブログ", "admin": True},
    # ── ffmpeg ──
    {"key": "FFMPEG_BIN",                  "type": "str",   "label": "ffmpeg バイナリパス",           "default": str(cfg.FFMPEG_BIN),                                           "group": "ffmpeg"},
    {"key": "NATIVE_FFMPEG_TIMEOUT_SEC",   "type": "float", "label": "ffmpegタイムアウト(秒)",        "default": str(cfg.NATIVE_FFMPEG_TIMEOUT_SEC),  "min": 30,  "max": 7200,  "group": "タイムアウト", "admin": True},
    {"key": "NATIVE_FFPROBE_TIMEOUT_SEC",  "type": "float", "label": "ffprobeタイムアウト(秒)",       "default": str(cfg.NATIVE_FFPROBE_TIMEOUT_SEC), "min": 5,   "max": 300,   "group": "タイムアウト", "admin": True},
]

_ALLOWED_KEYS = {item["key"] for item in EDITABLE_CONFIG}
_ADMIN_KEYS = {item["key"] for item in EDITABLE_CONFIG if item.get("admin")}


def developer_tools_enabled() -> bool:
    """開発者向け機能（管理者設定など）を表示/許可するか。販売版では False。"""
    return bool(getattr(cfg, "DEVELOPER_TOOLS_ENABLED", True))


def get_editable_config() -> list[dict[str, Any]]:
    """現在値付きの設定項目リストを返す。販売版では admin 項目を除外する。"""
    from core.settings_store import get_all as _db_get_all
    db_values = _db_get_all()
    include_admin = developer_tools_enabled()
    result = []
    for item in EDITABLE_CONFIG:
        if item.get("admin") and not include_admin:
            continue
        key = item["key"]
        raw = getattr(cfg, key, None)
        if raw is None:
            raw = db_values.get(key, item["default"])
        if isinstance(raw, bool):
            current_str = "1" if raw else "0"
        elif isinstance(raw, (tuple, list)):
            current_str = ",".join(str(v) for v in raw)
        else:
            current_str = str(raw)
        result.append({**item, "current": current_str})
    return result


def save_config(updates: dict[str, str]) -> list[str]:
    """
    更新値を検証して設定 DB に書き込む。
    戻り値: バリデーションエラーのリスト（空なら成功）
    """
    if not developer_tools_enabled():
        blocked = [k for k in updates if k in _ADMIN_KEYS]
        if blocked:
            return [f"管理者設定は無効化されています（販売版）: {', '.join(blocked)}"]
    errors = _validate(updates)
    if errors:
        return errors

    from core.settings_store import set_many as _db_set_many
    safe_updates = {_key: _normalize_update_value(_key, _value) for _key, _value in updates.items() if _key in _ALLOWED_KEYS}
    _db_set_many(safe_updates)
    _apply_runtime_updates(safe_updates)
    return []


def _normalize_update_value(key: str, value: str) -> str:
    if key == "WEB_IMAGE_STYLE_CHOICES":
        return ",".join(cfg._split_env_choices(value))
    if key == "WEB_DEFAULT_IMAGE_STYLE":
        return cfg._clean_env_choice(value)
    if key in {"AQUESTALK_ENGINE_PATH", "SD_MODEL_MANIFEST_PATH"}:
        from core.path_refs import to_storable_path_ref
        return to_storable_path_ref(value)
    return str(value)


def _validate(updates: dict[str, str]) -> list[str]:
    errors = []
    key_map = {item["key"]: item for item in EDITABLE_CONFIG}
    for key, raw_val in updates.items():
        raw_val = str(raw_val)
        if key not in _ALLOWED_KEYS:
            errors.append(f"不正なキー: {key}")
            continue
        if "\n" in raw_val or "\r" in raw_val:
            errors.append(f"{key}: 改行は使用できません")
            continue
        spec = key_map[key]
        try:
            if spec["type"] == "float":
                v = float(raw_val)
                if "min" in spec and v < spec["min"]:
                    errors.append(f"{key}: {v} は最小値 {spec['min']} 未満です")
                if "max" in spec and v > spec["max"]:
                    errors.append(f"{key}: {v} は最大値 {spec['max']} 超です")
            elif spec["type"] == "int":
                v = int(raw_val)
                if "min" in spec and v < spec["min"]:
                    errors.append(f"{key}: {v} は最小値 {spec['min']} 未満です")
                if "max" in spec and v > spec["max"]:
                    errors.append(f"{key}: {v} は最大値 {spec['max']} 超です")
            elif spec["type"] == "bool":
                if raw_val not in ("0", "1"):
                    errors.append(f"{key}: '0' か '1' で指定してください")
            elif spec["type"] == "hex_color":
                import re as _re
                if raw_val and not _re.match(r'^#[0-9a-fA-F]{6}$', raw_val):
                    errors.append(f"{key}: '#RRGGBB' 形式で指定してください（例: #7c2d12）。空欄にするとデフォルト色になります")
            elif spec["type"] in ("str", "ollama_model", "bgm_file"):
                if not raw_val.strip() and not spec.get("allow_empty"):
                    errors.append(f"{key}: 空文字は不正です")
                if spec["type"] == "bgm_file" and raw_val.strip():
                    if os.path.sep in raw_val or "/" in raw_val or "\\" in raw_val:
                        errors.append(f"{key}: ファイル名のみ指定してください（パス区切り文字不可）")
            elif spec["type"] == "select":
                choices = {str(value) for value, _label in spec.get("choices", [])}
                if raw_val not in choices:
                    errors.append(f"{key}: 選択肢にない値です")
        except (ValueError, TypeError):
            _logger.warning("設定値バリデーション中の型変換に失敗しました: key=%s value=%r", key, raw_val, exc_info=True)
            errors.append(f"{key}: '{raw_val}' は {spec['type']} として無効です")
    return errors


def _apply_runtime_updates(updates: dict[str, str]) -> None:
    """保存した設定を現在のWebプロセスへ即時反映する。

    1. os.environ を更新
    2. config モジュール属性を更新
    3. 'from config import X' でキャプチャ済みの全モジュール変数も更新
       → native_renderer, voicevox など起動時にインポートしたモジュールにも即反映
    """
    import sys
    key_map = {item["key"]: item for item in EDITABLE_CONFIG}
    for key, raw_val in updates.items():
        spec = key_map.get(key)
        if not spec:
            continue
        os.environ[key] = str(raw_val)
        try:
            if spec["type"] == "int":
                value: Any = int(raw_val)
            elif spec["type"] == "float":
                value = float(raw_val)
            elif spec["type"] == "bool":
                value = str(raw_val) == "1"
            elif key == "WEB_IMAGE_STYLE_CHOICES":
                value = cfg._split_env_choices(raw_val)
            elif key == "WEB_DEFAULT_IMAGE_STYLE":
                value = cfg._clean_env_choice(raw_val)
            elif spec["type"] == "hex_color":
                value = str(raw_val).strip()
            else:
                value = str(raw_val)
        except (ValueError, TypeError):
            _logger.warning("保存済み設定の実行時反映に失敗しました: key=%s value=%r", key, raw_val, exc_info=True)
            continue

        # config モジュール自身を更新
        setattr(cfg, key, value)

        # 'from config import KEY' でキャプチャしたモジュールの変数も一括更新
        for mod in list(sys.modules.values()):
            if mod is None or mod is cfg:
                continue
            if hasattr(mod, key):
                try:
                    setattr(mod, key, value)
                except (AttributeError, TypeError):
                    _logger.warning("設定値のモジュール反映に失敗しました: key=%s module=%s", key, getattr(mod, "__name__", ""), exc_info=True)
