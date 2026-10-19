//! 永続ジョブと工程DAG。実プロバイダの副作用は個別Stepが所有する。
mod dag;
pub mod preflight;
mod resources;
mod runner;
mod step;
pub mod thumbnail;
pub use dag::{CacheEnvelope, CachePolicy, Dag, Node, Provenance, RetrySafety};
pub use resources::{CoordinatedResources, SleepInhibitor, SleepPermit};
pub use runner::{Pipeline, ResourceGate, ResourcePermit, RunOptions, TickOutcome};
pub use step::{Step, StepCtx, StepFailure, StepFuture};

use picocast_core::{AppError, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};

fn failure(code: &str) -> AppError {
    tracing::error!(code, "工程処理を停止しました");
    AppError::new(
        code,
        "工程を完了できませんでした",
        "ジョブ状態・入力素材・工程の版・保存先を確認してください",
    )
}
pub fn content_hash<T: Serialize>(value: &T) -> Result<String> {
    let value = serde_json::to_value(value).map_err(|_| failure("E-PIPELINE-INPUT"))?;
    let digest =
        Sha256::digest(serde_json::to_vec(&value).map_err(|_| failure("E-PIPELINE-INPUT"))?);
    Ok(digest.iter().map(|byte| format!("{byte:02x}")).collect())
}
fn valid_hash(hash: &str) -> bool {
    hash.len() == 64
        && hash
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
fn now() -> Result<picocast_core::clock::Timestamp> {
    picocast_core::clock::Timestamp::parse(&picocast_core::clock::now_utc_iso())
}
