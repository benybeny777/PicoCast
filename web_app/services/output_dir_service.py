"""出力ベースディレクトリ（全プロファイル共通）の参照・変更サービス。

出力先の変更は既存データの移動を伴う重い操作のため、汎用の設定保存
(config_service) とは分離し、confirmed 必須・ジョブ稼働ガード付きで扱う。
"""
import logging
import os

_logger = logging.getLogger(__name__)


def get_output_base_info() -> dict:
    """現在の出力ベース・既定値・カスタム指定かどうかを返す。"""
    from core.output_paths import output_base_dir, default_output_base_dir

    current = output_base_dir()
    default = default_output_base_dir()
    return {
        "current": current,
        "default": default,
        "is_custom": os.path.normcase(os.path.normpath(current))
        != os.path.normcase(os.path.normpath(default)),
    }


def _active_jobs_by_profile() -> dict[str, int]:
    """全 channel profile の実行中/待機中ジョブ数を profile_id ごとに返す。"""
    from core.channel_profile import list_profiles, profile_context
    from core.metadata_db import count_active_jobs

    counts: dict[str, int] = {}
    for profile in list_profiles():
        with profile_context(profile.profile_id):
            n = count_active_jobs()
        if n > 0:
            counts[profile.profile_id] = n
    return counts


def change_output_base(new_path: str, *, confirmed: bool, move: bool = True) -> dict:
    """出力ベースを変更する。confirmed=true 必須。

    実行中/待機中のジョブがある場合は移動せず拒否する（runner が metadata.db を
    掴んでいる間に移動するとDB破損の恐れがあるため）。
    """
    new_path = (new_path or "").strip()
    if not new_path:
        raise ValueError("出力先のパスを入力してください")
    if not confirmed:
        raise ValueError("confirmed=true が必要です")

    active = _active_jobs_by_profile()
    if active:
        detail = ", ".join(f"{pid}:{n}件" for pid, n in active.items())
        raise RuntimeError(
            "実行中/待機中のジョブがあるため出力先を変更できません。"
            f"ジョブ完了後に再実行してください（{detail}）。"
        )

    from core.output_paths import relocate_output_base

    result = relocate_output_base(new_path, move=move)
    _logger.info("[OutputBase] 出力先変更完了: %s", result)
    return result
