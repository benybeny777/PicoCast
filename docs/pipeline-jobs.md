# 永続ジョブと工程DAG

`picocast-pipeline`は、既存の`jobs`・`job_steps`・`step_cache`を使う生成基盤である。ジョブIDとChannelIdを全操作へ明示する。実プロバイダ・全QA・YouTube投稿・実レンダーはこのWPで実装済みとは扱わない。

## 工程と計画

`Step`はNAME、VERSION、serdeのInput/Output、非同期runを持つ。`StepCtx`へchannel/job/node、安定したoperation_key、依存工程の出力、入力素材hash、モデル、設定、既存のCancellationを渡す。InputはNode.inputをその型で復元する。設定・モデル・素材をctx以外の隠れた状態から選ぶ実装を作らない。HTTP・プロセス・ファイル書込みは既存共通境界を使い、有料呼出はAI Gatewayと同じstore費用台帳へ接続する。

`Dag.nodes`は工程名・版・ソースSHA-256・入力JSON・入力素材SHA-256集合・モデルID・設定JSON・依存node・GPU有無・再実行安全性・cache方針を明示する。重複ID、循環、存在しない依存、版・実装hashの不一致は開始前に拒否する。入力JSONと設定JSONに秘密値を入れない。素材の実パスを内容の識別子にせず、CASのSHA-256を渡す。

`Pipeline::register`で型付きStepを登録し、`enqueue(store, NewJob, Dag)`で計画とジョブを一つの取引に保存する。計画は予約工程`$pipeline.plan`のJSONへ保持し、既存ジョブの計画を上書きしない。編集後のプロジェクト版は新しいjobへenqueueし、変更のない工程を共通cacheから再利用する。

`tick(store, channel, worker, cancel)`は、永続計画がある対象channelのジョブだけを原子的に取得し、最大1nodeを進めて実行権を解放する。他の利用者のqueueを取得・失敗扱いにしない。完了済み工程を再読取し、現在の入力hashと来歴を照合して次を決める。状態と結果は`TickOutcome`およびDBへ残す。

## リースと失敗

`Store::claim_job`と`claim_job_for_step`はImmediate transactionで取得する。優先度、作成時刻、IDの順で候補を選ぶ。各取得で新しいランダムfencing tokenをlease_ownerへ保存するため、同じworker名で取り直しても古い実行者の心拍・結果保存は通らない。期限・時刻は共通Timestampで比較し、RFC3339文字列の辞書順に依存しない。

`LeaseOptions`の期限と固着期間、`RunOptions`の心拍間隔・工程timeout・node数上限・payload上限を設定正本から注入する。心拍間隔は期限・固着期間より短くする。工程中は心拍を更新し、期限切れ・固着では安全な工程の先頭から回復する。実装は実行loopを長時間同期処理で塞がず、重い処理を共通外部プロセス等へ委譲する。

`attempts`は実失敗と固着回復の回数である。取得や通常のyield、offline/gpu_busy/quota/budget/window待機、cancelは増加させない。最大回数に達した失敗はterminal failedにする。待機のresume時刻を指定した場合だけ期限後に自動取得する。時刻なしの待機は`resume_waiting_job`の明示操作まで保持する。

`request_job_cancel`はqueue/待機を即cancelし、実行中はcancel_requestedにする。心拍がそれを検知して既存Cancellationへ伝え、工程futureとRAII資源を解放する。cancel要求と成功が競合した場合はcancelを優先し、旧leaseからの結果・cache公開を拒否する。

## 外部結果が不明な場合

各nodeは`RetrySafety::Repeatable`または`Reconcile`を必須指定する。有料要求・投稿など、途中まで成功した可能性がある工程にはReconcileを指定する。実装は結果が不明な失敗を`StepFailure::ExternalUnknown`として返す。確定失敗と分け、成功済みか分からない要求を単純な再試行へ落とさない。

Reconcile工程のrunning checkpointを回復した場合、またはその工程のtimeoutでは、再送せず`external_unknown`へ待機し`E-JOB-UNCERTAIN`を保持する。通常のresumeは拒否する。外部側で未送信を確認した利用者だけが`confirm_job_step_not_sent(..., confirmed=true, operator, at)`を呼べる。この操作は対象工程とjobを原子的にqueueへ戻し、`audit_log`へ操作者・対象を記録する。外部の課金保留・YouTube状態の照合をこのAPIだけで完了した扱いにしない。

再利用に適さない投稿等には`CachePolicy::Never`を指定する。別jobの同じ入力を成功済みcacheとして流用せず、operation_keyもjob/nodeを含める。同じjobの脱落復帰では安定したkeyを保つ。

## cacheと局所無効化

cache keyはchannel、工程名・版・ソースhash、正規化JSON入力、入力素材hash、モデル、実際に読む設定、依存工程の入力hashと出力hashから作る。依存に含めていない他の行の変更でキーを変えない。`Dag::invalidated(changed_nodes)`で変更nodeとその下流だけを求められる。

`CachePolicy::ContentAddressed`の成功結果だけを保存する。工程成功とcache公開はlease検証と同じ取引で行う。出力のSHA-256、channel、工程版、実装・入力・モデル・設定・素材の来歴を再読取で照合する。壊れたcacheを空として返したり、空結果で上書きしたりしない。複数jobが同じ内容を同時に生成した場合は、同じ出力に限り最初のcache来歴を保って再利用する。

`Store::observe_step_source`は最初に観測した工程名・版のソースhashをapp_settingsへ記録し、同じ版で変更を検知すると警告する。hash自体もcache keyへ含める。実際のソースからfingerprintを算出して登録する責任はbuild/登録側にあり、xtaskでGit差分からVERSION未更新を自動検出する接続は後続である。

plan・生成結果のDB保存と、ログへの出力を分ける。本文・設定JSON・秘密値・cache本文をログへ出さず、安定コードとchannel/jobだけを記録する。実ファイルを返すStepは共通CAS境界で検証済みhashを出力し、実行時・利用時の素材存在確認を所有する。ここでの偽工程の合格は素材ファイル全種の実受入を代替しない。

## 資源と未接続

`ResourceGate`はRAIIの`ResourcePermit`を返す。実行前にスリープ抑止済み、GPU工程ならGPU利用可能の両方を確認し、偽の既定成功実装を用意しない。permitは成功・失敗・timeout・cancel・lease喪失で解放する。`CoordinatedResources`はcoreの共有`GpuCoordinator`へ接続し、枠・空きVRAM・予約を確認したGpuPermitを保持する。GPU-BUSYだけをgpu_busy待機へ変換し、注入したretry_afterで再開時刻を設定する。読取不能や未対応を「空きあり」に降格しない。

スリープ抑止のOS APIは設計通りsrc-tauriが所有し、`SleepInhibitor`とchannel-boundの`SleepPermit`を実装して渡す。CPU工程でもactiveなsleep permitを要求し、別channelや抑止失敗なら工程を開始しない。CPU専用ホストはGPU構成を`None`として構築でき、機器UUIDやprobeを用意しない。GPU工程を要求した時に構成がなければ`E-PIPELINE-RESOURCE`で停止する。GPU使用を選んだ場合だけ、機器UUIDごとの同じ共有coordinatorと要件を`Some((coordinator, requirement))`で全pipelineへ注入する。

現時点の検証は明示した偽permitであり、実OSのスリープ抑止・実VRAM監視・実生成Step・全QA・投稿・画面/`--tick`起動口は未受入である。利用者の実DB・キー・モデルは使用していない。

## 限定検証

- `cargo test -p picocast-store jobs::tests --lib`：別connectionの同時取得、同名workerの再取得と旧owner拒否、心拍時刻逆行、固着の失敗上限、待機の失敗数非加算、cancel優先、期限切れ/別channelの書戻し拒否、enqueue rollback、同じ版のソース変更観測。
- `cargo test -p picocast-pipeline --test jobs`：脱落・再openからの再開、不明外部結果の再送禁止と監査付き確認、cache破損の停止、cache禁止工程、循環・版・素材hash拒否、他queueの保護、資源解放。
- `cargo test -p picocast-pipeline --test resources`：偽VRAM情報と明示偽sleep permitで、共有GPU枠の待機・再取得・解放、CPUでも同channelの抑止permitが必要なことを確認する。
- 20行分の偽音声工程＋timeline/render/QAの23工程に対し、1行変更後はその音声と下流3工程だけを再実行し、残り19工程を再利用する。これは再実行範囲の検証であり、実動画の処理時間が1/5以下になる速度受入とは区別する。
