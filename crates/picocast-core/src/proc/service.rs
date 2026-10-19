//! 長時間サービスの実体と、その起動で得た所有権だけを保持する。
use super::internal;
use crate::Result;
use std::{ffi::OsString, path::Path, process::Stdio};
use tokio::process::{Child, Command};

/// PIDを再検索せず、起動時の子ハンドルと専用プロセス領域を所有する。
pub struct OwnedService {
    child: Child,
    #[cfg(windows)]
    scope: Option<super::windows::Scope>,
    #[cfg(unix)]
    scope: Option<super::UnixScope>,
}
impl OwnedService {
    pub fn start(program: &Path, args: &[OsString]) -> Result<Self> {
        crate::paths::require_regular_file(program)?;
        let mut command = Command::new(program);
        // サービスが任意に出力する秘密値をアプリのログへ取り込まない。
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        #[cfg(windows)]
        let scope = super::windows::Scope::prepare(&mut command).map_err(internal)?;
        #[cfg(unix)]
        command.process_group(0);
        #[cfg_attr(not(windows), allow(unused_mut))]
        let mut child = command.spawn().map_err(internal)?;
        #[cfg(unix)]
        let scope = super::UnixScope(
            child
                .id()
                .ok_or_else(|| internal(std::io::Error::other("プロセスIDなし")))?,
        );
        #[cfg(windows)]
        if let Err(error) = scope.attach(&child) {
            if let Err(cleanup) = child.start_kill() {
                tracing::error!(error = %cleanup, "サービス起動失敗後の停止に失敗");
            }
            return Err(internal(error));
        }
        Ok(Self {
            child,
            scope: Some(scope),
        })
    }

    pub fn running(&mut self) -> Result<bool> {
        self.child
            .try_wait()
            .map(|status| status.is_none())
            .map_err(internal)
    }

    pub async fn stop(&mut self) -> Result<()> {
        // ハンドルを閉じて子孫も停止する。共有ポートや外部PIDは操作しない。
        drop(self.scope.take());
        // 領域の終了と根への二重killを競合させず、終了した根を回収する。
        self.child.wait().await.map_err(internal)?;
        Ok(())
    }
}
impl Drop for OwnedService {
    fn drop(&mut self) {
        drop(self.scope.take());
        // Futureが中断された場合もkill_on_dropで根を停止する。
    }
}
