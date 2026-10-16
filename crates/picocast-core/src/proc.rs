#![allow(clippy::disallowed_types)]

use crate::{AppError, Result};
use std::{
    ffi::OsString,
    path::Path,
    process::{Output, Stdio},
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    process::Command,
};

#[cfg(windows)]
mod windows;

pub struct RunOptions {
    pub timeout: Duration,
    /// 標準出力・標準エラーそれぞれの上限。呼出元の設定から指定する。
    pub max_output_bytes: usize,
}

/// 有界channelから順次入力する。生成元の失敗をEOFと取り違えない。
pub struct ProcessInput {
    pub chunks: tokio::sync::mpsc::Receiver<Result<Vec<u8>>>,
    pub max_chunk_bytes: usize,
}

/// 有限処理専用。終了・失敗・中断のいずれでも所有する子孫を回収する。
pub async fn run(program: &Path, args: &[OsString], options: RunOptions) -> Result<Output> {
    run_with_environment(program, args, options, &[]).await
}

/// 外部ツール起動用の一時環境だけを明示注入し、呼出元の環境を変更しない。
pub async fn run_with_environment(
    program: &Path,
    args: &[OsString],
    options: RunOptions,
    environment: &[(OsString, OsString)],
) -> Result<Output> {
    run_inner(program, args, options, environment, None).await
}

/// 全入力をメモリや一時ファイルへ集めず、標準入力へ送る有限処理。
pub async fn run_with_input(
    program: &Path,
    args: &[OsString],
    options: RunOptions,
    input: ProcessInput,
) -> Result<Output> {
    run_inner(program, args, options, &[], Some(input)).await
}

async fn run_inner(
    program: &Path,
    args: &[OsString],
    options: RunOptions,
    environment: &[(OsString, OsString)],
    input: Option<ProcessInput>,
) -> Result<Output> {
    if options.timeout.is_zero()
        || options.max_output_bytes == 0
        || input
            .as_ref()
            .is_some_and(|input| input.max_chunk_bytes == 0)
    {
        return Err(failure(
            "E-PROCESS-LIMIT",
            "実行制限が不正です",
            "制限時間と出力上限を0より大きくしてください",
        ));
    }
    let mut command = Command::new(program);
    command
        .args(args)
        .envs(environment.iter().map(|(key, value)| (key, value)))
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(windows)]
    let scope = windows::Scope::prepare(&mut command).map_err(internal)?;
    #[cfg(unix)]
    command.process_group(0);
    let mut child = command.spawn().map_err(internal)?;
    #[cfg(unix)]
    let scope = UnixScope(
        child
            .id()
            .ok_or_else(|| internal(std::io::Error::other("プロセスIDなし")))?,
    );
    #[cfg(windows)]
    if let Err(err) = scope.attach(&child) {
        // 登録前の根は停止中なので子孫はまだ存在しない。
        return finish(&mut child, scope, Err(internal(err))).await;
    }
    let Some(stdout) = child.stdout.take() else {
        return finish(
            &mut child,
            scope,
            Err(internal(std::io::Error::other("標準出力なし"))),
        )
        .await;
    };
    let Some(stderr) = child.stderr.take() else {
        return finish(
            &mut child,
            scope,
            Err(internal(std::io::Error::other("標準エラーなし"))),
        )
        .await;
    };
    let stdin = child.stdin.take();
    // 入力の送信と出力の読み取りを並行し、どのパイプの待機にも同じ期限を適用する。
    let operation = async {
        let (stdout, stderr, (), status) = tokio::try_join!(
            bounded(stdout, options.max_output_bytes),
            bounded(stderr, options.max_output_bytes),
            feed_input(stdin, input),
            async {
                let status = child.wait().await.map_err(internal)?;
                if !status.success() {
                    tracing::error!(exit_code=?status.code(),"外部プロセスが入力完了前も含め失敗終了しました");
                    return Err(failure(
                        "E-PROCESS-EXIT",
                        "外部処理が失敗しました",
                        "外部ツールの設定と入力を確認してください",
                    ));
                }
                Ok(status)
            },
        )?;
        Ok::<_, AppError>(Output {
            status,
            stdout,
            stderr,
        })
    };
    let result = match tokio::time::timeout(options.timeout, operation).await {
        Ok(Ok(output)) => Ok(output),
        Ok(Err(err)) => Err(err),
        Err(_) => Err(failure(
            "E-PROCESS-TIMEOUT",
            "外部処理が制限時間を超えました",
            "入力と外部ツールを確認し、必要なら制限時間を変更してください",
        )),
    };
    finish(&mut child, scope, result).await
}

async fn feed_input<W: AsyncWrite + Unpin>(
    pipe: Option<W>,
    input: Option<ProcessInput>,
) -> Result<()> {
    let Some(mut input) = input else {
        return Ok(());
    };
    let mut pipe = pipe.ok_or_else(|| internal(std::io::Error::other("標準入力なし")))?;
    while let Some(chunk) = input.chunks.recv().await {
        let chunk = chunk.inspect_err(|error| {
            tracing::error!(code = %error.code, "外部プロセスの入力生成に失敗しました");
        })?;
        if chunk.len() > input.max_chunk_bytes {
            return Err(failure(
                "E-PROCESS-LIMIT",
                "外部処理の入力単位が上限を超えました",
                "入力を分割するか、検証済みフレームの上限を確認してください",
            ));
        }
        pipe.write_all(&chunk).await.map_err(internal)?;
    }
    pipe.shutdown().await.map_err(internal)
}

async fn finish(
    child: &mut tokio::process::Child,
    scope: impl Sized,
    mut result: Result<Output>,
) -> Result<Output> {
    if result.is_err() {
        // 終了済みなら kill を重ねない。確認が失敗しても根の回収へ必ず進む。
        match child.try_wait() {
            Ok(Some(_)) => {}
            Ok(None) => {
                if let Err(err) = child.start_kill() {
                    record_cleanup_error(&mut result, err);
                }
            }
            Err(err) => {
                record_cleanup_error(&mut result, err);
                if let Err(err) = child.start_kill() {
                    record_cleanup_error(&mut result, err);
                }
            }
        }
    }
    // パイプを閉じずに残る子孫も含め、所有領域をここで閉じる。
    drop(scope);
    if let Err(err) = child.wait().await {
        record_cleanup_error(&mut result, err);
    }
    result
}

fn record_cleanup_error(result: &mut Result<Output>, error: std::io::Error) {
    tracing::error!(error = %error, "所有プロセスの終了・回収確認に失敗");
    match result {
        Err(primary) => {
            // 最初の原因のコードを保ち、回収失敗も利用者に知らせる。
            if !primary.message.contains("終了確認にも失敗") {
                primary.message.push_str("。終了確認にも失敗しました");
                primary
                    .fix
                    .push_str("。外部処理が残っていないか確認してください");
            }
        }
        Ok(_) => *result = Err(internal(error)),
    }
}

async fn bounded(pipe: impl AsyncRead + Unpin, max: usize) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    let limit = u64::try_from(max)
        .map_err(|_| {
            failure(
                "E-PROCESS-LIMIT",
                "出力上限が不正です",
                "出力上限を小さくしてください",
            )
        })?
        .saturating_add(1);
    pipe.take(limit)
        .read_to_end(&mut bytes)
        .await
        .map_err(internal)?;
    if bytes.len() > max {
        return Err(failure(
            "E-PROCESS-OUTPUT",
            "外部処理の出力が上限を超えました",
            "外部ツールの出力を減らすか上限を変更してください",
        ));
    }
    Ok(bytes)
}

fn failure(code: &str, message: &str, fix: &str) -> AppError {
    tracing::error!(code, "外部プロセス処理に失敗");
    AppError::new(code, message, fix)
}
fn internal(error: std::io::Error) -> AppError {
    tracing::error!(error = %error, "外部プロセスの操作に失敗");
    AppError::new(
        "E-PROCESS-IO",
        "外部処理を実行できませんでした",
        "ツールの実体と実行権限を確認してください",
    )
}

#[cfg(unix)]
struct UnixScope(u32);
#[cfg(unix)]
impl Drop for UnixScope {
    fn drop(&mut self) {
        // 自分が作った専用プロセスグループだけを停止する。
        if let Ok(pid) = i32::try_from(self.0) {
            if unsafe { libc::kill(-pid, libc::SIGKILL) } != 0 {
                let err = std::io::Error::last_os_error();
                if err.raw_os_error() != Some(libc::ESRCH) {
                    tracing::error!(error = %err, "所有プロセスグループの停止に失敗");
                }
            }
        }
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn streamed_input_preserves_chunks_and_propagates_generation_or_size_errors() {
        let (send, receive) = tokio::sync::mpsc::channel(1);
        let producer = tokio::spawn(async move {
            for chunk in [b"first".to_vec(), b"second".to_vec()] {
                send.send(Ok(chunk)).await.unwrap();
            }
        });
        let (write, mut read) = tokio::io::duplex(3);
        let (written, bytes) = tokio::join!(
            feed_input(
                Some(write),
                Some(ProcessInput {
                    chunks: receive,
                    max_chunk_bytes: 6
                })
            ),
            async {
                let mut bytes = Vec::new();
                read.read_to_end(&mut bytes).await.unwrap();
                bytes
            },
        );
        written.unwrap();
        producer.await.unwrap();
        assert_eq!(bytes, b"firstsecond");
        for chunk in [
            Ok(vec![0; 7]),
            Err(AppError::new("E-PROCESS-IO", "合成検証", "入力を確認")),
        ] {
            let (send, receive) = tokio::sync::mpsc::channel(1);
            send.send(chunk).await.unwrap();
            drop(send);
            let (write, mut read) = tokio::io::duplex(3);
            let (result, bytes) = tokio::join!(
                feed_input(
                    Some(write),
                    Some(ProcessInput {
                        chunks: receive,
                        max_chunk_bytes: 6
                    })
                ),
                async {
                    let mut bytes = Vec::new();
                    read.read_to_end(&mut bytes).await.unwrap();
                    bytes
                },
            );
            assert!(result.is_err());
            assert!(bytes.is_empty());
        }
    }

    #[cfg(windows)]
    #[tokio::test]
    async fn failed_child_does_not_wait_for_a_still_open_input_producer() {
        let (_held_sender, receive) = tokio::sync::mpsc::channel(1);
        let error = run_with_input(
            Path::new("cmd.exe"),
            &["/D".into(), "/C".into(), "exit /b 7".into()],
            RunOptions {
                timeout: Duration::from_secs(1),
                max_output_bytes: 4096,
            },
            ProcessInput {
                chunks: receive,
                max_chunk_bytes: 8192,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(error.code, "E-PROCESS-EXIT");
    }
    #[cfg(windows)]
    #[tokio::test]
    async fn hidden_streaming_child_echoes_binary_and_timeout_covers_unclosed_input() {
        let args = ["-NoProfile".into(), "-NonInteractive".into(), "-Command".into(),
            "$streamIn=[Console]::OpenStandardInput();$streamOut=[Console]::OpenStandardOutput();$streamIn.CopyTo($streamOut)".into()];
        let (send, receive) = tokio::sync::mpsc::channel(1);
        let producer = tokio::spawn(async move {
            for byte in 0..64u8 {
                send.send(Ok(vec![byte; 8192])).await.unwrap();
            }
        });
        let output = run_with_input(
            Path::new("powershell.exe"),
            &args,
            RunOptions {
                timeout: Duration::from_secs(10),
                max_output_bytes: 1024 * 1024,
            },
            ProcessInput {
                chunks: receive,
                max_chunk_bytes: 8192,
            },
        )
        .await
        .unwrap();
        producer.await.unwrap();
        assert_eq!(output.stdout.len(), 64 * 8192);
        for (byte, chunk) in output.stdout.chunks_exact(8192).enumerate() {
            assert!(chunk.iter().all(|value| usize::from(*value) == byte));
        }
        let (_held_sender, receive) = tokio::sync::mpsc::channel(1);
        let error = run_with_input(
            Path::new("powershell.exe"),
            &args,
            RunOptions {
                timeout: Duration::from_millis(100),
                max_output_bytes: 4096,
            },
            ProcessInput {
                chunks: receive,
                max_chunk_bytes: 8192,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(error.code, "E-PROCESS-TIMEOUT");
    }

    #[tokio::test]
    async fn output_limit_rejects_instead_of_truncating() {
        assert_eq!(
            bounded(&b"12345"[..], 4).await.unwrap_err().code,
            "E-PROCESS-OUTPUT"
        );
        assert_eq!(bounded(&b"1234"[..], 4).await.unwrap(), b"1234");
    }
    #[cfg(windows)]
    #[tokio::test]
    async fn hidden_process_runs_and_timeout_stops_it() {
        let output = run(
            Path::new("cmd.exe"),
            &["/D".into(), "/C".into(), "echo ready".into()],
            RunOptions {
                timeout: Duration::from_secs(5),
                max_output_bytes: 4096,
            },
        )
        .await
        .unwrap();
        assert!(String::from_utf8_lossy(&output.stdout).contains("ready"));
        let err = run(
            Path::new("cmd.exe"),
            &[
                "/D".into(),
                "/C".into(),
                "ping -n 10 127.0.0.1 > nul".into(),
            ],
            RunOptions {
                timeout: Duration::from_millis(100),
                max_output_bytes: 4096,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(err.code, "E-PROCESS-TIMEOUT");
        let err = run(
            Path::new("cmd.exe"),
            &["/D".into(), "/C".into(), "exit /b 7".into()],
            RunOptions {
                timeout: Duration::from_secs(5),
                max_output_bytes: 4096,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(err.code, "E-PROCESS-EXIT");
        let err = run(
            Path::new("cmd.exe"),
            &["/D".into(), "/C".into(), "echo too-long".into()],
            RunOptions {
                timeout: Duration::from_secs(5),
                max_output_bytes: 3,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(err.code, "E-PROCESS-OUTPUT");
    }
}
