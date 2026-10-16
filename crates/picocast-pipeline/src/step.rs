use picocast_ai::Cancellation;
use picocast_core::{AppError, ChannelId};
use picocast_store::jobs::WaitReason;
use serde::{de::DeserializeOwned, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::{future::Future, pin::Pin};

pub enum StepFailure {
    Failed(AppError),
    ExternalUnknown(AppError),
    Waiting {
        reason: WaitReason,
        resume_at: Option<picocast_core::clock::Timestamp>,
    },
    Cancelled,
}
pub type StepFuture<'a, T> =
    Pin<Box<dyn Future<Output = std::result::Result<T, StepFailure>> + 'a>>;
pub struct StepCtx<'a> {
    pub channel_id: &'a ChannelId,
    pub job_id: &'a str,
    pub node_id: &'a str,
    /// 同じ工程キーで不明な外部送信を照合する。リース更新で値を変えない。
    pub operation_key: &'a str,
    pub dependencies: &'a BTreeMap<String, serde_json::Value>,
    pub input_assets: &'a BTreeSet<String>,
    pub model_id: Option<&'a str>,
    pub settings: &'a serde_json::Value,
    pub cancel: &'a Cancellation,
}
pub trait Step {
    const NAME: &'static str;
    const VERSION: u32;
    type Input: Serialize + DeserializeOwned;
    type Output: Serialize + DeserializeOwned;
    fn run<'a>(&'a self, input: Self::Input, ctx: &'a StepCtx<'a>) -> StepFuture<'a, Self::Output>;
}
