"""
YouTube再生リスト管理スクリプト。

config/playlists.json          -- 再生リスト定義（名前・説明・優先度）
config/playlist_assignments.json -- 動画ごとのメイン/補助リスト割り当て

コマンド:
  py -3 tools/manage_playlists.py create [--dry-run]
      再生リストを全作成（既存は名前一致でスキップ）。
      --dry-run で実際には作成せず内容を表示するだけ。

  py -3 tools/manage_playlists.py assign [--dry-run]
      playlist_assignments.json に従い既存動画を振り分ける。
      --dry-run で実際には変更せず予定を表示するだけ。

  py -3 tools/manage_playlists.py status
      playlists.json の現在の状態（youtube_id の有無）を表示。
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PLAYLISTS_FILE = os.path.join(_ROOT, "config", "playlists.json")
_ASSIGNMENTS_FILE = os.path.join(_ROOT, "config", "playlist_assignments.json")


def _load_playlists() -> list[dict]:
    with open(_PLAYLISTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_playlists(playlists: list[dict]) -> None:
    with open(_PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(playlists, f, ensure_ascii=False, indent=2)


def _load_assignments() -> list[dict]:
    with open(_ASSIGNMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _playlist_name_by_key(playlists: list[dict], key: str) -> str:
    for p in playlists:
        if p["key"] == key:
            return p["name"]
    raise ValueError(f"プレイリストキーが見つかりません: {key!r}")


def _playlist_id_by_key(playlists: list[dict], key: str) -> str | None:
    for p in playlists:
        if p["key"] == key:
            return p.get("youtube_id")
    return None


def cmd_create(dry_run: bool) -> None:
    from core.youtube_uploader import create_playlist

    playlists = _load_playlists()
    changed = False
    for pl in sorted(playlists, key=lambda p: p["priority"]):
        name = pl["name"]
        desc = pl.get("description", "")
        existing_id = pl.get("youtube_id")
        if existing_id:
            print(f"  [スキップ] {name}  (youtube_id 登録済み: {existing_id})")
            continue
        if dry_run:
            print(f"  [dry-run] 作成予定: {name}")
            continue
        result = create_playlist(name, desc)
        if result["ok"]:
            tag = "新規作成" if result["created"] else "既存を使用"
            print(f"  [✅ {tag}] {name}  id={result['id']}")
            pl["youtube_id"] = result["id"]
            changed = True
        else:
            print(f"  [❌ 失敗] {name}  reason={result['reason']}")
    if changed:
        _save_playlists(playlists)
        print(f"\nplaylists.json を更新しました。")


def cmd_assign(dry_run: bool) -> None:
    from core.youtube_uploader import add_video_to_playlist_by_name

    playlists = _load_playlists()
    assignments = _load_assignments()

    if not dry_run:
        missing_ids = [p["name"] for p in playlists if not p.get("youtube_id")]
        if missing_ids:
            print("⚠ 以下の再生リストが未作成です。先に create コマンドを実行してください:")
            for n in missing_ids:
                print(f"  - {n}")
            sys.exit(1)

    ok = skip = fail = not_found = 0
    not_found_videos: list[str] = []
    for entry in assignments:
        video_id = entry["video_id"]
        title = entry.get("title", video_id)
        entry_not_found = False
        for role, key in [("メイン", entry["main"]), ("補助", entry.get("supplementary"))]:
            if not key:
                continue
            playlist_name = _playlist_name_by_key(playlists, key)
            if dry_run:
                print(f"  [dry-run] {role}: {title[:40]}  →  {playlist_name}")
                continue
            result = add_video_to_playlist_by_name(video_id, playlist_name)
            if result.get("not_found") and not entry_not_found:
                entry_not_found = True
                not_found += 1
                not_found_videos.append(f"{video_id}  {title}")
            if result["ok"] and not result["skipped"]:
                print(f"  [✅ {role}追加] {title[:40]}  →  {playlist_name}")
                ok += 1
            elif result["skipped"]:
                print(f"  [skip {role}] {title[:40]}  →  {playlist_name}  ({result['reason']})")
                skip += 1
            elif result.get("not_found"):
                print(f"  [🗑 削除済み] {title[:40]}  ({video_id})")
                break
            else:
                print(f"  [❌ {role}失敗] {title[:40]}  →  {playlist_name}  ({result['reason']})")
                fail += 1

    if not dry_run:
        print(f"\n完了: ✅{ok}件追加 / ⏭{skip}件スキップ / 🗑{not_found}件削除済み / ❌{fail}件失敗")
        if not_found_videos:
            print("\n削除済み動画一覧（playlist_assignments.json から除外を推奨）:")
            for v in not_found_videos:
                print(f"  {v}")


def cmd_status() -> None:
    playlists = _load_playlists()
    assignments = _load_assignments()

    key_count: dict[str, int] = {}
    for entry in assignments:
        for key in [entry["main"], entry.get("supplementary")]:
            if key:
                key_count[key] = key_count.get(key, 0) + 1

    print(f"{'優先度':4} {'キー':<18} {'動画数':>5}  {'youtube_id':<26}  名前")
    print("-" * 100)
    for pl in sorted(playlists, key=lambda p: p["priority"]):
        youtube_id = pl.get("youtube_id") or "(未作成)"
        count = key_count.get(pl["key"], 0)
        print(f"  {pl['priority']:2}  {pl['key']:<18} {count:>5}本  {youtube_id:<26}  {pl['name']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube再生リスト管理")
    sub = parser.add_subparsers(dest="cmd")

    p_create = sub.add_parser("create", help="再生リストを作成する")
    p_create.add_argument("--dry-run", action="store_true")

    p_assign = sub.add_parser("assign", help="動画を再生リストへ振り分ける")
    p_assign.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="現在の状態を表示する")

    args = parser.parse_args()
    if args.cmd == "create":
        cmd_create(args.dry_run)
    elif args.cmd == "assign":
        cmd_assign(args.dry_run)
    elif args.cmd == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
