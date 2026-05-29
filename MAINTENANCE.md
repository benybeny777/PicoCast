# MAINTENANCE.md — 期限付きメンテナンス予定

このファイルには「特定の日付に削除・変更すべきコード」を記録する。
期限が来たらユーザーに確認したうえで実施し、完了したらこのファイルから該当エントリを削除する。

---

## 2026-06-29 旧フォルダプレフィックス互換コードの削除

### 背景

2026-05-29 に動画フォルダのプレフィックスを `[Shorts]`/`[Long]`/`[ネタ会議]` から
`Shorts_`/`Long_`/`ネタ会議_` に変更した。
PowerShell で `[]` がグロブの文字クラスとして解釈される問題への対処。

アプリ起動時の `auto_migrate()` が旧形式フォルダを自動リネームするため、
1か月後には旧形式フォルダが存在しないはず。その時点で互換コードを削除する。

### 削除対象

以下のファイルに `TODO: 2026-06-29 以降に削除` コメントが付いている。

#### `config/config.py`

```python
# TODO: 2026-06-29 以降に "[Shorts]"/"[Long]"/"[SHORT]"/"[LONG]"/"[ネタ会議]" を削除
_LEGACY_FOLDER_PREFIXES = ("Shorts_", "Long_", "ネタ会議_", "[Shorts]", "[Long]", "[SHORT]", "[LONG]", "[ネタ会議]")
```

削除後:
```python
_LEGACY_FOLDER_PREFIXES = ("Shorts_", "Long_", "ネタ会議_")
```

#### `web_app/security.py` — `is_video_folder`

```python
# 削除: "[Shorts]", "[Long]", "[ネタ会議]",  # 旧形式 互換 TODO: 2026-06-29 以降に削除
```

削除後:
```python
return name.startswith((
    config.FOLDER_PREFIX_SHORTS, config.FOLDER_PREFIX_LONG, config.FOLDER_PREFIX_MEETING,
))
```

#### `web_app/services/history_service.py` — `_video_format_from_name`

```python
# 削除: # 旧形式 互換 TODO: 2026-06-29 以降に...
# 各 startswith タプルから "[Shorts]"/"[Long]"/"[ネタ会議]" を除去
```

#### `core/native_renderer.py` — `_video_size`

```python
# 削除: "[Shorts]", "[SHORT]" をタプルから除去
if os.path.basename(output_dir).startswith((_cfg.FOLDER_PREFIX_SHORTS,)):
```

#### `core/youtube_uploader.py` — `infer_video_type` / `upload_video`

```python
# 削除: "[Long]"/"[LONG]" / "[Shorts]"/"[SHORT]" をタプルから除去
# 削除: "[Shorts]" in str(mp4_path) の条件を除去
```

#### `core/analytics_score.py`

```python
# 削除: "[Shorts]" in title の条件を除去（Shorts_ のみ残す）
```

#### `core/parser.py`

```python
# 削除: "[Shorts]" in title_text の条件を除去（Shorts_ のみ残す）
```

#### `scripts/migrate_folder_prefixes.py`

`_RENAMES` リストから旧エントリを削除。
`auto_migrate()` の lifespan 呼び出し（`web_app/app.py`）も、
全フォルダの移行が完了していれば削除してよい。

### 削除前の確認事項

1. `output/`・`output/000_uploaded/`・`output/000_backups/` に旧形式フォルダが残っていないことを確認
   ```
   python scripts/migrate_folder_prefixes.py  # ドライランで 0 件なら OK
   ```
2. 問題なければ上記コードを削除してテストを実行
