"""
SD WebUI Forge モデル管理サービス。
Web UI ルートからの要求を受けてモデルマネージャーへ委譲する。
"""
import logging
from typing import Any

import config
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
    """SD WebUI API からインストール済みモデル一覧を取得する。

    Raises:
        RuntimeError: API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    gen = StableDiffusionWebUIGenerator()
    return gen.get_models()


def get_current_model_from_webui() -> str:
    """SD WebUI API から現在ロード中のモデル名を取得する。

    Raises:
        RuntimeError: API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    gen = StableDiffusionWebUIGenerator()
    return gen.get_current_model()


def set_active_model(model_name: str) -> None:
    """SD WebUI API でアクティブモデルを切り替える。

    Raises:
        RuntimeError: モデルが見つからない・API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    gen = StableDiffusionWebUIGenerator()
    gen.set_active_model(model_name)


def rescan_models() -> None:
    """SD WebUI API に再スキャンを依頼する。

    Raises:
        RuntimeError: API 未起動・HTTPエラー。
    """
    from core.sd_webui_generator import StableDiffusionWebUIGenerator
    gen = StableDiffusionWebUIGenerator()
    gen.rescan_models()
