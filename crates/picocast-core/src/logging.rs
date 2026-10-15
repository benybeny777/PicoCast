use crate::{
    clock, fsutil,
    settings::{Constraint, Definition, Registry, Value},
    AppError, Result,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value as Json};
use std::{
    collections::BTreeMap,
    fmt,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};
use tracing::{
    field::{Field, Visit},
    span::{Attributes, Id, Record},
    Event, Subscriber,
};
use tracing_subscriber::{
    layer::{Context, SubscriberExt},
    registry::LookupSpan,
    Layer,
};

/// 調整値の正本。合計容量をアプリとtickの2役割へ均等配分する。
pub fn setting_definitions() -> BTreeMap<String, Definition> {
    BTreeMap::from([
        (
            "log_retention_days".into(),
            Definition {
                default: Value::Integer(30),
                constraint: Constraint::Integer { min: 1, max: 3650 },
            },
        ),
        (
            "log_max_bytes".into(),
            Definition {
                default: Value::Integer(268_435_456),
                constraint: Constraint::Integer {
                    min: 8192,
                    max: i64::MAX,
                },
            },
        ),
        (
            "job_log_compress_days".into(),
            Definition {
                default: Value::Integer(90),
                constraint: Constraint::Integer { min: 1, max: 3650 },
            },
        ),
    ])
}

/// 呼出元も秘密値をログに渡さない。登録とフィールド判定は追加の防御。
#[derive(Clone, Default)]
pub struct SecretRedactor(Arc<Mutex<Vec<String>>>);
impl SecretRedactor {
    pub fn register(&self, secret: &str) -> Result<()> {
        if !secret.is_empty() {
            let mut values = self.0.lock().map_err(|_| failure(Failure::Lock))?;
            if !values.iter().any(|value| value == secret) {
                values.push(secret.to_owned());
                values.sort_by_key(|value| std::cmp::Reverse(value.len()));
            }
        }
        Ok(())
    }
    fn clean(&self, name: &str, value: &str) -> Result<String> {
        let name = name.to_ascii_lowercase();
        if [
            "secret",
            "token",
            "password",
            "authorization",
            "api_key",
            "master_key",
            "credential",
        ]
        .iter()
        .any(|part| name.contains(part))
        {
            return Ok("[REDACTED]".into());
        }
        let values = self.0.lock().map_err(|_| failure(Failure::Lock))?;
        let mut clean = value.to_owned();
        for secret in values.iter() {
            clean = clean.replace(secret, "[REDACTED]");
        }
        Ok(clean)
    }
}

#[derive(Debug, Clone, Copy)]
pub enum Role {
    App,
    Tick,
}
impl Role {
    fn name(self) -> &'static str {
        match self {
            Self::App => "app",
            Self::Tick => "tick",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CrashNotice {
    pub code: String,
    pub at: String,
    pub role: String,
    pub message: String,
    pub fix: String,
}
impl CrashNotice {
    fn new(role: Role) -> Self {
        Self {
            code: "E-LOG-CRASH".into(),
            at: clock::now_utc_iso(),
            role: role.name().into(),
            message: "前回の処理が正常に終了しませんでした".into(),
            fix: "ジョブとデバッグログを確認してから再開してください。自動再送は行いません".into(),
        }
    }
}

struct State {
    session: std::fs::File,
    failure: Option<AppError>,
    closed: bool,
}
struct Inner {
    root: PathBuf,
    role: Role,
    settings: Arc<Registry>,
    redactor: SecretRedactor,
    state: Mutex<State>,
}

/// 同じ役割はOSファイルロックで排他する。UIとtickのログは別ディレクトリ。
#[derive(Clone)]
pub struct Logging(Arc<Inner>);
impl Logging {
    pub fn open(
        data_root: &Path,
        role: Role,
        settings: Arc<Registry>,
        redactor: SecretRedactor,
    ) -> Result<Self> {
        if !data_root.is_absolute() {
            return Err(failure(Failure::Config));
        }
        read_policy(&settings)?;
        let root = data_root.join("logs").join(role.name());
        std::fs::create_dir_all(&root).map_err(|_| failure(Failure::Io))?;
        let mut session = fsutil::lock_log_session(&root.join("session.json"))
            .map_err(|_| failure(Failure::Init))?;
        let previous = fsutil::read_log_session(&mut session).map_err(|_| failure(Failure::Io))?;
        if !previous.is_empty() {
            let _: CrashNotice =
                serde_json::from_slice(&previous).map_err(|_| failure(Failure::Io))?;
            if !root.join("crash.json").exists() {
                let notice = serde_json::to_vec(&CrashNotice::new(role))
                    .map_err(|_| failure(Failure::Io))?;
                fsutil::atomic_write(&root.join("crash.json"), &notice)?;
            }
        }
        let marker =
            serde_json::to_vec(&CrashNotice::new(role)).map_err(|_| failure(Failure::Io))?;
        fsutil::write_log_session(&mut session, &marker).map_err(|_| failure(Failure::Io))?;
        let logging = Self(Arc::new(Inner {
            root,
            role,
            settings,
            redactor,
            state: Mutex::new(State {
                session,
                failure: None,
                closed: false,
            }),
        }));
        logging.maintain_at(&clock::now_utc_iso())?;
        Ok(logging)
    }
    pub fn dispatch(&self) -> tracing::Dispatch {
        tracing::Dispatch::new(tracing_subscriber::registry().with(LogLayer(self.clone())))
    }

    /// 起動時に1度だけ呼ぶ。秘密値を含み得るパニック本文は保存しない。
    pub fn install_global(&self) -> Result<()> {
        tracing::dispatcher::set_global_default(self.dispatch())
            .map_err(|_| failure(Failure::Init))?;
        let logger = self.clone();
        std::panic::set_hook(Box::new(move |_| {
            let result = logger.record_crash();
            tracing::error!(code = "E-LOG-CRASH", backtrace = %std::backtrace::Backtrace::force_capture(), "処理中にパニックが発生");
            if let Err(error) = result {
                logger.remember_failure(error);
            }
        }));
        Ok(())
    }

    /// 各ジョブ境界・アプリ終了で確認し、sinkの失敗を成功扱いにしない。
    pub fn check_health(&self) -> Result<()> {
        let state = self.0.state.lock().map_err(|_| failure(Failure::Lock))?;
        match &state.failure {
            Some(error) => Err(error.clone()),
            None => Ok(()),
        }
    }
    pub fn pending_crash(&self) -> Result<Option<CrashNotice>> {
        match std::fs::read(self.0.root.join("crash.json")) {
            Ok(bytes) => serde_json::from_slice(&bytes)
                .map(Some)
                .map_err(|_| failure(Failure::Io)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(_) => Err(failure(Failure::Io)),
        }
    }
    /// 画面が通知を表示し、利用者が確認した後にだけ呼ぶ。
    pub fn acknowledge_crash(&self) -> Result<()> {
        match std::fs::remove_file(self.0.root.join("crash.json")) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err(failure(Failure::Io)),
        }
    }
    /// 正常終了だけマーカーを空にする。Dropや強制終了では消さない。
    pub fn shutdown(&self) -> Result<()> {
        self.check_health()?;
        let mut state = self.0.state.lock().map_err(|_| failure(Failure::Lock))?;
        fsutil::write_log_session(&mut state.session, &[]).map_err(|_| failure(Failure::Io))?;
        state.closed = true;
        Ok(())
    }
    pub fn record_crash(&self) -> Result<()> {
        let bytes =
            serde_json::to_vec(&CrashNotice::new(self.0.role)).map_err(|_| failure(Failure::Io))?;
        fsutil::atomic_write(&self.0.root.join("crash.json"), &bytes)
    }
    fn remember_failure(&self, error: AppError) {
        if let Ok(mut state) = self.0.state.try_lock() {
            if state.failure.is_none() {
                state.failure = Some(error);
            }
        }
        // ロック破損時もcheck_healthが失敗する。失敗したsinkへ再入しない。
    }
    fn write_event(&self, event: Json) -> Result<()> {
        self.check_health()?;
        let mut bytes = serde_json::to_vec(&event).map_err(|_| failure(Failure::Io))?;
        bytes.push(b'\n');
        let now = clock::now_utc_iso();
        let (_, maximum, _) = read_policy(&self.0.settings)?;
        if bytes.len() as u128 > maximum as u128 {
            return Err(failure(Failure::Config));
        }
        let state = self.0.state.lock().map_err(|_| failure(Failure::Lock))?;
        if state.closed {
            return Err(failure(Failure::Init));
        }
        let prefix = format!("app-{}-", &now[..10]);
        let mut sequence = 0u64;
        for entry in std::fs::read_dir(&self.0.root).map_err(|_| failure(Failure::Io))? {
            let entry = entry.map_err(|_| failure(Failure::Io))?;
            let name = entry.file_name().to_string_lossy().into_owned();
            if let Some(index) = name
                .strip_prefix(&prefix)
                .and_then(|v| v.strip_suffix(".jsonl"))
                .and_then(|v| v.parse::<u64>().ok())
            {
                sequence = sequence.max(index);
            }
        }
        let mut path = self.0.root.join(format!("{prefix}{sequence:010}.jsonl"));
        let length = match std::fs::symlink_metadata(&path) {
            Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => {
                metadata.len()
            }
            Ok(_) => return Err(failure(Failure::Io)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => 0,
            Err(_) => return Err(failure(Failure::Io)),
        };
        if u128::from(length) + bytes.len() as u128 > maximum as u128 {
            sequence = sequence
                .checked_add(1)
                .ok_or_else(|| failure(Failure::Config))?;
            path = self.0.root.join(format!("{prefix}{sequence:010}.jsonl"));
        }
        fsutil::append_log(&path, &bytes).map_err(|_| failure(Failure::Io))?;
        self.prune(&now)
    }

    /// 完了ログはjob-完了日-識別子.jsonl。未完了ログにはこの名前を付けない。
    pub fn maintain_at(&self, now: &str) -> Result<()> {
        let _state = self.0.state.lock().map_err(|_| failure(Failure::Lock))?;
        self.prune(now)
    }
    fn prune(&self, now: &str) -> Result<()> {
        let (days, maximum, compress_days) = read_policy(&self.0.settings)?;
        let now = clock::Timestamp::parse(now)?;
        let mut managed = Vec::new();
        for entry in std::fs::read_dir(&self.0.root).map_err(|_| failure(Failure::Io))? {
            let entry = entry.map_err(|_| failure(Failure::Io))?;
            let name = entry.file_name().to_string_lossy().into_owned();
            let Some((date, job)) = managed_log_date(&name) else {
                continue;
            };
            let ty = entry.file_type().map_err(|_| failure(Failure::Io))?;
            if !ty.is_file() || ty.is_symlink() {
                return Err(failure(Failure::Io));
            }
            let stamp = clock::Timestamp::parse(&format!("{date}T00:00:00Z"))?;
            let age = now
                .as_utc()
                .signed_duration_since(*stamp.as_utc())
                .num_days();
            let path = entry.path();
            if !job && age >= days {
                std::fs::remove_file(path).map_err(|_| failure(Failure::Io))?;
                continue;
            }
            let path = if job && age >= compress_days && name.ends_with(".jsonl") {
                let destination = path.with_extension("jsonl.gz");
                fsutil::compress_log(&path, &destination).map_err(|_| failure(Failure::Io))?;
                destination
            } else {
                path
            };
            let size = std::fs::metadata(&path)
                .map_err(|_| failure(Failure::Io))?
                .len();
            managed.push((date.to_owned(), path, size));
        }
        managed.sort_by(|a, b| (&a.0, &a.1).cmp(&(&b.0, &b.1)));
        let mut total: u128 = managed.iter().map(|item| u128::from(item.2)).sum();
        for (_, path, size) in managed {
            if total <= maximum as u128 {
                break;
            }
            std::fs::remove_file(path).map_err(|_| failure(Failure::Io))?;
            total -= u128::from(size);
        }
        Ok(())
    }
}

fn read_policy(settings: &Registry) -> Result<(i64, i64, i64)> {
    let days = settings.integer("log_retention_days")?;
    let maximum = settings.integer("log_max_bytes")?;
    let compress = settings.integer("job_log_compress_days")?;
    if days < 1 || maximum < 8192 || compress < 1 {
        return Err(failure(Failure::Config));
    }
    Ok((days, maximum / 2, compress))
}
fn managed_log_date(name: &str) -> Option<(&str, bool)> {
    let (rest, job) = if let Some(rest) = name.strip_prefix("app-") {
        (rest.strip_suffix(".jsonl")?, false)
    } else {
        (name.strip_prefix("job-")?, true)
    };
    let date = rest.get(..10)?;
    if !date.bytes().enumerate().all(|(index, byte)| {
        if index == 4 || index == 7 {
            byte == b'-'
        } else {
            byte.is_ascii_digit()
        }
    }) {
        return None;
    }
    if rest.as_bytes().get(10) != Some(&b'-') {
        return None;
    }
    let suffix = rest.get(11..)?;
    let id = if job {
        suffix
            .strip_suffix(".jsonl.gz")
            .or_else(|| suffix.strip_suffix(".jsonl"))?
    } else {
        suffix
    };
    if id.is_empty()
        || !id.bytes().all(|b| {
            if job {
                b.is_ascii_alphanumeric() || b == b'-'
            } else {
                b.is_ascii_digit()
            }
        })
    {
        return None;
    }
    Some((date, job))
}

#[derive(Clone, Default)]
struct Fields(Map<String, Json>);
impl Visit for Fields {
    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        self.0
            .insert(field.name().into(), Json::String(format!("{value:?}")));
    }
    fn record_str(&mut self, field: &Field, value: &str) {
        self.0
            .insert(field.name().into(), Json::String(value.into()));
    }
    fn record_i64(&mut self, field: &Field, value: i64) {
        self.0.insert(field.name().into(), value.into());
    }
    fn record_u64(&mut self, field: &Field, value: u64) {
        self.0.insert(field.name().into(), value.into());
    }
    fn record_bool(&mut self, field: &Field, value: bool) {
        self.0.insert(field.name().into(), value.into());
    }
}
#[derive(Clone)]
struct LogLayer(Logging);
thread_local! {
    // 失敗したログ内部処理からtracingが呼ばれても同じsinkへ再入しない。
    static IN_LOG_EVENT: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}
struct EventGuard;
impl Drop for EventGuard {
    fn drop(&mut self) {
        IN_LOG_EVENT.with(|active| active.set(false));
    }
}
impl<S: Subscriber + for<'a> LookupSpan<'a>> Layer<S> for LogLayer {
    fn on_new_span(&self, attrs: &Attributes<'_>, id: &Id, context: Context<'_, S>) {
        if let Some(span) = context.span(id) {
            let mut fields = Fields::default();
            attrs.record(&mut fields);
            span.extensions_mut().insert(fields);
        }
    }
    fn on_record(&self, id: &Id, values: &Record<'_>, context: Context<'_, S>) {
        if let Some(span) = context.span(id) {
            if let Some(fields) = span.extensions_mut().get_mut::<Fields>() {
                values.record(fields);
            }
        }
    }
    fn on_event(&self, event: &Event<'_>, context: Context<'_, S>) {
        if IN_LOG_EVENT.with(|active| active.replace(true)) {
            self.0.remember_failure(failure(Failure::Lock));
            return;
        }
        let _event_guard = EventGuard;
        let result = (|| -> Result<()> {
            let mut fields = Fields::default();
            if let Some(scope) = context.event_scope(event) {
                for span in scope.from_root() {
                    if let Some(parent) = span.extensions().get::<Fields>() {
                        fields.0.extend(parent.0.clone());
                    }
                }
            }
            event.record(&mut fields);
            for (key, value) in &mut fields.0 {
                let original = match &*value {
                    Json::String(text) => text.clone(),
                    other => other.to_string(),
                };
                let clean = self.0 .0.redactor.clean(key, &original)?;
                if clean != original {
                    *value = Json::String(clean);
                }
            }
            self.0.write_event(json!({"at":clock::now_utc_iso(), "role":self.0.0.role.name(), "level":event.metadata().level().as_str(), "target":event.metadata().target(), "fields":fields.0}))
        })();
        if let Err(error) = result {
            self.0.remember_failure(error);
        }
    }
}
enum Failure {
    Config,
    Io,
    Lock,
    Init,
}
fn failure(kind: Failure) -> AppError {
    let (code, message, fix) = match kind {
        Failure::Config => (
            "E-LOG-CONFIG",
            "ログ設定が不正です",
            "保存日数・容量上限・圧縮開始日数を設定の範囲内にしてください",
        ),
        Failure::Lock => (
            "E-LOG-LOCK",
            "ログの共有状態が破損しました",
            "デバッグログを保護してアプリを再起動してください",
        ),
        Failure::Init => (
            "E-LOG-INIT",
            "ログを初期化できません",
            "同じ役割のプロセスを重複起動していないか確認してください",
        ),
        Failure::Io => (
            "E-LOG-IO",
            "ログを読み書きできません",
            "保存先の空き容量・権限と既存のログファイルを確認してください",
        ),
    };
    AppError::new(code, message, fix)
}

pub fn operation_span(channel_id: &crate::ChannelId, job_id: &str) -> tracing::Span {
    step_span(channel_id, job_id, "operation")
}
pub fn step_span(channel_id: &crate::ChannelId, job_id: &str, step: &str) -> tracing::Span {
    tracing::info_span!("operation", channel_id = channel_id.as_str(), job_id, step)
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::disallowed_types,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    fn logger(dir: &Path) -> Logging {
        Logging::open(
            dir,
            Role::App,
            Arc::new(Registry::new(setting_definitions()).unwrap()),
            SecretRedactor::default(),
        )
        .unwrap()
    }
    fn today_file(log: &Logging) -> PathBuf {
        log.0.root.join(format!(
            "app-{}-0000000000.jsonl",
            &clock::now_utc_iso()[..10]
        ))
    }

    #[test]
    fn context_and_secret_redaction() {
        let dir = tempfile::tempdir().unwrap();
        let log = logger(dir.path());
        log.0.redactor.register("sensitive-test-value").unwrap();
        tracing::dispatcher::with_default(&log.dispatch(), || {
            let channel = crate::ChannelId::new("channel-1").unwrap();
            let _span = step_span(&channel, "job-2", "voice").entered();
            tracing::warn!(
                api_key = "never-visible",
                "request sensitive-test-value failed"
            );
        });
        log.check_health().unwrap();
        let text = std::fs::read_to_string(today_file(&log)).unwrap();
        assert!(!text.contains("sensitive-test-value"));
        assert!(!text.contains("never-visible"));
        let row: Json = serde_json::from_str(text.trim()).unwrap();
        assert_eq!(row["fields"]["channel_id"], "channel-1");
        assert_eq!(row["fields"]["job_id"], "job-2");
        assert_eq!(row["fields"]["step"], "voice");
        assert_eq!(row["fields"]["api_key"], "[REDACTED]");
        log.shutdown().unwrap();
    }
    #[test]
    fn unclean_shutdown_notice_is_preserved_until_acknowledged() {
        let dir = tempfile::tempdir().unwrap();
        {
            let log = logger(dir.path());
            assert!(log.pending_crash().unwrap().is_none());
        }
        let log = logger(dir.path());
        assert_eq!(log.pending_crash().unwrap().unwrap().code, "E-LOG-CRASH");
        log.acknowledge_crash().unwrap();
        assert!(log.pending_crash().unwrap().is_none());
        log.shutdown().unwrap();
        drop(log);
        assert!(logger(dir.path()).pending_crash().unwrap().is_none());
    }
    #[test]
    fn panic_is_recorded_in_separate_process() {
        if let Some(directory) = crate::settings::test_environment_value("PICOCAST_PANIC_TEST_DIR")
        {
            let log = logger(Path::new(&directory));
            log.install_global().unwrap();
            assert!(std::panic::catch_unwind(|| panic!("PANIC_SECRET_NOT_FOR_LOGS")).is_err());
            assert!(log.pending_crash().unwrap().is_some());
            return;
        }
        let dir = tempfile::tempdir().unwrap();
        let runtime = tokio::runtime::Runtime::new().unwrap();
        let output = runtime
            .block_on(crate::proc::run_with_environment(
                &std::env::current_exe().unwrap(),
                &[
                    "logging::tests::panic_is_recorded_in_separate_process".into(),
                    "--exact".into(),
                ],
                crate::proc::RunOptions {
                    timeout: std::time::Duration::from_secs(30),
                    max_output_bytes: 65536,
                },
                &[(
                    "PICOCAST_PANIC_TEST_DIR".into(),
                    dir.path().as_os_str().to_owned(),
                )],
            ))
            .unwrap();
        assert!(output.status.success());
        let notice = std::fs::read_to_string(dir.path().join("logs/app/crash.json")).unwrap();
        assert!(!notice.contains("PANIC_SECRET"));
        assert!(logger(dir.path()).pending_crash().unwrap().is_some());
    }
    #[test]
    fn retention_capacity_and_completed_job_compression() {
        let dir = tempfile::tempdir().unwrap();
        let log = logger(dir.path());
        let root = &log.0.root;
        fsutil::atomic_write(&root.join("app-2025-01-01-0000000000.jsonl"), b"old").unwrap();
        fsutil::atomic_write(&root.join("job-2025-01-01-done.jsonl"), b"completed job\n").unwrap();
        fsutil::atomic_write(&root.join("user-file.txt"), b"keep").unwrap();
        log.maintain_at("2026-10-16T00:00:00Z").unwrap();
        assert!(!root.join("app-2025-01-01-0000000000.jsonl").exists());
        assert!(!root.join("job-2025-01-01-done.jsonl").exists());
        let mut decode = flate2::read::GzDecoder::new(
            std::fs::File::open(root.join("job-2025-01-01-done.jsonl.gz")).unwrap(),
        );
        let mut restored = String::new();
        std::io::Read::read_to_string(&mut decode, &mut restored).unwrap();
        assert_eq!(restored, "completed job\n");
        assert_eq!(std::fs::read(root.join("user-file.txt")).unwrap(), b"keep");
        log.0
            .settings
            .set("log_max_bytes", Value::Integer(8192))
            .unwrap();
        fsutil::atomic_write(
            &root.join("app-2026-10-15-0000000000.jsonl"),
            &vec![b'x'; 5000],
        )
        .unwrap();
        fsutil::atomic_write(&root.join("app-2026-10-16-0000000000.jsonl"), b"new").unwrap();
        log.maintain_at("2026-10-16T00:00:00Z").unwrap();
        assert!(!root.join("app-2026-10-15-0000000000.jsonl").exists());
        assert!(root.join("app-2026-10-16-0000000000.jsonl").exists());
    }
    #[test]
    fn duplicate_initialization_and_sink_failure_are_visible() {
        let dir = tempfile::tempdir().unwrap();
        let log = logger(dir.path());
        assert!(Logging::open(
            dir.path(),
            Role::App,
            log.0.settings.clone(),
            SecretRedactor::default()
        )
        .is_err());
        std::fs::create_dir(today_file(&log)).unwrap();
        tracing::dispatcher::with_default(&log.dispatch(), || tracing::error!("cannot append"));
        assert_eq!(log.check_health().unwrap_err().code, "E-LOG-IO");
        assert!(log.shutdown().is_err());
    }
}
