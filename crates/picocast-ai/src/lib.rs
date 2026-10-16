//! 工程別の明示モデル選択、契約検査と費用制限をまとめる生成入口。
mod gateway;
pub mod image;
pub mod image_contract;
pub mod image_fake;
mod provider;
mod types;

pub use gateway::Gateway;
pub use provider::{
    retry_after, Completion, CompletionInput, FaultKind, HttpMethod, HttpTransport, LlmProvider,
    Operation, ProviderContract, ProviderFault, ProviderLimits, ProviderOutput, ProviderResult,
    Transport, TransportRequest, TransportResponse, GEMINI_ENDPOINT, OPENAI_ENDPOINT,
};
pub use types::{
    CachedGeneration, CancelHandle, Cancellation, FutureResult, GatewayOptions, GenerateRequest,
    Generation, ModelRegistry, NoCache, Provenance, ProviderId, ResultCache, Secret, Stage,
    StageModel, Usage,
};

use picocast_core::AppError;

#[track_caller]
pub(crate) fn failure(code: &str) -> AppError {
    let caller = std::panic::Location::caller();
    tracing::error!(
        code,
        source = caller.file(),
        line = caller.line(),
        "AI処理を停止しました"
    );
    AppError::new(
        code,
        "AI処理を完了できませんでした",
        "モデル設定・通信状態・費用上限を確認してください",
    )
}
