#![allow(clippy::unwrap_used)]
use picocast_ai::Cancellation;
use picocast_core::{proc::service::OwnedService, AppError, ChannelId, Result};
use picocast_pipeline::{
    preflight::{
        system::{DiskCheck, SystemProbe},
        Dependency, Preflight, PreflightOptions, PreflightResources, ProbeFuture, ReadinessProbe,
        ServiceCommand,
    },
    ResourceGate, ResourcePermit, StepFailure, StepFuture,
};
use std::{
    cell::Cell,
    collections::{BTreeMap, BTreeSet, VecDeque},
    ffi::OsString,
    rc::Rc,
    time::Duration,
};

struct Probe {
    answers: VecDeque<Result<bool>>,
    calls: Rc<Cell<usize>>,
    slow: bool,
}
impl ReadinessProbe for Probe {
    fn ready<'a>(&'a mut self, _: &'a ChannelId, _: Dependency) -> ProbeFuture<'a> {
        Box::pin(async move {
            self.calls.set(self.calls.get() + 1);
            if self.slow {
                std::future::pending::<()>().await;
            }
            self.answers.pop_front().unwrap()
        })
    }
}
fn options() -> PreflightOptions {
    PreflightOptions {
        probe_timeout: Duration::from_millis(30),
        startup_timeout: Duration::from_secs(5),
        poll_interval: Duration::from_millis(5),
        max_restarts: 1,
    }
}
fn channel() -> ChannelId {
    ChannelId::new("channel-a").unwrap()
}
fn configured(
    required: &[Dependency],
    answers: Vec<Result<bool>>,
    commands: BTreeMap<Dependency, ServiceCommand>,
) -> (Preflight, Rc<Cell<usize>>) {
    let calls = Rc::new(Cell::new(0));
    let p = Preflight::new(
        channel(),
        required.iter().copied().collect(),
        commands,
        Box::new(Probe {
            answers: answers.into(),
            calls: calls.clone(),
            slow: false,
        }),
        options(),
    )
    .unwrap();
    (p, calls)
}
fn command() -> ServiceCommand {
    ServiceCommand {
        program: std::env::current_exe().unwrap(),
        args: ["--ignored", "--exact", "service_child", "--nocapture"]
            .iter()
            .map(OsString::from)
            .collect(),
    }
}

#[test]
#[ignore = "所有プロセスの検証専用。通常suiteで実行しない"]
fn service_child() {
    std::thread::sleep(Duration::from_secs(120));
}

#[tokio::test]
async fn aggregates_all_missing_dependencies_without_launching_any_service() {
    let (mut p, calls) = configured(
        &[
            Dependency::Voicevox,
            Dependency::GeminiCredential,
            Dependency::YoutubeToken,
            Dependency::Disk,
        ],
        vec![Ok(false), Ok(false), Ok(false), Ok(false)],
        BTreeMap::new(),
    );
    let (_handle, cancel) = Cancellation::pair();
    let errors = p.check(&channel(), &cancel).await.unwrap_err();
    assert_eq!(calls.get(), 4);
    assert_eq!(
        errors.iter().map(|e| e.code.as_str()).collect::<Vec<_>>(),
        [
            "E-PREFLIGHT-SERVICE",
            "E-PREFLIGHT-CREDENTIAL",
            "E-PREFLIGHT-CREDENTIAL",
            "E-PREFLIGHT-DISK"
        ]
    );
}

#[tokio::test]
async fn rejects_foreign_channel_before_any_probe() {
    let (mut p, calls) = configured(&[Dependency::Disk], vec![], BTreeMap::new());
    let (_, cancel) = Cancellation::pair();
    assert_eq!(
        p.check(&ChannelId::new("foreign").unwrap(), &cancel)
            .await
            .unwrap_err()[0]
            .code,
        "E-PREFLIGHT-CHANNEL"
    );
    assert_eq!(calls.get(), 0);
}

#[tokio::test]
async fn existing_service_is_neither_started_nor_stopped() {
    let external_command = command();
    let mut external =
        OwnedService::start(&external_command.program, &external_command.args).unwrap();
    // 実在するが起動に失敗するファイルを指定。稼働中判定なら起動しない。
    let file = tempfile::NamedTempFile::new().unwrap();
    let cmd = ServiceCommand {
        program: file.path().to_owned(),
        args: vec![],
    };
    let (mut p, calls) = configured(
        &[Dependency::Voicevox],
        vec![Ok(true)],
        BTreeMap::from([(Dependency::Voicevox, cmd)]),
    );
    let (_, cancel) = Cancellation::pair();
    p.check(&channel(), &cancel).await.unwrap();
    p.shutdown().await.unwrap();
    assert_eq!(calls.get(), 1);
    assert!(external.running().unwrap());
    external.stop().await.unwrap();
}

async fn response_server(body: &str) -> (String, tokio::task::JoinHandle<()>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/version", listener.local_addr().unwrap());
    let response = format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body);
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut buffer = [0; 4096];
        stream.read(&mut buffer).await.unwrap();
        stream.write_all(response.as_bytes()).await.unwrap();
    });
    (url, task)
}

#[tokio::test]
async fn health_probe_checks_response_shape_and_limits_without_using_external_network() {
    for (body, expected) in [("\"0.25.0\"", true), ("{}", false)] {
        let (url, server) = response_server(body).await;
        let mut probe = SystemProbe::new(
            channel(),
            BTreeMap::from([(Dependency::Voicevox, url)]),
            None,
            None,
            Duration::from_secs(2),
            1024,
        )
        .unwrap();
        assert_eq!(
            probe.ready(&channel(), Dependency::Voicevox).await.is_ok(),
            expected
        );
        server.await.unwrap();
    }
    let (url, server) = response_server("\"too-large\"").await;
    let mut probe = SystemProbe::new(
        channel(),
        BTreeMap::from([(Dependency::Voicevox, url)]),
        None,
        None,
        Duration::from_secs(2),
        2,
    )
    .unwrap();
    assert_eq!(
        probe
            .ready(&channel(), Dependency::Voicevox)
            .await
            .unwrap_err()
            .code,
        "E-HTTP-RESPONSE"
    );
    server.await.unwrap();
    let mut probe = SystemProbe::new(
        channel(),
        BTreeMap::from([(Dependency::Voicevox, "http://192.0.2.1/version".into())]),
        None,
        None,
        Duration::from_secs(2),
        1024,
    )
    .unwrap();
    assert_eq!(
        probe
            .ready(&channel(), Dependency::Voicevox)
            .await
            .unwrap_err()
            .code,
        "E-HTTP-REQUEST"
    );
}

#[tokio::test]
async fn owned_service_restarts_only_to_configured_limit_and_shutdown_reaps_it() {
    let (mut p, calls) = configured(
        &[Dependency::Voicevox],
        vec![Ok(false), Ok(true), Ok(false), Ok(true), Ok(false)],
        BTreeMap::from([(Dependency::Voicevox, command())]),
    );
    let (_, cancel) = Cancellation::pair();
    p.check(&channel(), &cancel).await.unwrap();
    p.check(&channel(), &cancel).await.unwrap();
    assert_eq!(
        p.check(&channel(), &cancel).await.unwrap_err()[0].code,
        "E-PREFLIGHT-RESTART"
    );
    assert_eq!(calls.get(), 5);
    p.shutdown().await.unwrap();
}

#[tokio::test]
async fn process_handle_reports_stopped_after_explicit_shutdown() {
    let command = command();
    let mut service = OwnedService::start(&command.program, &command.args).unwrap();
    assert!(service.running().unwrap());
    service.stop().await.unwrap();
    assert!(!service.running().unwrap());
    service.stop().await.unwrap();
}

#[tokio::test]
async fn cancelled_probe_and_probe_deadline_cannot_start_generation() {
    let calls = Rc::new(Cell::new(0));
    let mut p = Preflight::new(
        channel(),
        BTreeSet::from([Dependency::Disk]),
        BTreeMap::new(),
        Box::new(Probe {
            answers: VecDeque::new(),
            calls: calls.clone(),
            slow: true,
        }),
        options(),
    )
    .unwrap();
    let (handle, cancel) = Cancellation::pair();
    assert_eq!(
        p.check(&channel(), &cancel).await.unwrap_err()[0].code,
        "E-PREFLIGHT-TIMEOUT"
    );
    handle.cancel();
    assert_eq!(
        p.check(&channel(), &cancel).await.unwrap_err()[0].code,
        "E-AI-CANCELLED"
    );
    assert_eq!(calls.get(), 1);
}

#[tokio::test]
async fn read_failure_keeps_its_error_code() {
    let (mut p, _) = configured(
        &[Dependency::Disk],
        vec![Err(AppError::new(
            "E-FILE-WRITE",
            "読取失敗",
            "保存先を確認",
        ))],
        BTreeMap::new(),
    );
    let (_, cancel) = Cancellation::pair();
    assert_eq!(
        p.check(&channel(), &cancel).await.unwrap_err()[0].code,
        "E-FILE-WRITE"
    );
}

#[tokio::test]
async fn unavailable_owned_service_hits_startup_deadline() {
    let calls = Rc::new(Cell::new(0));
    let mut settings = options();
    settings.startup_timeout = Duration::from_millis(25);
    let mut p = Preflight::new(
        channel(),
        BTreeSet::from([Dependency::Voicevox]),
        BTreeMap::from([(Dependency::Voicevox, command())]),
        Box::new(Probe {
            answers: (0..100).map(|_| Ok(false)).collect(),
            calls,
            slow: false,
        }),
        settings,
    )
    .unwrap();
    let (_, cancel) = Cancellation::pair();
    assert_eq!(
        p.check(&channel(), &cancel).await.unwrap_err()[0].code,
        "E-PREFLIGHT-TIMEOUT"
    );
    p.shutdown().await.unwrap();
}

struct Gate(Rc<Cell<usize>>);
struct Permit;
impl ResourcePermit for Permit {
    fn sleep_inhibited(&self) -> bool {
        true
    }
    fn gpu_ready(&self) -> bool {
        true
    }
}
impl ResourceGate for Gate {
    fn acquire<'a>(
        &'a mut self,
        _: &'a ChannelId,
        _: bool,
        _: &'a Cancellation,
    ) -> StepFuture<'a, Box<dyn ResourcePermit>> {
        Box::pin(async move {
            self.0.set(self.0.get() + 1);
            Ok(Box::new(Permit) as Box<dyn ResourcePermit>)
        })
    }
}
#[tokio::test]
async fn resource_gate_does_not_acquire_or_execute_after_failed_preflight() {
    let (p, _) = configured(
        &[Dependency::Disk],
        vec![Ok(false), Ok(true)],
        BTreeMap::new(),
    );
    let calls = Rc::new(Cell::new(0));
    let mut gate = PreflightResources {
        preflight: p,
        inner: Box::new(Gate(calls.clone())),
    };
    let (_, cancel) = Cancellation::pair();
    assert!(
        matches!(gate.acquire(&channel(), false, &cancel).await, Err(StepFailure::Failed(error)) if error.code == "E-PREFLIGHT-DISK")
    );
    assert_eq!(calls.get(), 0);
    assert!(gate.acquire(&channel(), false, &cancel).await.is_ok());
    assert_eq!(calls.get(), 1);
}

#[tokio::test]
async fn real_disk_probe_rejects_insufficient_space_and_leaves_no_files() {
    let dir = tempfile::tempdir().unwrap();
    let mut probe = SystemProbe::new(
        channel(),
        BTreeMap::new(),
        None,
        Some(DiskCheck {
            directory: dir.path().to_owned(),
            minimum_free_bytes: u64::MAX,
        }),
        Duration::from_secs(1),
        1024,
    )
    .unwrap();
    assert!(!probe.ready(&channel(), Dependency::Disk).await.unwrap());
    assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 0);
    assert!(!picocast_core::fsutil::check_output_capacity(dir.path(), u64::MAX).unwrap());
    assert!(picocast_core::fsutil::check_output_capacity(dir.path(), 1).unwrap());
}

#[tokio::test]
async fn missing_credential_adapter_is_an_error_and_never_default_success() {
    let mut probe = SystemProbe::new(
        channel(),
        BTreeMap::new(),
        None,
        None,
        Duration::from_secs(1),
        1024,
    )
    .unwrap();
    assert_eq!(
        probe
            .ready(&channel(), Dependency::YoutubeToken)
            .await
            .unwrap_err()
            .code,
        "E-PREFLIGHT-SETTINGS"
    );
}

#[test]
fn invalid_configuration_is_rejected() {
    let calls = Rc::new(Cell::new(0));
    let result = Preflight::new(
        channel(),
        BTreeSet::from([Dependency::GeminiCredential]),
        BTreeMap::from([(Dependency::GeminiCredential, command())]),
        Box::new(Probe {
            answers: VecDeque::new(),
            calls,
            slow: false,
        }),
        options(),
    );
    assert!(matches!(result, Err(error) if error.code == "E-PREFLIGHT-SETTINGS"));
}
