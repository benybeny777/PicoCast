# 暗号化バックアップと復元訓練

`picocast_store::portable_backup` は、SQLiteのオンラインバックアップと素材目録をパスフレーズで暗号化し、新しい保存先へ復元する共通APIである。実データの移行承認・画面・定期runnerの接続とは分けて扱う。

## 保存と復元

- `Store::export_portable(paths, source_key, passphrase, destination, offsite, options)` で新規保存する。既存保存先と元データ領域への重複を拒否する。元DB・キー・素材は変更しない。
- `restore_portable(bundle, passphrase, destination, store_options, options)` は存在しない保存先だけを受け付ける。認証・目録・件数・DB整合性を確認し、同じ親の一時領域から完成したディレクトリを公開する。途中失敗では復元先を公開しない。
- `PortableReport` はチャンネル・素材・秘密値の件数、DBと素材の合計バイト数、別置きコピー照合結果を返す。秘密値を返さない。

エクスポート対象のDBスナップショットからschema version・全テーブル件数・素材目録を取得し、全秘密値と旧設定DB暗号スナップショットを元キーで復号確認する。DBと素材を暗号化後に復号・SHA-256照合してから公開する。復元時は認証済み目録と復元DBの素材一覧も一致させる。

暗号化方式はArgon2id（version 0x13、32バイト導出）と既存共通のAES-GCMである。ファイルはchunkごとに独立したランダムnonceを使い、bundle識別子・header情報・ファイル役割・chunk番号・平文長を認証文脈へ含める。順序変更・末尾追加・切断・内容変更を拒否する。[Argon2 API](https://docs.rs/argon2/0.6.0/argon2/struct.Argon2.html)

元の暗号キー材料は暗号化された目録内だけに含める。元のDPAPI保護ファイルを可搬キーとしてコピーしない。復元時は新キーを生成し、通常の秘密値と旧DB暗号スナップショットを新キーで再暗号化し、復元先のDPAPIで新規保存する。現行キー保存方式による実復元対応はWindowsで確認している。

パスフレーズはバイト列の引数で受け取り、argv・設定JSON・ログ・Debugへ出す入口は設けない。呼出元も対話入力または秘密入力のバッファを使い、使用後に消去すること。KDF値・上限・最小パスフレーズ長・chunk上限・header/目録/素材数/合計容量上限は`PortableOptions`で明示注入する。テスト用の小さいKDF値を運用既定に流用しない。復元元headerのKDF指定も呼出側上限で検証する。

## 別置きコピー

平文DBの一時領域と最初の暗号化成果物はローカルの安全な保存先に置く。`offsite`指定時だけ、完成した暗号化ファイルを別置き先へコピーし、ファイルごとにSHA-256を照合する。NAS・同期先への許可は`offsite_policy`へ明示注入する。NAS・同期先のDBを直接開かない。

`offsite_verified=true`はコピー内容の一致を表す。物理的に別のドライブであること、Google Drive等の同期完了、別PCでの実復元までは証明しない。元データと保存先の包含関係は拒否するが、物理媒体の分離とクラウド同期は運用側で確認する。別置きコピーに失敗した場合はエラーを返す。この時点で完成済みローカルバックアップが残る場合がある。

## 復元訓練

`restore_drill_due(at, interval)`は最後の記録から指定期間が経過したかを返す。週1回の運用では設定正本から7日間を注入する。0期間と時刻逆行は拒否する。

`run_restore_drill(bundle, passphrase, scratch, store_options, options, channel)`はscratchの親に所有する専用TempDirを作り、その中へ保存先を移して実復元する。全DBハンドルを解放してからTempDirを明示削除する。渡された既存scratchや他のファイルは削除しない。復元失敗・一時領域削除失敗はログと`DrillOutcome`に失敗として残す。

`record_restore_drill`は全体設定`backup.restore_drill.latest`へ結果を保存する。チャンネル未設定でも失敗を参照できる。チャンネルを指定した場合は通知も同一transactionで記録し、成功時に既存失敗通知を解決する。パスフレーズや内部トレースを結果へ含めない。

定期runnerからのtick呼出、秘密入力画面、全体結果と通知の画面表示は後続実装で接続する。このAPIだけで週次自動実行が稼働済みとは扱わない。

## 合成fixtureでの確認

`cargo test -p picocast-store portable_backup --lib`で、秘密値と旧DBスナップショットの再暗号化、素材照合、暗号化済み別置きコピー、誤パスフレーズ、暗号破損、誤元キー、認証済み目録とDBの不一致、部分復元の非公開、訓練後の一時領域削除、既存scratch保護、KDF上限、チャンネル無し結果記録を確認する。実DB・実キー・外部サービスは使わない。
