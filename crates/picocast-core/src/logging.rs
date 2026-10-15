/// 各処理はこの span の中で実行し、チャンネルとジョブを記録する。
pub fn operation_span(channel_id: &str, job_id: &str) -> tracing::Span {
    tracing::info_span!("operation", channel_id, job_id)
}
