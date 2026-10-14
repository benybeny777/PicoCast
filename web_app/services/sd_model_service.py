"""
Stable Diffusion WebUI モデル管理サービス。
Web UI ルートからの要求を受けてモデルマネージャーへ委譲する。
"""
import logging
from typing import Any, Callable

from core.sd_model_manager import SDWebUIModelManager

logger = logging.getLogger(__name__)


def get_model_list() -> list[dict[str, Any]]:
    """マニフェスト内全モデルのステータスリストを返す。

    Raises:
        RuntimeError: マニフェスト読み込み失敗など。
    """
    manager = SDWebUIModelManager()
    return manager.get_model_status()


def get_installed_models_from_webui() -> list[dict]:
    """Stable Diffusion WebUI API からインストール済みモデル一覧を取得する。

    Raises:
        RuntimeError: API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    with StableDiffusionWebUIGenerator() as gen:
        return gen.get_models()


def get_current_model_from_webui() -> str:
    """Stable Diffusion WebUI API から現在ロード中のモデル名を取得する。

    Raises:
        RuntimeError: API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    with StableDiffusionWebUIGenerator() as gen:
        return gen.get_current_model()


def set_active_model(model_name: str) -> None:
    """Stable Diffusion WebUI API でアクティブモデルを切り替える。

    Raises:
        RuntimeError: モデルが見つからない・API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    with StableDiffusionWebUIGenerator() as gen:
        gen.set_active_model(model_name)


def rescan_models() -> None:
    """Stable Diffusion WebUI API に再スキャンを依頼する。

    Raises:
        RuntimeError: API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    with StableDiffusionWebUIGenerator() as gen:
        gen.rescan_models()


def download_model(
    model_id: str,
    *,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> str:
    """指定モデルをダウンロードする。

    Raises:
        RuntimeError: 各種エラー。
    """
    manager = SDWebUIModelManager()
    return manager.download_model(model_id, progress_callback=progress_callback)


def delete_model(model_id: str, *, confirmed: bool = False) -> str:
    """指定モデルのファイルを削除する。confirmed=True が必須。

    Raises:
        RuntimeError: confirmed=False、ファイルが存在しない、パスが範囲外。
    """
    manager = SDWebUIModelManager()
    return manager.delete_model(model_id, confirmed=confirmed)
