# 旧版オラクルの比較契約

WP-R1-7。入力は架空の文章・チャンネル設定・指標だけで構成し、実チャンネル・秘密値・動画を含めない。

- `inputs/v1.json`: `contract_version=1`、`cases`の各要素が一意な`id`、`kind`、`input`を持つ。
- `expected/v1.json`: 同じ`id`と`kind`に、旧版の関数が返した`output`を対応させる。文字列はUTF-8、日時はオフセット付きISO 8601、JSONのnullと数値を保つ。オブジェクトのキー順は比較対象にせず、配列順・文言・数値を比較する。
- `reading`: 辞書の優先順・長い語の優先・Sudachiによる安全な自動補正。Sudachiと辞書の版はuv.lockで固定する。
- `script`: 日本語・英語メタ、表情付き台詞、背景、テロップ、固定コメント。旧版が解析結果から除くチャプターも現在の挙動として記録する。
- `metadata`: 架空のジャンル設定を明示注入し、タイトルの空白処理・説明・タグ・ハッシュタグを確認する。設定取得の境界だけを固定し、組み立て関数は旧版を実行する。
- `schedule`: 固定時計・既使用枠・5分余裕・日付境界。YouTubeへ接続しない。
- `score`と`expansion`: データ待ち・非公開・ゼロ再生、音切れ日付境界、単発の参考観察、同構造2件の横展開候補、配布不足。横展開の厳格化d949061後の現行関数を記録する。

Rust移植はこの入力を共通の比較入力として読み、各分野の期待値と照合する。現状のxtaskは契約の構造と旧版での再現性までを検査し、Rust実装の同等性は各R2/R3のWPで追加する。

## 実行

リポジトリルートから`.venv/Scripts/python.exe tools/oracle.py`（macOSでは`.venv/bin/python tools/oracle.py`）。`cargo xtask oracle`も同じ処理を実行する。

旧版の全体確認は`.venv/Scripts/python.exe -m pytest tests -q`。`tests/conftest.py`がcollectionより前に`tools/oracle_environment.py`を呼び、DB・キー・出力の基準を`temp/legacy-tests/session-*`へ隔離する。既存の設定環境変数を除き、暗黙の.env読込みを一時領域へ向ける。実資産のコードと設定seedはコピーまたは読取りだけに使用し、実DBを開かない。socket接続は拒否し、通信が必要な個別テストは依存をモックする。WindowsのAnyIO用self-pipeは、標準socketpair呼出中の同一スレッドだけ内部接続を許可する。通常のloopback接続は引き続き拒否する。各テストのmonkeypatchはこの一時環境に対して適用する。

設定済みチャンネルを前提にする旧テストは`configured_test_channel`を明示利用する。架空のprofileと空のジャンル設定をテストごとに作り、未設定エラーを検査するテストの前提は変更しない。

Web画面の起動では、runner起動、OSタスク修復、ライセンス更新、外部サービスの調査ログと設定先読みをsession fixtureで置き換える。画面に必要なstatusの組み立ては維持し、VOICEVOX・ffmpeg・Ollama・SD・AquesTalkの調査とOllama一覧取得の境界だけを固定する。対象機能そのものの単体テストは個別monkeypatchで上書きできる。Geminiの選択分岐テストは架空の秘密値とfakeクライアントを注入し、API接続も実キー登録も行わない。

投稿枠同期テストはmetadata.dbの場所も各テストの一時領域へ向ける。これによりactive profile未設定の空環境でも、実チャンネルに依存せず同期アルゴリズムを検査する。

`--emit-json`は基準候補を標準出力へ出すだけで既存基準を書き換えない。基準を変える場合は理由・差分・該当WPをレビューし、品質の後退を自動承認しない。初回基準の記録時はPython 3.11の既存.venvを使用。Python 3.12環境への切り替え後にも同じ基準で再検証する。
