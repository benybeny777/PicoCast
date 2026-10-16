# PSDレイヤーの移行書き出し

WP-R1-5の実装。元PSDを読み取る一度きりのPython道具で、Rustの通常実行時はPSDを解析しない。ソースPSD・既存書き出し先・実設定DBを上書きしない。新しい出力先には`layers/`、`variants/`、`manifest.json`だけを保存する。

## 書き出し

旧版の`.venv`にあるpsd-toolsとPillowを使う。許容差はCLIで明示する。0はRGBA全チャンネルの完全一致で、透明画素内のRGBも比較する。

```powershell
.venv\Scripts\python.exe tools/export_psd_layers.py C:\素材\zundamon.psd C:\移行\zundamon --pixel-tolerance 0 --legacy-character zundamon
.venv\Scripts\python.exe tools/export_psd_layers.py C:\素材\metan.psd C:\移行\metan --pixel-tolerance 0 --legacy-character metan
```

`--legacy-character`は旧`core/native_character_assets.py`が列挙するbase・口3種・目閉じと、`core/character_expressions.py:EXPRESSION_PRESETS`の全表情を対象にする。旧選択ロジックをコピーせず、同じ関数を実行して可視状態と旧合成PNGを記録する。`tools/oracle_environment.py`の共通隔離を`work_name="psd-layer-export"`で使い、設定初期化・参照合成・キャッシュは専用の一時環境へ閉じ込める。DesktopのPSD探索や別キャラクターの実素材検索は呼ばない。

任意キャラクターには`--variants <JSON>`を指定できる。JSONは`[{"id":"表情名","visibility":{"0":true,"1":false}}]`の配列で、全レイヤーIDを真偽値で明示する。IDはPSD階層の0始まりの番号（例`1/0`）で、同名レイヤーも区別する。default表情は常に含める。`--legacy-character`を省略した場合は、旧キャラクターの全presetを検証済みとは扱わない。

## manifestと品質判定

形式の正本は`tools/psd_layer_manifest.schema.json`のversion 1。全レイヤーとグループをフルキャンバスRGBA PNGとして保存し、階層・順序・名前・位置・可視状態・不透明度・混合方式・各PNGのSHA-256を記録する。元PSDのSHA-256は書き出し前後で照合する。

表情ごとに旧psd-toolsの合成と、書き出したPNGの通常alpha合成を比較する。`max_abs_channel_diff`は1チャンネルの最大差、`mismatched_pixels`は4チャンネルのいずれかが異なる画素数。許容差を超える、乗算などの混合方式・クリッピング・グループの不透明度やマスクがある場合は`qualified=false`にして、CLIを終了コード2で止める。画素差が0でも未対応の混合方式を合格にはしない。未適格の結果は調査用に残し、Rustへの登録を拒否する。

表情PNGを使う区間の口パク・まばたき差分を無効にする契約は`expression_overlay_policy`へ記録する。実際の動画合成の実装はWP-R2-6で行う。旧版の手描きまばたき補助・差分オーバーレイはPSDレイヤーではないため、この書き出しの画素同等性の対象に含めない。利用者が別途登録した表情PNGも自動探索しない。

## Rustへの登録

`Store::register_character_layers(channel_id, character_id, manifest_path, assets_root)`を使う。`assets_root`は`StorePaths::assets_directory()`から渡す。チャンネル内に既に登録したキャラクターだけを指定できる。

manifestの形式・階層・全表情の可視map・資格・旧preset網羅性、PNGのヘッダーと寸法、全ファイルのサイズとSHA-256を検査する。PNGとmanifestを共通CASへ保存し、`characters.layer_manifest_sha256`・キャラクター所有の`asset_refs`・監査記録を1 transactionで更新する。同じmanifestの登録は冪等。既存の素材や以前のmanifest参照を削除しない。失敗時はDB登録をrollbackし、共有され得る未参照CAS実体は削除しない。

Rustの登録口はPNGの全デコードや画素再合成を行わず、書き出し時の比較結果とファイルのハッシュを検証する。Rust自身の再合成と動画受入はWP-R2-6の検査対象である。

## 検証と証拠の範囲

```powershell
.venv\Scripts\python.exe -m unittest tests.test_export_psd_layers -v
cargo test --locked -p picocast-store character_layers::
```

合成fixtureで通常レイヤー・非表示差分・元PSDの不変・上書き拒否・未対応blendの不合格・可視map欠損を検査する。ずんだもん/四国めたんの既存native 5種と既存expression 5種を、それぞれdefaultを含む11種として同じ旧選択処理で列挙し、PNG再合成の画素差0を確認した。登録fixtureでは冪等・同内容PNGの重複排除・別チャンネル拒否・改変/未適格/欠損manifestの拒否を確認する。

**利用者の実PSD・実表情・実画面では未確認。** 合成fixtureの成功を全キャラクターの本番画素同一やWP-R2-6完了とは扱わない。

CLIエラー`E-PSD-EXPORT`は一度きりのPython開発用道具のコードで、旧Pythonアプリへ機能を追加しない。内部トレースは`app_debug_import.log`にだけ保存し、利用者向けには原因カテゴリと確認手順を表示する。ログ先の既定は`temp/psd-layer-export/logs/`、変更は`--log-dir`で明示する。Rustの登録失敗は`E-PSD-REGISTER`を返す。
