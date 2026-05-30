"""
セキュリティユーティリティ。
- active profile の output_root 配下のみアクセス許可
- パストラバーサル対策
- 秘密ファイルの読み取り禁止
"""
import os
from fastapi import HTTPException

# 絶対に読み取り・返却してはならないファイル名
_SECRET_FILES = frozenset({
    ".env",
    "client_secrets.json",
    "token.json",
    "token_analytics.json",
})


def _get_output_base() -> str:
    """active profile の output_root を返す。未設定なら config フォールバック。"""
    from core.output_paths import get_output_root
    return os.path.realpath(get_output_root())


def safe_output_path(relative_or_name: str, output_base: str | None = None) -> str:
    """
    active profile の output_root 配下に限定した安全なパスを返す。
    別 profile の output_root へのアクセスは拒否する。
    パストラバーサルや秘密ファイルアクセスも拒否する。
    """
    if output_base is None:
        output_base = _get_output_base()
    else:
        output_base = os.path.realpath(output_base)

    # 絶対パスが渡された場合はそのまま検証
    if os.path.isabs(relative_or_name):
        candidate = os.path.realpath(relative_or_name)
    else:
        candidate = os.path.realpath(os.path.join(output_base, relative_or_name))

    if not candidate.startswith(output_base + os.sep) and candidate != output_base:
        raise HTTPException(status_code=403, detail="出力フォルダ外へのアクセスは禁止されています")

    basename = os.path.basename(candidate)
    if basename in _SECRET_FILES:
        raise HTTPException(status_code=403, detail="このファイルへのアクセスは禁止されています")

    return candidate


def is_safe_output_path(path: str) -> bool:
    """パスが output_root 配下かつ秘密ファイルでないか判定する（例外を投げない版）。"""
    try:
        safe_output_path(path)
        return True
    except HTTPException:
        return False


def is_video_folder(name: str) -> bool:
    """動画フォルダのプレフィックスがあるフォルダのみ動画フォルダとみなす。"""
    from config import config
    return name.startswith((
        config.FOLDER_PREFIX_SHORTS, config.FOLDER_PREFIX_LONG, config.FOLDER_PREFIX_MEETING,
    ))
