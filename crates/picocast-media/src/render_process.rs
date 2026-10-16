use picocast_core::{proc, Result};
use std::{ffi::OsString, future::Future, path::PathBuf, pin::Pin};

pub type RenderProcessFuture<'a> = Pin<Box<dyn Future<Output = Result<RenderProcessOutput>> + 'a>>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RenderCommandKind {
    Version,
    Encoders,
    Encode,
    Probe,
}
pub struct RenderCommand {
    pub kind: RenderCommandKind,
    pub program: PathBuf,
    pub arguments: Vec<OsString>,
    pub limits: proc::RunOptions,
}
pub struct RenderProcessOutput {
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

/// 録画・偽processも同じ有限入力を受け、エンコーダの契約を検査できる。
pub trait RenderProcess {
    fn run<'a>(
        &'a mut self,
        command: RenderCommand,
        input: Option<proc::ProcessInput>,
    ) -> RenderProcessFuture<'a>;
}
pub struct CoreRenderProcess;
impl RenderProcess for CoreRenderProcess {
    fn run<'a>(
        &'a mut self,
        command: RenderCommand,
        input: Option<proc::ProcessInput>,
    ) -> RenderProcessFuture<'a> {
        Box::pin(async move {
            let output = match input {
                Some(input) => {
                    proc::run_with_input(
                        &command.program,
                        &command.arguments,
                        command.limits,
                        input,
                    )
                    .await?
                }
                None => proc::run(&command.program, &command.arguments, command.limits).await?,
            };
            Ok(RenderProcessOutput {
                stdout: output.stdout,
                stderr: output.stderr,
            })
        })
    }
}
