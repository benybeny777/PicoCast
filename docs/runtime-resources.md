# 外部プロセス入力とGPU資源

## 順次入力する外部処理

`picocast_core::proc::run_with_input` は `run`・`run_with_environment` と同じ起動・期限・出力上限・子孫回収を使う。`ProcessInput` へ有界 `mpsc::Receiver<Result<Vec<u8>>>` と `max_chunk_bytes` を明示する。フレーム全体をディスクやメモリにためない。

入力・標準出力・標準エラーと子プロセスの終了を同時に処理し、全体へ同じ期限を適用する。子が先に異常終了した場合は、入力producerの終了を待たず失敗を返す。入力の生成失敗、単位容量超過、書込み失敗、出力上限、期限切れはエラーにして所有した子孫を回収する。入力終了ではstdinをshutdownする。futureをdropした場合も既存の所有scopeが停止を担う。呼出側は予定フレーム数と最終動画の尺を別途検査し、producerが途中で単に終了した結果を完成扱いにしない。

調整可能な容量・期限・channelサイズは呼出側から注入する。利用者の台詞・フレーム内容・認証情報をエラーログへ含めない。

## GPUの明示実行枠

`picocast_core::gpu::GpuCoordinator` はGPU UUIDに固定した実行枠とVRAM予約を持つ。ホストはUUIDごとに1つ作り、すべてのチャンネル・画像・LLM・レンダーへcloneを共有する。`GpuRequirement` は必要量・余裕量・待機上限を明示する。GPU機能を利用者が有効にした経路でだけ取得し、機器・モデルの探索や取得、ドライバー設定の変更を自動で行わない。

`acquire` は枠を取って空きVRAMを照会し、現在の実測値と予約前基準からの残りの両方を検査する。既に実割当へ反映された予約を二重控除しない。`GpuPermit` はチャンネルと機器の照合を提供し、Cloneできない。保持中は枠と予約を維持し、dropで解放する。待機や照会中のfuture中断でも予約を残さない。

これは同じプロセスで共有するcoordinatorの調停であり、OS上の物理VRAMを独占予約するAPIではない。他アプリの使用量は実行直前にも変化する。複数ホストプロセスを同時にGPU実行する運用は、この枠だけで排他できたと扱わず、ホスト側で共通の実行所有を確保する。実GPUのメモリ不足やプロセス失敗をCPUへの無言切替で隠さない。

`NvidiaSmiProbe` は導入済み `nvidia-smi` の絶対パス・期限・出力上限を受ける。`--query-gpu=index,uuid,memory.free --format=csv,noheader,nounits --id=<UUID>` だけを発行する。GPU UUIDを照合し、MiBをchecked変換する。複数行・未知値・N/A・不一致・失敗を空き容量として扱わない。UUIDと応答全体をDebugへ出さない。

不足と待機上限は `E-GPU-BUSY`、照会不能は `E-GPU-UNAVAILABLE`、設定・状態・チャンネルの不正はそれぞれ `E-GPU-CONFIG`・`E-GPU-STATE`・`E-GPU-CHANNEL`。パイプラインはBUSYだけを待機へ分類し、確定した設定・照会失敗を無限待機にしない。

GPUの空き確認は [NVIDIA公式nvidia-smi仕様](https://docs.nvidia.com/deploy/nvidia-smi/index.html) を2026-10-16に照合した。NVIDIAの技能カタログも確認したが、VSS/Jetson等の導入スキルはこの小さな読取処理と一致しないため追加導入していない。

## ファイルと検証

ツール・素材の通常ファイル確認は `paths::require_regular_file` を共用する。絶対パス、末尾の通常ファイル、非symlink・Windows非reparseを確認する。DBなどの保存先に必要な同期フォルダ・ドライブ検査は、別の `StoragePolicy` を通す。

順次入力は有限のWindows子プロセスへ512KBのバイナリを往復させ、空いていない入力の期限切れ、生成失敗と単位容量超過を確認する。GPUは偽probeで複数枠・容量予約・チャンネル・中断・期限・N/A拒否を確認する。このPCでは導入済みnvidia-smiのメタデータ読取だけを確認し、GPU計算・NVENC・モデル取得は実行していない。

スリープ抑止の実OS処理はTauriホストが所有する。パイプラインの型だけで実Windows抑止済みと扱わず、CPU工程でも同じチャンネルの有効なRAII permitを要求する。
