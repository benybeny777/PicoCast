#![allow(clippy::disallowed_methods)]

use crate::{AppError, Result};
use std::time::Duration;

/// 全 HTTP 利用者が有限の接続・要求タイムアウトを指定する。
pub fn client(timeout: Duration) -> Result<reqwest::Client> {
    if timeout.is_zero() {
        tracing::error!("HTTP制限時間に0を指定");
        return Err(AppError::new(
            "E-HTTP-TIMEOUT",
            "通信の制限時間が不正です",
            "0より大きい制限時間を指定してください",
        ));
    }
    reqwest::Client::builder()
        .tls_backend_rustls()
        .connect_timeout(timeout)
        .timeout(timeout)
        .build()
        .map_err(|err| {
            tracing::error!(error = %err, "HTTPクライアント作成に失敗");
            AppError::new(
                "E-HTTP-CLIENT",
                "通信を準備できませんでした",
                "ネットワーク環境を確認してください",
            )
        })
}
