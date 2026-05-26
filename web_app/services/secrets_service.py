"""
APIキー等の秘密値を .env へ書き込む専用サービス。
値はメモリ上で処理し、ログ・レスポンスには一切含めない。
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")

_ALLOWED_SECRET_KEYS = {"GOOGLE_API_KEY", "OPENAI_API_KEY"}


def save_secrets(updates: dict[str, str]) -> list[str]:
    """
    空文字は「変更なし」として無視する。
    不正なキーはエラーを返す。値は検証のみ行い、ログに出さない。
    """
    errors: list[str] = []
    for key, value in updates.items():
        if key not in _ALLOWED_SECRET_KEYS:
            errors.append(f"不正なキー: {key}")
        if "\n" in str(value) or "\r" in str(value):
            errors.append(f"{key}: 改行は使用できません")
    if errors:
        return errors

    to_write = {k: v for k, v in updates.items() if v.strip()}
    if not to_write:
        return []

    _write_env_secrets(to_write)
    return []


def _write_env_secrets(updates: dict[str, str]) -> None:
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    updated: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated.add(k)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in updated:
            new_lines.append(f"{k}={v}\n")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
