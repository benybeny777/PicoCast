"""
旧 output/ 直下のデータを active profile の output_root 配下へ移行するモジュール。

旧構造:
  output/000_data/       ← metadata.db など
  output/000_analytics/  ← Analytics ファイル
  output/000_uploaded/   ← アップロード済みアーカイブ
  output/000_backups/    ← バックアップ
  output/Shorts_xxx/     ← 動画フォルダ（あれば）
  output/Long_xxx/

新構造（profile 別）:
  output/{profile_id}/000_data/
  output/{profile_id}/000_analytics/
  output/{profile_id}/000_uploaded/
  output/{profile_id}/000_backups/
  output/{profile_id}/videos/Shorts_xxx/

移行ルール:
- active profile が1件設定されている場合のみ実行
- 移行済みマーカー（output/{profile_id}/.migrated_from_root）があればスキップ
- 移動先に同名フォルダ/ファイルが既存の場合はスキップ（上書きしない）
- 旧ファイルは移動するのではなく、移動後に元の場所から削除はしない
  （ユーザーが確認してから手動削除できるよう残す）
- 勝手に別 profile へ振り分けない
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

# 旧構造のシステムディレクトリ（動画フォルダではないもの）
_OLD_SYSTEM_DIRS = {
    "000_data", "000_analytics", "000_uploaded",
    "000_backups", "000_legacy", "000_debug",
}

_MIGRATION_MARKER = ".migrated_from_root"


@dataclass
class MigrationResult:
    profile_id: str
    moved_dirs: list[str] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    already_done: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def _marker_path(profile_output_root: str) -> str:
    return os.path.join(profile_output_root, _MIGRATION_MARKER)


def needs_migration(old_output_root: str, profile_output_root: str) -> bool:
    """
    移行が必要かどうかを判定する。

    - 旧=新 ならスキップ
    - 移行済みマーカーがあればスキップ
    - 旧 output_root にシステムディレクトリまたは動画フォルダがあれば True
      （profile_output_root が old_output_root の配下でも判定を継続する）
    """
    old_real = os.path.realpath(old_output_root)
    new_real = os.path.realpath(profile_output_root)

    if old_real == new_real:
        return False  # 同一ディレクトリ

    if os.path.isfile(_marker_path(profile_output_root)):
        return False  # 移行済み

    # 旧 output_root のシステムディレクトリに中身があるか確認
    # （新 profile_output_root が旧の配下にある場合でも判定する）
    for d in _OLD_SYSTEM_DIRS:
        old_d = os.path.join(old_output_root, d)
        new_d = os.path.join(profile_output_root, d)
        if not os.path.isdir(old_d):
            continue
        # 旧に中身があり、かつ新の対応フォルダに同名アイテムがない
        try:
            old_items = set(os.listdir(old_d))
            new_items = set(os.listdir(new_d)) if os.path.isdir(new_d) else set()
            # 旧にのみ存在するアイテムがあれば移行対象
            if old_items - new_items:
                return True
        except OSError:
            pass

    # 動画フォルダ（Shorts_ / Long_ / ネタ会議_ で始まるもの）があるか
    try:
        from config.config import FOLDER_PREFIX_SHORTS, FOLDER_PREFIX_LONG, FOLDER_PREFIX_MEETING
        prefixes = (FOLDER_PREFIX_SHORTS, FOLDER_PREFIX_LONG, FOLDER_PREFIX_MEETING)
        new_videos = os.path.join(profile_output_root, "videos")
        new_video_names = set(os.listdir(new_videos)) if os.path.isdir(new_videos) else set()
        for name in os.listdir(old_output_root):
            if name.startswith(prefixes) and name not in new_video_names:
                return True
    except Exception:
        pass

    return False


def migrate_output_to_profile(
    old_output_root: str,
    profile_output_root: str,
    profile_id: str,
    dry_run: bool = False,
) -> MigrationResult:
    """
    旧 output_root のデータを active profile の output_root 配下へ移行する。

    dry_run=True のとき実際の移動は行わず、移行対象の一覧だけ返す。
    """
    result = MigrationResult(profile_id=profile_id)

    if not needs_migration(old_output_root, profile_output_root):
        result.already_done = True
        _logger.debug("[OutputMigration] 移行不要またはマーカー確認済み")
        return result

    _logger.info(
        "[OutputMigration] 移行開始: %s → %s (dry_run=%s)",
        old_output_root, profile_output_root, dry_run,
    )

    # ── システムディレクトリの移行 ─────────────────────────────────────────
    dir_map = {
        "000_data":      os.path.join(profile_output_root, "000_data"),
        "000_analytics": os.path.join(profile_output_root, "000_analytics"),
        "000_uploaded":  os.path.join(profile_output_root, "000_uploaded"),
        "000_backups":   os.path.join(profile_output_root, "000_backups"),
        "000_legacy":    os.path.join(profile_output_root, "000_legacy"),
    }

    for old_name, new_dir in dir_map.items():
        old_dir = os.path.join(old_output_root, old_name)
        if not os.path.isdir(old_dir):
            continue
        _migrate_directory(old_dir, new_dir, result, dry_run)

    # ── 動画フォルダの移行 ────────────────────────────────────────────────
    try:
        from config.config import FOLDER_PREFIX_SHORTS, FOLDER_PREFIX_LONG, FOLDER_PREFIX_MEETING
        prefixes = (FOLDER_PREFIX_SHORTS, FOLDER_PREFIX_LONG, FOLDER_PREFIX_MEETING)
    except Exception:
        prefixes = ("Shorts_", "Long_", "ネタ会議_")

    videos_dir = os.path.join(profile_output_root, "videos")
    try:
        for name in sorted(os.listdir(old_output_root)):
            if not name.startswith(prefixes):
                continue
            src = os.path.join(old_output_root, name)
            dst = os.path.join(videos_dir, name)
            if not os.path.isdir(src):
                continue
            if os.path.exists(dst):
                result.skipped_dirs.append(f"videos/{name} (移動先が既存)")
                continue
            if not dry_run:
                os.makedirs(videos_dir, exist_ok=True)
                shutil.move(src, dst)
                _logger.info("[OutputMigration] 移動: %s → %s", name, dst)
            result.moved_dirs.append(f"videos/{name}")
    except OSError as e:
        result.errors.append(f"動画フォルダスキャン失敗: {e}")

    # ── 移行済みマーカーを書く ────────────────────────────────────────────
    if not dry_run and not result.errors:
        try:
            os.makedirs(profile_output_root, exist_ok=True)
            with open(_marker_path(profile_output_root), "w", encoding="utf-8") as f:
                import datetime
                f.write(
                    f"migrated_at: {datetime.datetime.now().isoformat()}\n"
                    f"from: {old_output_root}\n"
                    f"profile_id: {profile_id}\n"
                    f"moved: {len(result.moved_dirs)}\n"
                    f"skipped: {len(result.skipped_dirs)}\n"
                )
        except OSError as e:
            _logger.warning("[OutputMigration] マーカー書き込み失敗: %s", e)

    _logger.info(
        "[OutputMigration] 完了: moved=%d skipped=%d errors=%d",
        len(result.moved_dirs), len(result.skipped_dirs), len(result.errors),
    )
    return result


def _migrate_directory(
    src_dir: str, dst_dir: str, result: MigrationResult, dry_run: bool
) -> None:
    """src_dir の中身を dst_dir へマージ移動する（ファイル単位・上書きなし）。"""
    if not dry_run:
        os.makedirs(dst_dir, exist_ok=True)

    try:
        entries = os.listdir(src_dir)
    except OSError as e:
        result.errors.append(f"{src_dir}: {e}")
        return

    dir_name = os.path.basename(src_dir)
    for name in entries:
        src_item = os.path.join(src_dir, name)
        dst_item = os.path.join(dst_dir, name)
        rel = f"{dir_name}/{name}"

        if os.path.exists(dst_item):
            result.skipped_dirs.append(f"{rel} (移動先が既存)")
            _logger.debug("[OutputMigration] スキップ（既存）: %s", rel)
            continue

        if not dry_run:
            try:
                shutil.move(src_item, dst_item)
                _logger.info("[OutputMigration] 移動: %s", rel)
            except OSError as e:
                result.errors.append(f"{rel}: {e}")
                continue
        result.moved_dirs.append(rel)


def auto_migrate_output(dry_run: bool = False) -> MigrationResult | None:
    """
    lifespan から呼ぶ。active profile が設定されていれば移行を試みる。
    profile 未設定・移行不要の場合は None を返す。
    """
    try:
        from core.channel_profile import get_active_profile
        profile = get_active_profile()
        if profile is None:
            return None

        from config.config import OUTPUT_DIR as _old_root
        old_root = os.path.abspath(_old_root)
        new_root = profile.output_root_abs

        if not needs_migration(old_root, new_root):
            return None

        return migrate_output_to_profile(
            old_root, new_root, profile.profile_id, dry_run=dry_run
        )
    except Exception as e:
        _logger.error("[OutputMigration] 自動移行エラー: %s", e)
        return None
