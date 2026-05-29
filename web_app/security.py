"""
セキュリティユーティリティ。
- output/ 配下のみアクセス許可
- パストラバーサル対策
- 秘密ファイルの読み取り禁止
"""
import os
from fastapi import HTTPException

from core.output_paths import OUTPUT_DIR

# 絶対に読み取り・返却してはならないファイル名
_SECRET_FILES = frozenset({
    ".env",
    "client_secrets.json",
    "token.json",
    "token_analytics.json",
})


def safe_output_path(relative_or_name: str, output_base: str | None = None) -> str:
    """
    output/ 配下に限定した安全なパスを返す。
    パストラバーサルや秘密ファイルアクセスを拒否する。
    """
    output_base = os.path.realpath(output_base or OUTPUT_DIR)

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
    """パスが output/ 配下かつ秘密ファイルでないか判定する（例外を投げない版）。"""
    try:
        safe_output_path(path)
        return True
    except HTTPException:
        return False


def is_video_folder(name: str) -> bool:
    """動画フォルダのプレフィックスがあるフォルダのみ動画フォルダとみなす。旧[]形式も認識する。"""
    from config import config
    return name.startswith((
        config.FOLDER_PREFIX_SHORTS, config.FOLDER_PREFIX_LONG, config.FOLDER_PREFIX_MEETING,
        "[Shorts]", "[Long]", "[ネタ会議]",  # 旧形式 互換 TODO: 2026-06-29 以降に削除
    ))
