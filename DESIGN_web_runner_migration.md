# 設計引き継ぎ: Web(薄) ＋ job-runner ＋ DB共有状態 への移行

> このドキュメントは別エージェント（Codex 等）が単独で実装に着手できるよう、背景・確定事項・現状コード・目標設計・タスク分解・リスクを自己完結で記述する。実装者はまず本書を通読すること。ルールの正本は [AGENTS.md](AGENTS.md)。

## 0. 目的（なぜやるか）

「重い生成処理の最中でも Web UI が固まらない」ようにする並列処理の強化。現状は安定優先で **ワーカーを直列実行（同時1本）** に絞っているため、並列性が弱い。これをプロセス分離（Apache ワーカー型）に作り替える。

## 1. 確定した前提（ユーザー言質・調査結果）

- **OS資源は原因ではない**：CPU/GPU/ディスクIO は余裕。資源飽和は除外してよい。
- **DBロックは主因ではない**：metadata.db は WAL（[core/metadata_db.py:65-67](core/metadata_db.py#L65)）。明示排他ロック（`BEGIN EXCLUSIVE`/`IMMEDIATE`/`LOCK TABLE`）はコード上ゼロ。よって **SELECT はブロックされない**。競合は writer 対 writer のみ（同時1 writer、busy_timeout=10s）で稀。
- **「並列が弱い」真因**：`JOB_MAX_CONCURRENT_WORKERS=1`（[config/config.py:461](config/config.py#L461)）で意図的に直列化しているから。元の「固まり」はパイプバッファのデッドロック（stderr を汲まないと子プロセスが詰まる）で、これは既に stderr ドレインスレッド（[web_app/worker_runner.py:187](web_app/worker_runner.py#L187)）で対策済み。
- **クラッシュ隔離は不要**：ユーザー方針「半端に処理を守る必要はない。ユーザーから見たらどっちもエラー」。生成を runner プロセス内で直接実行し、ハードクラッシュは runner ごと巻き込まれてもよい（その分エラーが分かりやすい）。
- **ファイルIPCは廃止**：`input.json` / `result.json`（[web_app/worker_runner.py:142-143](web_app/worker_runner.py#L142)）を使いたくない。run_pipeline は元々メモリ引数で受けられるので不要。
- **配布・販売前提**：Kafka/Redis/Docker 等の外部依存は禁止。純Python・SQLite・標準ライブラリで実装。起動コマンドは従来どおり1つに保つ。
- **ログ詰まり懸念（Windows）**：`TimedRotatingFileHandler`（[core/debug_logging.py:32](core/debug_logging.py#L32)）は深夜ローテーション時の `os.rename` が、他プロセスがファイルを開いていると Windows で `PermissionError`（WinError 32）になる。**現状は app_debug.log の書き手が Web プロセス1つ**（ワーカー subprocess は `setup_debug_logging` を呼ばず stdout 経由）なので今は衝突していないが、**多プロセス化すると新たに衝突が発生する**ため、ロギングを log4j 的に作り替える必要がある。

## 2. 現状アーキテクチャ（移行前）

```
[uvicorn 単一プロセス]
  ├ FastAPI ルート（同期エンドポイントは anyio threadpool）
  ├ JobManager（in-memory dict ＋ ThreadPoolExecutor(max_workers=4)）
  │    submit(job, fn=run_in_worker, "worker_pipeline.py", params)
  └ run_in_worker（job実行スレッド内）
       ├ tempdir に input.json 書き出し
       ├ subprocess.Popen([python, worker_pipeline.py, --input, --result], stdin/stdout/stderr=PIPE)
       ├ stdout を1行ずつ json.loads → _log(job)（in-memory job.logs ＋ app_debug.log ミラー）
       ├ stderr ドレインスレッド
       ├ cancel は stdin に "cancel\n" を書く
       └ 終了後 result.json を読む
```

主要事実:
- JobManager: [web_app/job_manager.py:82](web_app/job_manager.py#L82)。`_jobs` は in-memory。DB へは **ジョブ確定時のみ** `upsert_job`（[job_manager.py:116](web_app/job_manager.py#L116)）。起動時 `_load_jobs` で復元し、RUNNING/QUEUED は「再起動により中断」で FAILED 化（[job_manager.py:94](web_app/job_manager.py#L94)）。
- jobs テーブル: [core/metadata_db.py:300](core/metadata_db.py#L300)。カラム = `job_id, job_type, status, progress_text, started_at, finished_at, logs_json, result_json, error, created_at`。`upsert_job`=[:1283](core/metadata_db.py#L1283), `load_jobs_from_db`=[:1314](core/metadata_db.py#L1314)。
- 直列化: `_worker_slots = BoundedSemaphore(JOB_MAX_CONCURRENT_WORKERS)`（[web_app/worker_runner.py:33](web_app/worker_runner.py#L33)）。
- 生成本体: `workers.main.run_pipeline(topic, pregenerated_script, image_style, background_engine, reuse_backgrounds, reuse_audio, cancel_event, progress_callback, long_thumbnail_ab_test, long_budget_mode, sd_size_mode, bgm_mode, bgm_id, bgm_volume_db)`（[workers/main.py:723](workers/main.py#L723)）。戻り値 `(msg, report)`。`report.theme_dir`, `report.elapsed_sec` を使用。`cancel_event`（threading.Event）と `progress_callback(msg, tag="info")` を**既に受け取れる**。
- レンダーワーカーの引数対応は [workers/worker_render.py:41](workers/worker_render.py#L41) の main() を参照（同様の薄いラッパ）。
- Web 投入経路: `web_app/services/generate_service.py` の `submit_generate_job` / `submit_batch_generate_jobs`（[web_app/routes/api_generate.py:4](web_app/routes/api_generate.py#L4) から使用）。
- UI 読み取り: [web_app/routes/api_jobs.py](web_app/routes/api_jobs.py) が `get_job_manager().list_jobs()/get_job()/cancel_job()` を呼ぶ。
- 起動: `web_app/app.py` `main()`=[:161](web_app/app.py#L161)、通常起動は `uvicorn.Server(uv_config)` を `asyncio.run(server.serve())`（[:245-254](web_app/app.py#L245)）。`--reload` 時は `uvicorn.run()`。

## 3. 目標アーキテクチャ（移行後）

```
[uvicorn Web（薄い）]                         [job-runner（常駐プロセス）]
  submit  -> INSERT jobs(status=queued,         ループ:
            params_json)                          reap_stale_running_jobs()
  list    -> SELECT jobs                          claim_queued_job() を JOB_MAX_CONCURRENT_WORKERS 本まで
  detail  -> SELECT jobs                          各ジョブ(スレッド):
  cancel  -> UPDATE cancel_requested=1              cancel監視ウォッチャ(DB polling -> Event.set)
                      |                             heartbeat 更新
              [metadata.db jobs]  <----------       progress_callback -> append_job_logs(バッファ)
              (WAL・共有状態)                         run_pipeline(...) / レンダーを「直接呼ぶ」
                                                     例外はそのまま status=failed で記録
```

- Web は計算しない・subprocess を起動しない・ファイルを書かない。状態は全て DB。
- runner が `run_pipeline` を **同一プロセス内で直接呼ぶ**（subprocess/ファイル/stdin/stdout の IPC を全廃）。
- ffmpeg は run_pipeline 内で別プロセスとして起動されるため、runner 終了時は ffmpeg 子プロセスをツリーごと kill する（既存 `_kill_tree` 相当を runner にも持たせる）。

## 4. タスク分解（一括実装）

### 4.1 DB スキーマ拡張（core/metadata_db.py）
jobs テーブルに追加（既存の ALTER ガードパターン＝`PRAGMA table_info` で存在チェックして追加する方式に合わせる）:
- `params_json TEXT`（生成パラメータ。input.json 置換）
- `cancel_requested INTEGER DEFAULT 0`（キャンセル指令。stdin "cancel" 置換）
- `heartbeat_at TEXT`（runner 生存時刻。ISO8601 JST）
- `runner_pid INTEGER`（担当 runner PID）

追加関数:
- `claim_queued_job(runner_pid) -> dict | None`：`BEGIN IMMEDIATE` で原子的に「最古の queued を1件 → running に更新（runner_pid, started_at, heartbeat_at セット）」し、その行を返す。二重 claim 防止が要件。
- `append_job_logs(job_id, entries: list[dict])`：logs_json に追記（読み→結合→書き戻し、または JSON 配列マージ）。**呼び出し側でバッファして ~0.5s 毎にまとめて呼ぶ**（WAL 単一 writer 負荷軽減）。
- `update_job_progress(job_id, progress_text, heartbeat_at)`。
- `set_job_result(job_id, status, result_json, error, finished_at)`。
- `request_cancel(job_id)` / `is_cancel_requested(job_id) -> bool`。
- `reap_stale_running_jobs(timeout_sec)`：heartbeat が timeout 超過の running を `failed`（error="runner停止により中断"）へ。`config` に `JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC`（既定30）を追加（ハードコード禁止）。

`config/config.py` に追加（[[feedback_config_no_hardcode]]）:
- `JOB_RUNNER_POLL_INTERVAL_SEC`（既定0.5）
- `JOB_RUNNER_HEARTBEAT_INTERVAL_SEC`（既定2.0）
- `JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC`（既定30.0）
- `JOB_LOG_FLUSH_INTERVAL_SEC`（既定0.5）

### 4.2 Web 側を薄くする
- `web_app/job_manager.py`：ThreadPoolExecutor・`submit` 実行・atexit を撤去。`create_job` は queued INSERT（params_json 込み）、`list_jobs`/`get_job` は DB SELECT、`cancel_job` は `request_cancel`。`_load_jobs` の「再起動で中断」処理は不要（runner が reap する）。`_log` は Web では使わない（ログは DB から取得）。
- `web_app/services/generate_service.py`：`submit_generate_job` / `submit_batch_generate_jobs` は params を組んで queued INSERT し job_id を返すだけにする。`run_in_worker` 参照を除去。
- `web_app/routes/api_jobs.py`：インターフェース不変（job_manager 経由のまま）。
- **削除**：`web_app/worker_runner.py`、`workers/worker_pipeline.py`、`workers/worker_render.py`。

### 4.3 job-runner 新規（workers/runner.py）
- `python -m workers.runner` で起動する常駐プロセス。`main()`:
  - 起動時に自プロセス用ロギング設定（4.5）。
  - ループ（`JOB_RUNNER_POLL_INTERVAL_SEC` 毎）: `reap_stale_running_jobs()` → 空きスロットぶん `claim_queued_job()` → ThreadPoolExecutor(`JOB_MAX_CONCURRENT_WORKERS`) に投入。
  - 各ジョブスレッド `_run_job(job_row)`:
    - `cancel_event = threading.Event()`。サブスレッドで `is_cancel_requested` を `JOB_RUNNER_POLL_INTERVAL_SEC` 毎に監視し set。同スレッドで `heartbeat_at` を `JOB_RUNNER_HEARTBEAT_INTERVAL_SEC` 毎に更新。
    - `progress_callback(msg, tag)`: ログをバッファに積み、`JOB_LOG_FLUSH_INTERVAL_SEC` 毎に `append_job_logs` ＋ `update_job_progress`。
    - `job_type` で分岐し `run_pipeline(...)`（[workers/main.py:723](workers/main.py#L723)）または旧 worker_render.py 相当のレンダー処理を直接呼ぶ。引数は params_json から復元（旧ラッパ [workers/worker_pipeline.py:63-78](workers/worker_pipeline.py#L63) のマッピングを移植）。
    - 終了判定（旧ラッパ [workers/worker_pipeline.py:80-95](workers/worker_pipeline.py#L80) 準拠）: cancel_event set→cancelled / msg が `❌` 始まり→failed / それ以外→success。`set_job_result` で確定。
    - 例外は握りつぶさず（[[feedback_no_silent_fallback]]）traceback をログに残し status=failed。
  - シャットダウン（SIGTERM/Ctrl+C）: 実行中ジョブの cancel_event を set、ffmpeg を含む子プロセスをツリー kill（`_kill_tree` を [web_app/worker_runner.py](web_app/worker_runner.py) から移植）。

### 4.4 起動・監視（web_app/app.py main()）
- uvicorn 起動前に runner を `subprocess.Popen([sys.executable, "-m", "workers.runner"], cwd=<repo root>, env=...)` で起動。
- スーパーバイザ用 daemon スレッドで runner を監視し、異常終了したら再起動（再起動後 reap で中断ジョブが failed 化される）。
- Web 終了時（lifespan shutdown / 既存 [core/app_shutdown.py](core/app_shutdown.py) の停止フックに合わせる）に runner を terminate→（猶予後）kill。
- **起動コマンドは従来どおり1つ**（`python web_app/app.py`）に保つ。`--reload` 開発モードでも runner を起動するか、起動しない旨をドキュメント明記。

### 4.5 ロギング刷新（core/debug_logging.py）— log4j 的
- 各プロセスで **`QueueHandler`（root に付与）→ `QueueListener`（専用スレッド）** 構成にする。アプリスレッドはキューに積むだけ＝ファイルI/O・ローテーションでブロックしない。`QueueListener` だけが実ハンドラ（`TimedRotatingFileHandler`）へ書く。`atexit` で listener.stop()。
- **プロセス別ファイル**：`setup_debug_logging(role: str)` を追加し、`app_debug_{role}.log`（例 `app_debug_web.log` / `app_debug_runner.log`）に分ける。1ファイル＝1書き手にして Windows の rename 衝突を構造的に排除。
- 既存の `_SecretRedactingFilter`・noisy ロガー抑制・`cleanup_old_debug_logs` は流用。フォーマットの `[%(process)d]` は維持。
- ログ閲覧（[web_app/services/debug_log_service.py](web_app/services/debug_log_service.py)）は対象ファイル名の変更に追従。UI のジョブログは DB の logs_json を正とする。

### 4.6 テスト・ドキュメント
- `tests/test_web.py`：直列化テスト（[:796](tests/test_web.py#L796)）等、subprocess 前提のテストを DB ベースに更新。
- runner 単体テスト追加：`claim_queued_job` の原子性（並行 claim で二重取得しない）／cancel フラグ→Event 反映／`reap_stale_running_jobs`／progress バッファ flush。
- ロギング：QueueListener 経由で書かれること、role 別ファイルになることのテスト。
- ドキュメント更新（[[feedback_docs_always_update]]）：[AGENTS.md](AGENTS.md)・[SPEC.md](SPEC.md) に新アーキ（web/runner/DB の責務分担・起動・ロギング設計・キャンセル/reap 仕様）を反映。[CHANGELOG.md](CHANGELOG.md) に追記。

## 5. リスク・仕様判断

- **ポーリング遅延**：claim/cancel/進捗が `JOB_RUNNER_POLL_INTERVAL_SEC`(~0.5s) 周期 → UI 反映に最大 ~0.5s 遅延。ローカル用途で許容。
- **WAL 単一 writer**：runner の進捗書込が直列化する。ログは必ずバッファして flush 回数を抑える。
- **ffmpeg 孤児**：runner がハードキルされると ffmpeg 子が孤児化しうる。通常終了時はツリー kill。異常時は reap でジョブ failed 化（孤児プロセスの掃除は OS 再起動 or 既存の掃除機構に委譲。必要なら runner 起動時に古い yj 系プロセスを掃除する処理を検討）。
- **クラッシュで runner ごと死ぬ**：許容（ユーザー方針）。reap によりジョブは `failed` として可視化、スーパーバイザが runner 再起動。
- **migration 互換**：既存 jobs 行（新カラム無し）は ALTER で DEFAULT 補完。古い RUNNING 行は初回 reap で failed 化。

## 6. 受け入れ確認（完了条件）

1. `python web_app/app.py` 一発で Web ＋ runner が起動し、生成・レンダーが動く。
2. `JOB_MAX_CONCURRENT_WORKERS` を 2 以上にすると実際に並列実行され、その最中も Web UI（一覧/詳細/他ページ）が固まらない。
3. UI からのキャンセルが効く（DB フラグ→Event→run_pipeline 停止→ffmpeg も停止）。
4. runner を強制終了しても、中断ジョブが ~30s 以内に `failed` 表示になり、runner が自動再起動する。
5. `input.json`/`result.json`/`worker_pipeline.py`/`worker_render.py`/`worker_runner.py` が存在しない（ファイルIPC全廃）。
6. ログが `app_debug_web.log` / `app_debug_runner.log` に分かれ、深夜ローテーションが Windows で失敗しない（QueueListener 単一書き手）。
7. `python -m pytest -q` 全 pass。
8. AGENTS.md / SPEC.md / CHANGELOG.md 更新済み。

## 7. 実装順序の目安（一括でも内部はこの順が安全）

1. config 定数追加 → 2. DB スキーマ＋関数 → 3. ロギング刷新（QueueHandler/role別） → 4. runner 新規 → 5. Web 薄化＋submit 変更 → 6. app.py で runner 起動・監視 → 7. 旧 IPC ファイル群削除 → 8. テスト更新 → 9. ドキュメント更新。
