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
    message: str                 # ユーザー向け既定文言（何が起きたか）
    category: str                # auth / quota / api_busy / generic / config / pipeline ...
    retry_recommended: bool = False  # 時間を置いた再実行で回復する見込みがあるか
    remediation: str = ""        # ユーザーが取るべき具体的な対処手順（必ず1つ以上）


# ─────────────────────────────────────────────────────────────────────────────
# 中央カタログ（コード → 定義）。文言の変更はここだけで行う。
# すべてのエントリに remediation（対処手順）を必ず付ける。製品版では
# 「原因不明・対処不明」のエラーをユーザーに出さないことを方針とする。
# ─────────────────────────────────────────────────────────────────────────────
ERROR_CATALOG: dict[str, ErrorDef] = {
    # 画像生成（Gemini / Nano Banana / Stable Diffusion WebUI）
    "E-IMG-BUSY":  ErrorDef("E-IMG-BUSY",  "一時的に混雑しています（提供元サーバー側の高負荷）。残高・APIキー・台本やプロンプトの問題ではありません。", "api_busy", True,
                            "数分おいてから履歴の再生成（背景再利用）で未生成分だけ作り直してください。"),
    "E-IMG-AUTH":  ErrorDef("E-IMG-AUTH",  "画像生成の認証・権限エラーです。", "auth", False,
                            "設定画面のAPIキーが正しいか、課金・権限（Generative Language API の有効化）を確認して登録し直してください。"),
    "E-IMG-QUOTA": ErrorDef("E-IMG-QUOTA", "画像生成の利用上限に達しました（レート制限・クォータ・残高のいずれか）。", "quota", True,
                            "提供元コンソールで利用量と課金状況を確認し、上限引き上げか時間をおいて再実行してください。"),
    "E-IMG-FAIL":  ErrorDef("E-IMG-FAIL",  "画像生成に失敗しました。", "generic", False,
                            "デバッグログ（app_debug_*.log）でエラー内容を確認し、APIキー・プロンプト・画像エンジンの稼働状況を確認してください。"),
    # 認証情報
    "E-SECRET-MISSING": ErrorDef("E-SECRET-MISSING", "必要なAPIキー/認証情報が未登録です。", "config", False,
                                 "設定画面の「APIキー」タブから対象の認証情報を登録してください。"),
    # 台本
    "E-SCRIPT-MISSING": ErrorDef("E-SCRIPT-MISSING", "対象の台本がデータベースに見つかりません。", "pipeline", False,
                                 "履歴一覧から対象動画を選び直すか、台本を再生成してください。フォルダ移動・削除をした場合は再取り込みが必要です。"),
    # 音声・レンダー
    "E-VOICE-FAIL":  ErrorDef("E-VOICE-FAIL",  "音声生成に失敗したセリフがあります。", "pipeline", False,
                              "VOICEVOX が起動しているか（既定 http://localhost:50021）確認し、該当セリフを修正して再生成してください。"),
    "E-RENDER-FAIL": ErrorDef("E-RENDER-FAIL", "MP4のレンダリングに失敗しました。", "pipeline", False,
                              "ffmpeg が利用可能か、音声・背景が揃っているかを確認し、履歴詳細の「動画再作成（レンダーのみ）」で作り直してください。"),
    # 外部サービス稼働
    "E-VOICEVOX-DOWN": ErrorDef("E-VOICEVOX-DOWN", "VOICEVOX に接続できません。", "config", True,
                                "VOICEVOX を起動し、設定画面の VOICEVOX_URL（既定 http://localhost:50021）が正しいか確認してから再実行してください。"),
    "E-FFMPEG-MISSING": ErrorDef("E-FFMPEG-MISSING", "ffmpeg が見つかりません。", "config", False,
                                 "ffmpeg をインストールして PATH に通すか、設定画面の FFMPEG_BIN に ffmpeg.exe のパスを指定してください。/setup の自動検出も利用できます。"),
    "E-OLLAMA-DOWN": ErrorDef("E-OLLAMA-DOWN", "Ollama に接続できません。", "config", True,
                              "Ollama を起動してください（未導入ならインストール後 `ollama pull qwen3:8b`）。台本の品質レビューと、Stable Diffusion WebUI 画像の英語プロンプト変換で使用します。設定画面の OLLAMA_BASE_URL も確認してください。"),
    # ネットワーク
    "E-NET": ErrorDef("E-NET", "ネットワーク接続に失敗しました。", "network", True,
                      "インターネット接続とプロキシ/ファイアウォール設定を確認し、しばらくしてから再実行してください。"),
    # YouTube アップロード
    "E-UPLOAD-AUTH": ErrorDef("E-UPLOAD-AUTH", "YouTube の認証が無効または未完了です。", "auth", False,
                              "設定画面でYouTube Client Secretsを登録し、アップロード用のOAuth認証をやり直してください。トークン失効時は再認証が必要です。"),
    "E-UPLOAD-FAIL": ErrorDef("E-UPLOAD-FAIL", "YouTube へのアップロードに失敗しました。", "pipeline", True,
                              "ネットワークと認証状態を確認し、時間をおいて再実行してください。YouTube側の上限・重複の可能性もあります。"),
    # ライセンス・セットアップ
    "E-SETUP-INCOMPLETE": ErrorDef("E-SETUP-INCOMPLETE", "初回セットアップが未完了です。", "config", False,
                                   "/setup を開き、チャンネル・APIキー・外部サービス診断を完了してください。"),
    "E-PROFILE-MISSING": ErrorDef("E-PROFILE-MISSING", "アクティブなチャンネルプロファイルが未設定です。", "config", False,
                                  "設定画面または初回セットアップでチャンネルを作成し、アクティブに選択してください。"),
    "E-PLAYLIST-CONFIG": ErrorDef("E-PLAYLIST-CONFIG", "再生リスト設定が取得できません。", "config", False,
                                  "active channel profile の genre_profile と playlist_categories.md を確認してください。"),
    "E-PLAYLIST-CLASSIFY": ErrorDef("E-PLAYLIST-CLASSIFY", "Ollama による再生リスト判定に失敗しました。", "pipeline", True,
                                    "単体の「再生リスト振り分け」画面で、Ollama が起動しているか、OLLAMA_PLAYLIST_MODEL が pull 済みか、playlist_categories.md のカテゴリ名が適切か確認してください。タイムアウト時は設定画面で判定モデルまたはタイムアウト秒数を調整してください。"),
    "E-PLAYLIST-TARGET": ErrorDef("E-PLAYLIST-TARGET", "再生リスト判定の対象動画が見つかりません。", "pipeline", False,
                                  "再生リスト振り分け画面を再読み込みし、現在のチャンネルに存在する動画を選び直してください。"),
    "E-PLAYLIST-SAVE": ErrorDef("E-PLAYLIST-SAVE", "再生リスト判定結果をデータベースへ保存できませんでした。", "pipeline", True,
                                "データベースが他の処理でロックされていないか確認し、処理終了後に再生リスト振り分けを再実行してください。"),
    "E-METADATA-CONFIG": ErrorDef("E-METADATA-CONFIG", "YouTubeメタデータ用のチャンネル設定が取得できません。", "config", False,
                                  "active channel profile の genre_profile と profile.yaml を確認してください。"),
    "E-LICENSE-LIMIT": ErrorDef("E-LICENSE-LIMIT", "現在のライセンスエディションの利用上限に達しました。", "license", False,
                                "設定画面「製品管理」で上位エディションに切り替えるか、上限の範囲内で実行してください。"),
    # ディスク
    "E-DISK": ErrorDef("E-DISK", "ディスクの空き容量が不足している可能性があります。", "system", False,
                       "出力先ドライブの空き容量を確保してから再実行してください。"),
    "E-IMG-FONT": ErrorDef("E-IMG-FONT", "画像の文字入れに使うフォントが見つかりません。", "config", False,
                           "設定画面「AI / 画像生成」の IMAGE_TEXT_FONT_PATH に、太字の日本語フォントファイル（例: C:\\Windows\\Fonts\\YuGothB.ttc）を指定してください。"),
    "E-CODEX-IMAGE-MISSING": ErrorDef("E-CODEX-IMAGE-MISSING", "Codex が画像を保存しませんでした。", "pipeline", True,
                                      "ターミナルで codex を起動し、ChatGPT の有料プランでログインしていることと、画像生成の使用枠が残っていることを確認してください。詳細は app_debug_*.log を確認してください。"),
    # 文章生成AI（core/text_llm.py）
    "E-LLM-BACKEND": ErrorDef("E-LLM-BACKEND", "文章生成AIの設定が正しくありません。", "config", False,
                              "設定画面「AI / 文章生成」で文章生成AI（gemini / claude_cli / codex_cli / ollama）とモデル名を確認してください。"),
    "E-LLM-CLI-MISSING": ErrorDef("E-LLM-CLI-MISSING", "文章生成に使う CLI が見つかりません。", "config", False,
                                  "Claude Code（claude）または Codex（codex）をインストールしてログインし、設定画面で実行ファイルのパスを確認してください。"),
    "E-LLM-FAILED": ErrorDef("E-LLM-FAILED", "文章生成AIが失敗しました。", "pipeline", True,
                             "CLI の場合はターミナルで一度起動してログイン状態と利用上限を確認してください。詳細は app_debug_*.log を確認してください。"),
    "E-LLM-TIMEOUT": ErrorDef("E-LLM-TIMEOUT", "文章生成AIが時間内に終わりませんでした。", "pipeline", True,
                              "設定画面の TEXT_LLM_TIMEOUT_SEC を延ばすか、時間を置いて再実行してください。"),
    # YouTube 予約投稿
    "E-YOUTUBE-SCHEDULE": ErrorDef("E-YOUTUBE-SCHEDULE", "YouTube から予約投稿の状況を取得できません。", "network", True,
                                   "ネットワーク接続と YouTube の認証（設定画面「認証情報」）を確認して再実行してください。予約の重複を避けるため、取得できるまで予約枠の割り当てと同期は行いません。"),
    # 固定コメント
    "E-FIXED-COMMENT-AUTO": ErrorDef("E-FIXED-COMMENT-AUTO", "固定コメントの自動投稿に失敗しました。", "youtube", True,
                                     "固定コメント画面から該当動画を手動投稿して原因を確認してください。YouTube の認証切れなら設定画面「認証情報」で再認証し、詳細は app_debug_fixed_comment.log を確認してください。"),
    # 既定
    "E-UNKNOWN": ErrorDef("E-UNKNOWN", "不明なエラーが発生しました。", "generic", False,
                          "デバッグログ（app_debug_*.log）を確認し、解決しない場合は設定画面「製品管理」から診断パッケージを作成して問い合わせてください。"),
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


# 画像生成バックエンド値 → ユーザー向け表示名（UI表記ルールに準拠）
_BACKEND_LABELS = {
    "nanobanana": "Gemini",
    "gemini":     "Gemini",
    "sd_webui":   "Stable Diffusion WebUI",
    "comfyui":    "ComfyUI（ローカル）",
    "codex_cli":  "Codex CLI",
}


def backend_label(backend: str) -> str:
    """画像生成バックエンド値をユーザー向け表示名に変換する。"""
    key = (backend or "").strip().lower()
    return _BACKEND_LABELS.get(key, backend or "画像生成")


def format_image_error(
    code: str,
    *,
    backend: str = "",
    model: str = "",
    status_code=None,
    detail: str = "",
) -> str:
    """画像生成エラーを『[CODE] バックエンド：文言（HTTP=… / model=… / detail）』形式の表示文字列にする。

    どのバックエンド（Gemini / Stable Diffusion WebUI）で、どの種別
    （混雑 / クォータ・残高 / 認証 / その他）の失敗かを一目で判別できる形にする。
    """
    d = get_error(code)
    head = f"[{d.code}] {backend_label(backend)}：{d.message}"
    extras: list[str] = []
    if status_code is not None:
        extras.append(f"HTTP={status_code}")
    if model:
        extras.append(f"model={model}")
    detail = (detail or "").strip()
    if detail:
        extras.append(detail)
    return f"{head}（{' / '.join(extras)}）" if extras else head


def get_error(code: str) -> ErrorDef:
    """コードから定義を返す。未登録コードは E-UNKNOWN を返す（落とさない）。"""
    return ERROR_CATALOG.get(code, ERROR_CATALOG["E-UNKNOWN"])


def format_error(code: str, detail: str = "", *, with_fix: bool = False) -> str:
    """`[CODE] 文言（detail）` 形式の表示文字列を返す。

    with_fix=True のとき、末尾に ` 対処: <remediation>` を付けて
    「何が起きたか」と「どうすればよいか」を一目で示す。
    """
    d = get_error(code)
    base = f"[{d.code}] {d.message}"
    detail = (detail or "").strip()
    text = f"{base}（{detail}）" if detail else base
    if with_fix and d.remediation:
        text = f"{text} 対処: {d.remediation}"
    return text


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

    @property
    def remediation(self) -> str:
        return self.definition.remediation

    def user_message(self) -> str:
        """ユーザー向けに「何が起きたか＋対処」をまとめた文字列を返す。"""
        return format_error(self.code, self.detail, with_fix=True)
