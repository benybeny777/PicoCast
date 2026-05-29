"""
フォルダプレフィックス移行スクリプト。
[Shorts] / [Long] / [ネタ会議] 形式 → Shorts_ / Long_ / ネタ会議_ 形式にリネームする。

使い方:
  python scripts/migrate_folder_prefixes.py          # ドライラン（実際には変更しない）
  python scripts/migrate_folder_prefixes.py --apply  # 実際にリネーム

対象フォルダ:
  output/               直下の動画フォルダ
  output/000_uploaded/  アップロード済み動画フォルダ
  output/000_backups/   バックアップフォルダ
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config

# 旧プレフィックス → 新プレフィックス のマッピング
_RENAMES = [
    ("[Shorts]",   config.FOLDER_PREFIX_SHORTS),
    ("[SHORT]",    config.FOLDER_PREFIX_SHORTS),
    ("[Long]",     config.FOLDER_PREFIX_LONG),
    ("[LONG]",     config.FOLDER_PREFIX_LONG),
    ("[ネタ会議]", config.FOLDER_PREFIX_MEETING),
]


def _new_name(name: str) -> str | None:
    """旧形式なら新名を返す。既に新形式または対象外なら None。"""
    for old, new in _RENAMES:
        if name.startswith(old):
            return new + name[len(old):]
    return None


def _scan_dir(parent: str) -> list[tuple[str, str]]:
    """parent 直下のフォルダをスキャンしてリネーム候補を返す。"""
    pairs = []
    try:
        entries = os.listdir(parent)
    except OSError:
        return pairs
    for name in sorted(entries):
        new = _new_name(name)
        if new is None:
            continue
        src = os.path.join(parent, name)
        dst = os.path.join(parent, new)
        if os.path.isdir(src):
            pairs.append((src, dst))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="フォルダプレフィックス移行スクリプト")
    parser.add_argument("--apply", action="store_true", help="実際にリネームを実行する（省略時はドライラン）")
    args = parser.parse_args()
    dry = not args.apply

    output_dir = config.OUTPUT_DIR
    scan_dirs = [
        output_dir,
        os.path.join(output_dir, "000_uploaded"),
        os.path.join(output_dir, "000_backups"),
    ]

    all_pairs: list[tuple[str, str]] = []
    for d in scan_dirs:
        all_pairs.extend(_scan_dir(d))

    if not all_pairs:
        print("リネーム対象のフォルダはありませんでした。")
        return

    mode = "【ドライラン】" if dry else "【実行】"
    print(f"{mode} {len(all_pairs)} 件のフォルダをリネームします。\n")

    errors = 0
    for src, dst in all_pairs:
        rel_src = os.path.relpath(src)
        rel_dst = os.path.relpath(dst)
        if os.path.exists(dst):
            print(f"  スキップ (移動先が既に存在): {rel_src} -> {rel_dst}")
            errors += 1
            continue
        print(f"  {'(dry) ' if dry else ''}rename: {rel_src}  ->  {rel_dst}")
        if not dry:
            try:
                os.rename(src, dst)
            except OSError as e:
                print(f"    エラー: {e}")
                errors += 1

    print()
    if dry:
        print("※ ドライランです。実際に変更するには --apply を付けて実行してください。")
    else:
        ok = len(all_pairs) - errors
        print(f"完了: {ok} 件成功 / {errors} 件スキップ・エラー")


if __name__ == "__main__":
    main()
