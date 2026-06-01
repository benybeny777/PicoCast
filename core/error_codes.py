"""
エラーコードの中央カタログ。

コード・ユーザー向け文言・カテゴリ・再実行推奨可否をここで一元管理する。
新しいエラー種別を増やすときは ERROR_CATALOG に1行追加する（コードは安定IDとして残す）。

使い方:
    from core.error_codes import AppError, format_error, image_error_code
    raise AppError("E-IMG-BUSY", detail="503 UNAVAILABLE")
    log_line = format_error("E-IMG-BUSY", "背景4/8")  # "[E-IMG-BUSY] ...: 背景4/8"
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDef:
    code: str
    message: str                 # ユーザー向け既定文言（日本語）
    category: str                # auth / quota / api_busy / generic / config / pipeline ...
    retry_recommended: bool = False  # 時間を置いた再実行で回復する見込みがあるか


# ─────────────────────────────────────────────────────────────────────────────
# 中央カタログ（コード → 定義）。文言の変更はここだけで行う。
# ─────────────────────────────────────────────────────────────────────────────
ERROR_CATALOG: dict[str, ErrorDef] = {
    # 画像生成（Gemini / Nano Banana / Stable Diffusion WebUI）
    "E-IMG-BUSY":  ErrorDef("E-IMG-BUSY",  "画像生成APIが混雑しています。台本やプロンプトの問題ではありません。時間を置いて再生成してください。", "api_busy", True),
    "E-IMG-AUTH":  ErrorDef("E-IMG-AUTH",  "画像生成APIの認証・権限エラーです。設定画面のAPIキーを確認してください。", "auth", False),
    "E-IMG-QUOTA": ErrorDef("E-IMG-QUOTA", "画像生成APIのレート制限・クォータ超過です。時間を置いて再実行してください。", "quota", True),
    "E-IMG-FAIL":  ErrorDef("E-IMG-FAIL",  "画像生成に失敗しました。", "generic", False),
    # 認証情報
    "E-SECRET-MISSING": ErrorDef("E-SECRET-MISSING", "必要なAPIキー/認証情報が未登録です。設定画面から登録してください。", "config", False),
    # 台本
    "E-SCRIPT-MISSING": ErrorDef("E-SCRIPT-MISSING", "対象の台本がデータベースに見つかりません。", "pipeline", False),
    # 音声・レンダー
    "E-VOICE-FAIL":  ErrorDef("E-VOICE-FAIL",  "音声生成に失敗したセリフがあります。", "pipeline", False),
    "E-RENDER-FAIL": ErrorDef("E-RENDER-FAIL", "MP4のレンダリングに失敗しました。", "pipeline", False),
    # 既定
    "E-UNKNOWN": ErrorDef("E-UNKNOWN", "不明なエラーが発生しました。", "generic", False),
}


# 画像APIの分類（image_generator.classify_image_api_error の category）→ コード
_IMAGE_CATEGORY_TO_CODE = {
    "api_busy": "E-IMG-BUSY",
    "auth":     "E-IMG-AUTH",
    "quota":    "E-IMG-QUOTA",
    "generic":  "E-IMG-FAIL",
}


def image_error_code(category: str) -> str:
    """画像APIエラーのカテゴリからエラーコードを返す。"""
    return _IMAGE_CATEGORY_TO_CODE.get(category, "E-IMG-FAIL")


def get_error(code: str) -> ErrorDef:
    """コードから定義を返す。未登録コードは E-UNKNOWN を返す（落とさない）。"""
    return ERROR_CATALOG.get(code, ERROR_CATALOG["E-UNKNOWN"])


def format_error(code: str, detail: str = "") -> str:
    """`[CODE] 文言（: detail）` 形式の表示文字列を返す。"""
    d = get_error(code)
    base = f"[{d.code}] {d.message}"
    detail = (detail or "").strip()
    return f"{base}（{detail}）" if detail else base


class AppError(Exception):
    """エラーコードを持つアプリ例外。`str()` は `[CODE] 文言: detail`。"""

    def __init__(self, code: str, detail: str = "", *, cause: Exception | None = None):
        self.code = code
        self.detail = detail
        self.definition = get_error(code)
        self.__cause__ = cause
        super().__init__(format_error(code, detail))

    @property
    def category(self) -> str:
        return self.definition.category

    @property
    def retry_recommended(self) -> bool:
        return self.definition.retry_recommended
