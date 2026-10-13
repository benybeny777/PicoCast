# ライセンス発行（販売者用）

製品版のライセンスキーは、Google スプレッドシート＋Apps Script で自動発行する。アプリは埋め込んだ公開鍵でオフライン検証する（`core/license_key.py`）。このフォルダは配布物に含めない。

## 全体の流れ

1. 購入者が BOOTH で購入する → 販売者の Gmail に購入通知が届く。
2. `importBoothOrders`（1時間ごと）が通知を読み、「注文」シートへ注文番号を追記する。
3. 購入者が Google フォームに注文番号・メールアドレス・お名前を送る。
4. `onFormSubmit` が注文番号を照合し、キーを発行して「発行済み」シートに記録、購入者へメールで送る。
5. 返金時は「発行済み」シートの「失効」列に何か入力する。失効確認URLを設定したアプリは、起動時（既定7日ごと）に無効化される。

## 初回設置

1. 鍵を作る（1回だけ。作り直すと発行済みキーはすべて無効になる）:
   ```
   .\.venv\Scripts\python.exe tools/license/license_tool.py genkey
   ```
   秘密鍵は `~/.nvf_license/private_key.pem` に保存される。**必ずバックアップし、共有しない。**
2. スプレッドシートを作り、シートを2枚作る（1行目は見出し）:
   - `注文`: 注文番号 / 商品 / edition / packs / 受信日時 / メールID
   - `発行済み`: license_id / 注文番号 / メール / 購入者名 / edition / packs / 発行日 / 更新期限 / 失効 / メモ
3. 「拡張機能 > Apps Script」に `gas/Code.gs` を貼り付ける。
4. 「プロジェクトの設定 > スクリプトプロパティ」に `LICENSE_PRIVATE_KEY` を追加し、秘密鍵 PEM の全文を貼る。
5. Google フォームを作り、質問「注文番号」「メールアドレス」「お名前」を置いて回答先をこのスプレッドシートにする。
6. トリガーを追加する:
   - `importBoothOrders`: 時間主導型・1時間ごと
   - `onFormSubmit`: スプレッドシートから・フォーム送信時
7. （任意）「デプロイ > 新しいデプロイ > ウェブアプリ」（実行ユーザー=自分、アクセス=全員）で公開し、URL をアプリ設定 `LICENSE_REVOCATION_CHECK_URL` の既定値として製品ビルドに入れる。
8. `testIssueKey` を実行し、ログに出たキーを `license_tool.py verify <キー>` で検証できることを確認する。

## 要確認

- **BOOTH 購入通知メールの書式**: `CONFIG.BOOTH_MAIL_QUERY` / `ORDER_NUMBER_REGEX` / `PRODUCTS` は仮の値。実際の通知メールで件名・送信元・注文番号の書き方・商品名を確認して合わせる。解析できない通知があると販売者宛てに警告メールが届く。
- Gmail の送信上限（個人アカウントで1日100通程度）。

## 手動発行

注文と結びつかないキー（自分用・サポート対応など）は手元で発行できる:
```
.\.venv\Scripts\python.exe tools/license/license_tool.py issue --edition pro --buyer "名前" --update-months 0
```
失効確認を使う場合は、出力された license_id を「発行済み」シートにも記録する（未記録だとアプリに「台帳に未登録」と表示される）。
