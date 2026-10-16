# Python 3.12 切り替え手順（実行前レビュー用）

WP-R0-2 の準備。スクリプトは作成・構文検査だけを行い、実環境の切り替えはまだ実行していない。

## 読み取り確認

```powershell
powershell.exe -NoProfile -File .\scripts\switch-python312.ps1 -CheckOnly
```

`-Apply` がない場合は常に読み取り専用。Python 3.11 の実体、Git ルート、対象プロセス、設定 DB、自動運用、各 metadata DB の queued/running と runner PID・作成日時、対象を起動する OS タスクを調べる。設定モジュールは import せず、SQLite は `mode=ro` で開く。DB・ジョブ・鍵・環境・退避フォルダを変更しない。

読み取り検査の失敗は、安定したエラーコード・対象種別・例外の分類・SQLite の分類だけを標準エラーへ JSON で出す。設定値・SQL パラメータ・例外本文・トレースは表示しない。CheckOnly ではデバッグファイルも作らない。詳細トレースを保存するのは Apply で作った退避先だけ。

Windows の venv ランチャーが起動した base Python は、親の所属・同じ runner 引数・作成順序を確認して同じ対象として数える。正規の `%SystemRoot%\System32\conhost.exe` が作成順序の一致する直接の子として存在しても作業中とは扱わないが、conhost 自体を強制終了しない。その他の子プロセスがあれば停止する。

PID が存在しない running、または PID の作成日時より古いジョブ記録は履歴として数える。ジョブの開始・心拍・作成時刻のうち最新の記録を使う。PID 未記録の running は、対象 runner の起動以前の記録と分かる場合だけ履歴とする。稼働中・判定不能な記録を「古い」と決め付けず、切り替えを停止する。履歴の削除・キャンセル・再実行はしない。

Web UI、所属不明の runner、対象の有効 OS タスク、queued、実行中または判定不能ジョブ、自動運用 ON があれば停止する。スクリプトは OS タスクを無効化しない。事前に別の作業として停止状態を確保してから再確認する。

## 明示実行

```powershell
powershell.exe -NoProfile -File .\scripts\switch-python312.ps1 -Apply
```

長時間実行なので、レビュー後に Codex Process Jobs からこの有限の foreground payload を実行する。Python 3.12 本体は既存の uv 管理領域を使い、Python 本体の自動ダウンロードを禁止する。

1. リポジトリ外の `%USERPROFILE%\.codex\backups\picocast-python312\<日時と一意ID>` へ DB のオンラインバックアップを作り、元・コピーの整合性を検査する。マスターキー、旧認証ファイル、既存ライセンス鍵、未コミット差分、index 差分、未追跡ファイルを退避・照合する。秘密値は標準出力や通常ログに出さない。
2. Python 3.11 の隔離全テストとオフラインオラクルを実行し、テスト ID 一覧・件数・skip 件数を保存する。失敗したら環境を移動しない。
3. プロセス・DB・OS タスクを再確認し、対象ワークスペースの idle runner だけを親子関係の葉から停止する。PID の大小を停止順に使わない。PID と作成日時を再照合し、プロセスハンドルを保持してから終了させる。停止ごとに再検査し、別の runner が再生成されたら新プロセスには触れず中止する。別ワークスペース・所属不明・処理中のプロセスは停止しない。
4. 停止後にもう一度、別の退避先へオンラインバックアップを作る。`.venv` を `.venv-311-backup` に移し、`uv sync --locked --group build --group dev --python 3.12` で新しい `.venv` を作る。既存の `.venv-311-backup` があれば上書きしない。uv に課金 API の認証環境変数やユーザーの index 設定を渡さない。
5. Python 3.12 の全テストとオラクルを実行する。旧版とテスト ID・件数・skip 件数が一致しなければ不合格にする。デバッグ出力は退避先だけに保存する。
6. 途中で失敗したら、部分的な新 `.venv` を専用 `temp/python312-switch/failed-environment-<ID>` に保管し、旧環境を元の `.venv` へ戻す。旧環境や部分環境を削除しない。停止した runner は自動再起動しない。

処理単位の時間上限は `-OperationTimeoutSeconds`（既定3600秒）、runner 終了待機は `-StopTimeoutSeconds`（既定30秒）。退避先の親は `-BackupParent` で指定できるが、リポジトリ内を拒否する。

## 別途必要な受入

全テストとオラクルの一致は、実生成・実レンダーの確認を代替しない。実サンプルが未実行なら WP-R0-2 全体を完了にせず、`.venv-311-backup` を保持する。アプリと runner の再起動、外部の VOICEVOX / SD / Ollama の実利用確認も別に記録する。

スクリプトが表示する成功は「3.12環境と隔離検証の成功」まで。失敗時は退避先の `app_debug_migration.log` と実際の `.venv` / `.venv-311-backup` を照合する。rollback 自体が失敗した場合も旧環境を消さず、実体を確認して元の場所へ戻す。

準備の限定 fixture 検証は `python -m pytest tests/test_python312_switch.py -q`。PID の不在・再利用、実 running、日時欠損と作成時刻、判定不能、queued、不正な自動運用設定、読み取り専用接続、WAL を含むバックアップと元 DB/鍵のハッシュ不変を一時データで確認する。実際の停止・環境移動・uv sync をこの fixture 検証では実行しない。
