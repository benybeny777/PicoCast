"""
SD WebUI Forge / AUTOMATIC1111 モデル管理クラス。

モデルマニフェスト (model_manifest.json) に基づき、
チェックポイントモデルのインストール確認・ダウンロード・SHA256検証を行う。

ダウンロードは .part 一時ファイルを使用し、完了後に rename する。
SHA256 が空文字列の場合は検証をスキップする。
フォールバック・サイレントスキップは禁止: 例外は必ず上位に伝播させる。
"""
import hashlib
import json
import logging
import os
from typing import Any, Callable

import httpx

import config

logger = logging.getLogger(__name__)

# マニフェスト必須フィールド
_REQUIRED_MANIFEST_KEYS = {"version", "models"}
_REQUIRED_MODEL_KEYS = {
    "id", "display_name", "type", "filename", "target_subdir",
    "source_url", "sha256",
}


class SDWebUIModelManager:
    """SD WebUI Forge モデルマニフェストを元にモデルの管理を行う。"""

    def __init__(
        self,
        sd_root: str | None = None,
        manifest_path: str | None = None,
    ):
        self.sd_root = (sd_root if sd_root is not None else config.SD_WEBUI_ROOT).rstrip("/\\")
        self.manifest_path = (
            manifest_path if manifest_path is not None else config.SD_MODEL_MANIFEST_PATH
        )

    # ─────────────────────────────────────────
    # マニフェスト読み込み
    # ─────────────────────────────────────────

    def _load_manifest(self) -> dict:
        """マニフェスト JSON を読み込んで返す。

        Raises:
            RuntimeError: ファイルが存在しない、JSON不正、必須キーなし。
        """
        if not os.path.isfile(self.manifest_path):
            raise RuntimeError(
                f"SDモデルマニフェストが見つかりません: {self.manifest_path}"
            )
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"SDモデルマニフェストのJSON解析に失敗しました ({self.manifest_path}): {e}"
            ) from e
        if not isinstance(data, dict) or not _REQUIRED_MANIFEST_KEYS.issubset(data):
            raise RuntimeError(
                f"SDモデルマニフェストが不正です: 必須キー {_REQUIRED_MANIFEST_KEYS} が不足しています "
                f"({self.manifest_path})"
            )
        if not isinstance(data["models"], list):
            raise RuntimeError(
                f"SDモデルマニフェストが不正です: 'models' がリストではありません ({self.manifest_path})"
            )
        return data

    # ─────────────────────────────────────────
    # パス解決
    # ─────────────────────────────────────────

    def _resolve_model_path(self, model_entry: dict) -> str:
        """モデルエントリから絶対ファイルパスを返す。

        SD_WEBUI_ROOT が空の場合は絶対パスを構築できないため RuntimeError を送出する。
        """
        if not self.sd_root:
            raise RuntimeError(
                "SD_WEBUI_ROOT が設定されていません。"
                "SD WebUI のインストールディレクトリを SD_WEBUI_ROOT に設定してください。"
            )
        return os.path.join(
            self.sd_root,
            model_entry["target_subdir"],
            model_entry["filename"],
        )

    # ─────────────────────────────────────────
    # モデル状態確認
    # ─────────────────────────────────────────

    def get_model_status(self) -> list[dict[str, Any]]:
        """マニフェスト内全モデルのインストール状態を返す。

        Returns:
            各モデルのステータスリスト。各要素は以下のキーを持つ:
            - id, display_name, filename, type, recommended, description
            - installed (bool): ファイルが存在するか
            - path (str | None): SD_WEBUI_ROOT が設定されている場合のみ解決済みパス
            - can_download (bool): source_url が設定されているか
            - source_url, sha256, requires_auth, api_match_hint
        """
        manifest = self._load_manifest()
        result: list[dict[str, Any]] = []
        for m in manifest["models"]:
            # 必須キーチェック
            missing = _REQUIRED_MODEL_KEYS - set(m.keys())
            if missing:
                raise RuntimeError(
                    f"SDモデルマニフェスト内のモデル定義にキーが不足しています: {missing} (id={m.get('id', '?')})"
                )

            # パス解決（SD_WEBUI_ROOT 未設定時は None）
            try:
                file_path = self._resolve_model_path(m)
            except RuntimeError:
                file_path = None

            installed = os.path.isfile(file_path) if file_path else False

            result.append({
                "id": m["id"],
                "display_name": m["display_name"],
                "filename": m["filename"],
                "type": m["type"],
                "target_subdir": m["target_subdir"],
                "description": m.get("description", ""),
                "recommended": m.get("recommended", False),
                "requires_auth": m.get("requires_auth", False),
                "api_match_hint": m.get("api_match_hint", ""),
                "source_url": m["source_url"],
                "sha256": m["sha256"],
                "installed": installed,
                "path": file_path,
                "can_download": bool(m["source_url"]),
            })
        return result

    def check_all_models_ready(self) -> bool:
        """全マニフェストモデルがインストール済みか確認する。

        Returns:
            True: すべてインストール済み

        Raises:
            RuntimeError: 1つ以上のモデルが未インストール。
        """
        statuses = self.get_model_status()
        missing = [s["filename"] for s in statuses if not s["installed"]]
        if missing:
            raise RuntimeError(
                f"SD WebUI必要モデルが不足しています。不足: {', '.join(missing)}"
            )
        return True

    def is_model_installed(self, filename: str) -> bool:
        """指定ファイル名のモデルがインストール済みか返す。"""
        statuses = self.get_model_status()
        for s in statuses:
            if s["filename"] == filename:
                return s["installed"]
        raise RuntimeError(
            f"マニフェストにモデル '{filename}' が見つかりません。"
        )

    # ─────────────────────────────────────────
    # ダウンロード
    # ─────────────────────────────────────────

    def download_model(
        self,
        model_id: str,
        *,
        progress_callback: Callable[[str, int, int], None] | None = None,
        timeout: int = 3600,
    ) -> str:
        """指定モデルをダウンロードして所定のパスに保存する。

        ダウンロードは .part ファイルに行い、成功後に rename する。
        SHA256 が非空の場合は検証を行い、不一致であれば RuntimeError を送出する。

        Args:
            model_id: マニフェスト内の id
            progress_callback: 進捗通知コールバック (filename, downloaded_bytes, total_bytes)
            timeout: ダウンロード全体のタイムアウト秒数

        Returns:
            保存したファイルの絶対パス

        Raises:
            RuntimeError: モデルが見つからない・ダウンロードURL未設定・HTTP失敗・SHA256不一致
        """
        manifest = self._load_manifest()
        entry = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if entry is None:
            raise RuntimeError(
                f"SDモデルマニフェストにモデル id '{model_id}' が見つかりません。"
            )

        if not entry.get("source_url"):
            raise RuntimeError(
                f"モデル '{entry['display_name']}' はダウンロードURLが設定されていません。"
                f"手動で '{entry['filename']}' を '{entry['target_subdir']}' に配置してください。"
            )

        dest_path = self._resolve_model_path(entry)
        part_path = dest_path + ".part"
        dest_dir = os.path.dirname(dest_path)

        os.makedirs(dest_dir, exist_ok=True)

        url = entry["source_url"]
        filename = entry["filename"]
        sha256_expected = (entry.get("sha256") or "").strip().lower()

        logger.info("SDモデル ダウンロード開始: %s → %s", url, dest_path)

        try:
            with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
                if response.status_code != 200:
                    raise RuntimeError(
                        f"SDモデルダウンロード失敗: HTTP {response.status_code} ({url})"
                    )
                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                with open(part_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(filename, downloaded, total)
        except Exception:
            # ダウンロード失敗時は .part ファイルを削除
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            raise

        # SHA256 検証（非空時のみ）
        if sha256_expected:
            logger.info("SHA256 検証中: %s", filename)
            actual = self._sha256_file(part_path)
            if actual != sha256_expected:
                os.remove(part_path)
                raise RuntimeError(
                    f"SDモデルのSHA256が一致しません: {filename}\n"
                    f"  期待値: {sha256_expected}\n"
                    f"  実際値: {actual}\n"
                    f"ダウンロードしたファイルは削除しました。再度試みてください。"
                )
        else:
            logger.info("SHA256未設定のためスキップ: %s", filename)

        os.replace(part_path, dest_path)
        logger.info("SDモデル 保存完了: %s", dest_path)
        return dest_path

    # ─────────────────────────────────────────
    # ユーティリティ
    # ─────────────────────────────────────────

    @staticmethod
    def _sha256_file(path: str) -> str:
        """ファイルの SHA256 ハッシュを小文字16進数で返す。"""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
