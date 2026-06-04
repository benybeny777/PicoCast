"""
Stable Diffusion WebUI / AUTOMATIC1111 モデル管理クラス。

モデルマニフェスト (model_manifest.json) に基づき、
チェックポイントモデルのインストール確認・ダウンロード・SHA256検証を行う。

ダウンロードポリシー:
- source_url が空ならエラー（通常マニフェストでは空にしない）
- requires_auth=true かつ HF_TOKEN 未設定ならエラー（HF_TOKEN 設定を促す）
- requires_auth=true かつ HF_TOKEN 設定済みなら Authorization ヘッダー付きで取得
- ダウンロードは .part 一時ファイルを使用し、完了後に rename する
- SHA256 が空文字列の場合は検証をスキップする
- 既存ファイルが存在し SHA256 が一致するなら再ダウンロードしない
- 既存ファイルが存在し SHA256 が不一致の場合はエラー（自動上書き禁止）
- フォールバック・サイレントスキップは禁止: 例外は必ず上位に伝播させる

削除ポリシー:
- delete_model() は confirmed=True が必要
- 削除対象が SD_WEBUI_ROOT 配下であることを確認する
"""
import hashlib
import json
import logging
import os
from typing import Any, Callable

import httpx

from config import config

logger = logging.getLogger(__name__)

# マニフェスト必須フィールド
_REQUIRED_MANIFEST_KEYS = {"version", "models"}
_REQUIRED_MODEL_KEYS = {
    "id", "display_name", "type", "filename", "target_subdir",
    "source_url", "sha256",
}


class SDWebUIModelManager:
    """Stable Diffusion WebUI モデルマニフェストを元にモデルの管理を行う。"""

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
                "Stable Diffusion WebUI のインストールディレクトリを SD_WEBUI_ROOT に設定してください。"
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
            - license_note, source_page_url
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
                "license_note": m.get("license_note", ""),
                "source_page_url": m.get("source_page_url", ""),
                "installed": installed,
                "path": file_path,
                "can_download": bool(m["source_url"]),
                # 後方互換
                "download_page_url": m.get("download_page_url", m.get("source_page_url", "")),
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
                f"Stable Diffusion WebUI必要モデルが不足しています。不足: {', '.join(missing)}\n"
                f"SDモデル管理画面からダウンロードしてください。"
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

        既存ファイルが存在する場合:
        - SHA256 が設定済みで一致 → 再ダウンロードしない（パスを返す）
        - SHA256 が設定済みで不一致 → RuntimeError（手動で削除して再DLを促す）
        - SHA256 未設定 → 再ダウンロードしない（インストール済みと見なす）

        Args:
            model_id: マニフェスト内の id
            progress_callback: 進捗通知コールバック (filename, downloaded_bytes, total_bytes)
            timeout: ダウンロード全体のタイムアウト秒数

        Returns:
            保存したファイルの絶対パス

        Raises:
            RuntimeError: モデルが見つからない・URL未設定・認証不足・HTTP失敗・SHA256不一致
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
                f"マニフェストを確認してください。"
            )

        # 認証チェック
        from core.secret_store import current_profile_id_or_default, has_secret, load_secret
        profile_id = current_profile_id_or_default()
        hf_token = load_secret("hf_token", profile_id=profile_id) if has_secret("hf_token", profile_id=profile_id) else ""
        if entry.get("requires_auth"):
            if not hf_token:
                raise RuntimeError(
                    f"モデル '{entry['display_name']}' のダウンロードには HF_TOKEN が必要です。\n"
                    f"設定画面の「認証情報」タブで HF_TOKEN を登録し、\n"
                    f"配布元ページでライセンス同意済みか確認してください。\n"
                    f"配布元: {entry.get('source_page_url') or entry.get('source_url', '')}"
                )

        dest_path = self._resolve_model_path(entry)
        sha256_expected = (entry.get("sha256") or "").strip().lower()

        # 既存ファイルの確認
        if os.path.isfile(dest_path):
            if sha256_expected:
                logger.info("既存ファイルの SHA256 を確認中: %s", dest_path)
                actual = self._sha256_file(dest_path)
                if actual == sha256_expected:
                    logger.info("SHA256 一致。再ダウンロード不要: %s", entry["filename"])
                    return dest_path
                else:
                    raise RuntimeError(
                        f"モデル '{entry['filename']}' は既にインストールされていますが、SHA256 が一致しません。\n"
                        f"  期待値: {sha256_expected}\n"
                        f"  実際値: {actual}\n"
                        f"ファイルが壊れている可能性があります。"
                        f"SDモデル管理画面の「削除して再ダウンロード」で修復してください。"
                    )
            else:
                logger.info("SHA256 未設定のため既存ファイルをそのまま使用: %s", entry["filename"])
                return dest_path

        part_path = dest_path + ".part"
        dest_dir = os.path.dirname(dest_path)
        os.makedirs(dest_dir, exist_ok=True)

        url = entry["source_url"]
        filename = entry["filename"]

        # Authorization ヘッダー（requires_auth=true かつ HF_TOKEN 設定済み）
        headers = {}
        if entry.get("requires_auth") and hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"
            logger.info("SDモデル ダウンロード開始 (認証あり): %s → %s", filename, dest_path)
        else:
            logger.info("SDモデル ダウンロード開始: %s → %s", filename, dest_path)

        try:
            with httpx.stream(
                "GET", url, headers=headers, timeout=timeout, follow_redirects=True
            ) as response:
                if response.status_code in (401, 403):
                    if entry.get("requires_auth"):
                        raise RuntimeError(
                            f"SDモデルダウンロード認証失敗: HTTP {response.status_code} ({filename})\n"
                            f"HF_TOKEN が無効か、配布元ページでライセンス同意が未完了の可能性があります。\n"
                            f"配布元: {entry.get('source_page_url') or url}"
                        )
                    raise RuntimeError(
                        f"SDモデルダウンロード失敗: HTTP {response.status_code} ({url})"
                    )
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
        except RuntimeError:
            raise
        except Exception as e:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            raise RuntimeError(
                f"SDモデルダウンロード中にエラーが発生しました: {filename}\n詳細: {e}"
            ) from e
        finally:
            # RuntimeError 以外の例外でも .part を削除
            if "e" in dir() and isinstance(locals().get("e"), Exception):
                if os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass

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
                    f"ダウンロードしたファイルは削除しました。再度お試しください。"
                )
        else:
            logger.info("SHA256未設定のためスキップ: %s", filename)

        os.replace(part_path, dest_path)
        logger.info("SDモデル 保存完了: %s", dest_path)
        return dest_path

    # ─────────────────────────────────────────
    # 削除
    # ─────────────────────────────────────────

    def delete_model(self, model_id: str, *, confirmed: bool = False) -> str:
        """指定モデルのファイルを削除する。

        confirmed=True が必須。SD_WEBUI_ROOT 配下のファイルのみ削除できる。

        Args:
            model_id: マニフェスト内の id
            confirmed: True でなければ RuntimeError

        Returns:
            削除したファイルのパス

        Raises:
            RuntimeError: confirmed=False、ファイルが存在しない、パスが範囲外
        """
        if not confirmed:
            raise RuntimeError(
                "delete_model() には confirmed=True が必要です。"
            )

        manifest = self._load_manifest()
        entry = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if entry is None:
            raise RuntimeError(
                f"SDモデルマニフェストにモデル id '{model_id}' が見つかりません。"
            )

        dest_path = self._resolve_model_path(entry)

        # SD_WEBUI_ROOT の範囲外へのパス操作を防ぐ
        sd_root_real = os.path.realpath(self.sd_root)
        dest_real = os.path.realpath(dest_path)
        if not dest_real.startswith(sd_root_real + os.sep) and dest_real != sd_root_real:
            raise RuntimeError(
                f"削除対象のパスが SD_WEBUI_ROOT 配下にありません: {dest_path}"
            )

        if not os.path.isfile(dest_path):
            raise RuntimeError(
                f"モデルファイルが存在しません: {dest_path}"
            )

        os.remove(dest_path)
        logger.info("SDモデル 削除完了: %s", dest_path)
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
