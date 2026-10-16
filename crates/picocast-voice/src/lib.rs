//! 共通辞書・Rust Sudachi による読み補正と、明示チャンネルの音声合成。
mod reading;
mod voicevox;
mod wav;

pub use reading::{
    katakana_to_hiragana, InspectionReason, ReadingAnalyzer, ReadingDictionary, ReadingInspection,
    ReadingMode, ReadingNormalizer, ReadingPolicy, ReadingReport, ReadingToken, SudachiAnalyzer,
    SudachiPaths,
};
pub use voicevox::{
    AccentOverride, AccentPlan, CharacterStyles, CoreVoiceTransport, SynthesisRequest,
    SynthesisResult, VoiceFuture, VoiceMethod, VoiceRequest, VoiceResponse, VoiceTransport,
    Voicevox, VoicevoxSettings,
};
pub use wav::{ensure_trailing_silence, WaveAudio, WavePolicy};

use picocast_core::AppError;

pub(crate) fn failure(code: &str) -> AppError {
    tracing::error!(code, "音声処理を停止しました");
    AppError::new(
        code,
        "読みまたは音声を処理できませんでした",
        "辞書・話者とスタイル・アクセント・音声形式・接続設定を確認してください",
    )
}

#[cfg(test)]
mod tests;
