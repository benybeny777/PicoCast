# バックアップからの旧データ取り込みと照合

WP-R1-3・WP-R1-4・WP-R1-6の開発用入口。通常の実行は、SQLiteオンラインバックアップ済みの単体DBとコピー済み素材だけを読む。元アプリのデータ・キー・生成物を直接指定しない。元のPython版を停止・削除・再実行する機能は含まない。

```powershell
cargo xtask import-legacy --initialize --config C:\PicoCastImport\initialize.json
cargo xtask import-legacy --settings --config C:\PicoCastImport\settings-import.json
cargo xtask import-legacy --channel --config C:\PicoCastImport\channel-import.json
```

引数はこの順序で指定する。設定ファイル内の相対パス、未知フィールド、未知の型、モードとkindの不一致はエラーになる。環境変数・実行中フォルダからDBやキーを探さない。設定ファイルにAPIキーやトークンの値を書かない。

## 事前条件

1. 元DBをSQLiteのオンラインバックアップで単体ファイルへ保存する。未checkpointのWALを無視したファイルコピーは使わない。`-wal`または`-shm`が付随するDBは取り込みを拒否する。
2. `backup_root`を元アプリの`original_root`とは別の実在するディレクトリにし、DB・旧キー・必要素材のコピーをその内側へ置く。リンクを解決して元フォルダやバックアップ範囲外を指す入力も拒否する。
3. 新環境は独立した`--initialize`操作で明示的に初期化する。通常版は`data_parent/PicoCast/secret_master.key`、開発版は`data_parent/PicoCast-Dev/secret_master.key`。`destination.master_key`はこの共通保存先と一致させる。通常の読み取り・取り込みでキーを自動生成しない。
4. 設定側を先に取り込み、チャンネル側には登録済みの同じ`channel_id`とタイムゾーンを指定する。運用元は`legacy`を維持し、取り込みだけで投稿や自動運用を開始しない。

以下は架空の小さなfixture用の例である。パス・型一覧・BGMの対応は対象バックアップに合わせて明示する。`original_root`も実在する元フォルダを指定する。

## 新保存先の明示初期化

```json
{
  "kind": "initialize",
  "destination": {
    "data_parent": "C:\\PicoCastData",
    "mode": "development",
    "master_key": "C:\\PicoCastData\\PicoCast-Dev\\secret_master.key",
    "busy_timeout_ms": 5000,
    "backup_pages_per_step": 16,
    "backup_pause_ms": 1
  }
}
```

保存先の安全検査後に新DBと新キーを作る。既存DB・既存キー・保存先内の既存ファイルがあれば拒否し、上書きしない。作成中のOSエラーでも既存物を削除してやり直さない。取り込み時は、保存先とバックアップだけでなく、保存先と元アプリのディレクトリ木の重複も拒否する。

## 設定側のJSON例

```json
{
  "kind": "settings",
  "destination": {
    "data_parent": "C:\\PicoCastData",
    "mode": "development",
    "master_key": "C:\\PicoCastData\\PicoCast-Dev\\secret_master.key",
    "busy_timeout_ms": 5000,
    "backup_pages_per_step": 16,
    "backup_pause_ms": 1
  },
  "source": {
    "backup_root": "C:\\PicoCastImport\\backup",
    "original_root": "C:\\OriginalPicoCast",
    "database": "C:\\PicoCastImport\\backup\\settings.db",
    "master_key": "C:\\PicoCastImport\\backup\\secret_master.key",
    "language": "ja",
    "timezone": "Asia/Tokyo",
    "setting_types": {"SAMPLE_INTEGER": "integer"},
    "retired_settings": ["LICENSE_API_URL"],
    "bgm_files": {},
    "bgm_durations_ms": {}
  }
}
```

`setting_types`は保存済み設定の全キーについて`boolean`・`integer`・`decimal`・`json`・`text`を指定する。未知キーを文字列として黙って取り込まない。`AUTOPILOT_POLICY:<profile_id>`は専用処理するので型一覧に含めない。販売など撤回済み設定は`retired_settings`へ明示し、有効設定へ移さない。廃止した設定の値は暗号化した元DBのsnapshotだけに保持し、互換行にはその参照だけを記録する。ライセンスキー等を平文AppSettingへ複製しない。平文の認証情報キーが非認証settings表にあれば停止する。

旧BGMがある場合は`bgm_files`へ旧`bgm_id`からコピー音源の絶対パスへの対応を入れる。旧DBに尺が無い音源だけ、`bgm_durations_ms`に測定済みのミリ秒値を指定する。0秒を推測しない。素材は共通保存先の内容アドレスへコピーし、ハッシュとサイズを照合する。音量・ループ・有効/既定状態・元パス等の旧行も保持する。利用規約・クレジットが旧DBに無いため、権利確認が必要なことを報告する。

旧WindowsキーはDPAPI生blobを読取り専用で復号する。旧AES-GCMのAAD無し形式を復号し、チャンネルとsecret_typeをAADに持つRust形式へ再暗号化する。欠損・別利用者・改竄・未知暗号版・孤立profileは停止し、値をログや報告へ出さない。秘密値が無い旧DBでは`source.master_key`をnullにできる。

テンプレートの版1は`format=legacy-template-v1`のenvelopeとして旧全フィールドを保持する。キャラクターの口調・規則・有効フラグ等も保持し、将来の生成側が無条件に全件有効として扱わない。読み辞書はbase/userを別所有として残す。投稿枠はShorts/Longと曜日を区別する。

元settings DB全体も、新キーでAAD付き暗号化したsnapshotとして同じtransaction内に保持し、再読取復号したbytesと元DBを比較する。未知表・未知列・BLOB・索引もこのsnapshotに残る。未知表の件数を報告し、専用写像の未確認をholdにする。autopilot_runsがこのDBに存在する場合も履歴として保持し、自動実行しない。

## チャンネル側のJSON例

```json
{
  "kind": "channel",
  "destination": {
    "data_parent": "C:\\PicoCastData",
    "mode": "development",
    "master_key": "C:\\PicoCastData\\PicoCast-Dev\\secret_master.key",
    "busy_timeout_ms": 5000,
    "backup_pages_per_step": 16,
    "backup_pause_ms": 1
  },
  "source": {
    "backup_root": "C:\\PicoCastImport\\backup",
    "original_root": "C:\\OriginalPicoCast",
    "database": "C:\\PicoCastImport\\backup\\channel-a\\metadata.db",
    "output_root": "C:\\PicoCastImport\\backup\\channel-a\\output",
    "original_output_root": "C:\\OriginalPicoCast\\output\\channel-a",
    "channel_id": "channel-a",
    "timezone": "Asia/Tokyo",
    "imported_at": "2026-10-16T00:00:00Z",
    "synthetic_media": true,
    "verified_running_jobs": {}
  }
}
```

`output_root`はコピー実体、`original_output_root`は旧DBに記録された元パスを対応づける基準である。タイムゾーン無しの旧日時は指定チャンネルのtimezoneで変換し、DSTで曖昧/存在しない日時は拒否する。`synthetic_media`は利用者が明示した値を使う。

CLIはPIDだけで実ジョブの同一性を検証できないため、`verified_running_jobs`は空のみ受け付ける。旧runningを自動再開しない。期間累計Analyticsは日次の値へ捏造せず原記録として保持する。設定・トークン・秘密鍵などの保護対象ファイルはメディアとしてコピーしない。

## 報告と停止条件

成功時は標準出力へJSONを返す。`verification=matched`はDB値の再読取・元件数・内容ハッシュなど、その入口が実施した照合の成功を示す。`status=verified_with_holds`は取り込みに成功しつつ、再承認や専用写像の確認が残る状態である。holdは成功終了、照合不一致・型エラー・復号失敗などは短いエラーと非0終了になる。報告に台本本文・秘密値・元DBの行内容を出さない。

元の自動運用設定は原文を保持するが、新しい自動運用は停止、金額予算0、理由付きの保留と通知にする。旧有料API回数を金額へ勝手に換算しない。予算の設定と再承認が必要である。

同じ入力の再実行は重複登録しない。既存の宛先が元入力と異なる場合は上書きせず停止する。登録途中の失敗はDBのtransactionをrollbackする。既存と共有され得るCAS実体は誤削除を避けて削除しないため、失敗前にコピー済みの未参照実体が残る場合がある。

synthetic fixtureの単体確認は`cargo test --locked -p picocast-store imports::tests`、チャンネル側は`cargo test --locked -p picocast-store channel_import::tests`。CLIの引数・入力境界は`cargo test --locked -p xtask import_legacy::tests`で検査する。これらは本番コピーでの全件受入、実キーの読取り、影運用や切り替えの完了を示さない。
