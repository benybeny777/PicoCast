# Rust保存先の危険検出

WP-R0-4。パスと保存先ポリシーの唯一の持ち主は `picocast_core::paths`。

`settings::windows_storage_environment()` からOSのAPPDATA親と既知のOneDrive同期ルートを取得し、`StorePaths::new(data_parent, DataMode)` へ明示注入する。通常版はAPPDATA配下の `PicoCast`、開発版は `PicoCast-Dev`。独自名の同期先は `StoragePolicy.sync_roots` へ設定の正本から追加する。

`Store::open` は既定ポリシーで危険を拒否する。明示許可は `Store::open_with_policy` へ `allow_cloud_sync` / `allow_network` / `allow_fat32` を危険の種類ごとに渡す。UIの確認操作と設定保存は後続の設定画面で接続し、許可を暗黙に作らない。バックアップ先も同じポリシーを適用する。

検査対象はDB・管理ルート・バックアップ・マスターキー。UNCと既知の同期名はネットワークへアクセスする前に拒否し、既存祖先をcanonicalizeしてjunctionの実体も再検査する。Windowsは実ボリュームのドライブ種別・ファイルシステム・ラベルを照合し、ネットワークドライブ・FAT32・Google Driveを検出する。拒否時は `E-STORE-UNSAFE-PATH` を返し、DBや保存先を作成しない。

Windowsの実ローカルドライブ検査、同期/UNC/volumeの模擬分類、DB作成前の拒否・明示許可・バックアップ経路をテストした。実クラウド同期・実ネットワーク共有・実FAT32・macOS/Linuxは未実機確認。同期ソフト独自の保存先を名前だけで網羅できるとは扱わない。
