#![allow(clippy::disallowed_methods)]

use crate::{AppError, Result};
use std::time::Duration;

/// HTTP接続の実体を共通境界だけが所有する。
pub struct Client {
    inner: reqwest::Client,
}

/// 全 HTTP 利用者が有限の接続・要求タイムアウトを指定する。
pub fn client(timeout: Duration) -> Result<Client> {
    build_client(timeout, false)
}

/// ローカルサービス向け。OSや環境変数のproxyへ本文を転送しない。
pub fn local_client(timeout: Duration) -> Result<Client> {
    build_client(timeout, true)
}

fn build_client(timeout: Duration, local: bool) -> Result<Client> {
    if timeout.is_zero() {
        tracing::error!("HTTP制限時間に0を指定");
        return Err(AppError::new(
            "E-HTTP-TIMEOUT",
            "通信の制限時間が不正です",
            "0より大きい制限時間を指定してください",
        ));
    }
    let builder = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .tls_backend_rustls()
        .connect_timeout(timeout)
        .timeout(timeout);
    let builder = if local { builder.no_proxy() } else { builder };
    builder
        .build()
        .map(|inner| Client { inner })
        .map_err(|err| {
            tracing::error!(error = %err, "HTTPクライアント作成に失敗");
            AppError::new(
                "E-HTTP-CLIENT",
                "通信を準備できませんでした",
                "ネットワーク環境を確認してください",
            )
        })
}

/// 応答本文はDebugへ含めない。エラー応答はstatusとRetry-Afterだけを公開する。
pub struct JsonResponse {
    pub status: u16,
    pub retry_after: Option<String>,
    pub body: serde_json::Value,
}

/// 音声などのバイナリ応答。本文はログやDebugへ渡さない。
pub struct ByteResponse {
    pub status: u16,
    pub retry_after: Option<String>,
    pub body: Vec<u8>,
}

fn request_failure() -> AppError {
    tracing::error!(code = "E-HTTP-REQUEST", "HTTP要求に失敗しました");
    AppError::new(
        "E-HTTP-REQUEST",
        "通信要求を完了できませんでした",
        "接続先とサービスの起動状態、通信設定、制限時間を確認してください",
    )
}

fn response_failure() -> AppError {
    tracing::error!(
        code = "E-HTTP-RESPONSE",
        "HTTP応答の形式または容量制限に違反しました"
    );
    AppError::new(
        "E-HTTP-RESPONSE",
        "通信応答を読み取れませんでした",
        "応答形式と容量上限、利用するサービスの互換性を確認してください",
    )
}

fn transport_failure(error: reqwest::Error) -> AppError {
    let (code, message, fix) = if error.is_timeout() {
        ("E-HTTP-DEADLINE", "通信が制限時間を超えました", "サービスの負荷と制限時間を確認してください。送信済みの処理を確認せず再送しないでください")
    } else if error.is_connect() {
        (
            "E-HTTP-OFFLINE",
            "接続先へ接続できませんでした",
            "接続先の起動状態とネットワーク設定を確認してください",
        )
    } else {
        return request_failure();
    };
    tracing::error!(code, "HTTP転送を完了できませんでした");
    AppError::new(code, message, fix)
}

/// 本文を上限付きで取得する共通境界。Futureのdropで送受信も中断できる。
pub async fn request_json(
    client: &Client,
    method: reqwest::Method,
    url: &str,
    headers: &[(String, String)],
    body: Option<&serde_json::Value>,
    max_response_bytes: usize,
) -> Result<JsonResponse> {
    let response = request_bytes(client, method, url, headers, body, max_response_bytes).await?;
    let body = if (200..300).contains(&response.status) {
        serde_json::from_slice(&response.body).map_err(|_| response_failure())?
    } else {
        serde_json::Value::Null
    };
    Ok(JsonResponse {
        status: response.status,
        retry_after: response.retry_after,
        body,
    })
}

/// JSONと音声で、送信・容量・中断・エラー本文の扱いを共有する。
pub async fn request_bytes(
    client: &Client,
    method: reqwest::Method,
    url: &str,
    headers: &[(String, String)],
    body: Option<&serde_json::Value>,
    max_response_bytes: usize,
) -> Result<ByteResponse> {
    if max_response_bytes == 0 {
        return Err(response_failure());
    }
    let url = reqwest::Url::parse(url).map_err(|_| request_failure())?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err(request_failure());
    }
    let mut request = client.inner.request(method, url);
    for (name, value) in headers {
        let name = reqwest::header::HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| request_failure())?;
        let mut value =
            reqwest::header::HeaderValue::from_str(value).map_err(|_| request_failure())?;
        // APIキーを含むヘッダーが別のDebug経路へ漏れるのを防ぐ。
        value.set_sensitive(true);
        request = request.header(name, value);
    }
    if let Some(body) = body {
        request = request.json(body);
    }
    // reqwestの例外本文にはURLやqueryが入り得るため記録しない。
    let mut response = request.send().await.map_err(transport_failure)?;
    let status = response.status().as_u16();
    let retry_after = response
        .headers()
        .get(reqwest::header::RETRY_AFTER)
        .map(|value| {
            value
                .to_str()
                .map(str::to_owned)
                .map_err(|_| response_failure())
        })
        .transpose()?;
    if response
        .content_length()
        .is_some_and(|length| length > max_response_bytes as u64)
    {
        return Err(response_failure());
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(transport_failure)? {
        if chunk.len() > max_response_bytes.saturating_sub(bytes.len()) {
            return Err(response_failure());
        }
        bytes.extend_from_slice(&chunk);
    }
    if !(200..300).contains(&status) {
        // エラー本文のJSON/HTMLや秘密値は呼出側へ転送せず、状態で判定する。
        tracing::warn!(
            code = "E-HTTP-REQUEST",
            status,
            "サービスが要求を受け付けませんでした"
        );
        bytes.clear();
    }
    Ok(ByteResponse {
        status,
        retry_after,
        body: bytes,
    })
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    async fn response_server(response: &'static [u8]) -> (String, tokio::task::JoinHandle<()>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let handle = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = [0u8; 4096];
            let count = socket.read(&mut request).await.unwrap();
            assert!(count > 0);
            socket.write_all(response).await.unwrap();
            socket.shutdown().await.unwrap();
        });
        (format!("http://{address}/fixture"), handle)
    }

    #[tokio::test]
    async fn json_is_bounded_and_error_body_is_not_disclosed() {
        let client = client(Duration::from_secs(2)).unwrap();
        let (url, server) = response_server(
            b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}",
        )
        .await;
        let result = request_json(&client, reqwest::Method::GET, &url, &[], None, 100)
            .await
            .unwrap();
        assert_eq!(result.body["ok"], true);
        server.await.unwrap();
        let (url, server) = response_server(b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 3\r\nContent-Length: 15\r\nConnection: close\r\n\r\nsensitive-value").await;
        let result = request_json(&client, reqwest::Method::GET, &url, &[], None, 100)
            .await
            .unwrap();
        assert_eq!(result.status, 503);
        assert_eq!(result.retry_after.as_deref(), Some("3"));
        assert!(result.body.is_null());
        server.await.unwrap();
    }

    #[tokio::test]
    async fn binary_audio_uses_the_same_bounded_transport() {
        let client = local_client(Duration::from_secs(2)).unwrap();
        let (url, server) = response_server(
            b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nRIFFtest",
        )
        .await;
        let result = request_bytes(
            &client,
            reqwest::Method::POST,
            &url,
            &[],
            Some(&serde_json::json!({})),
            8,
        )
        .await
        .unwrap();
        assert_eq!(result.status, 200);
        assert_eq!(result.body, b"RIFFtest");
        server.await.unwrap();
    }

    #[tokio::test]
    async fn rejects_oversize_chunked_body_and_invalid_json() {
        let client = client(Duration::from_secs(2)).unwrap();
        for response in [
            &b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n8\r\n12345678\r\n0\r\n\r\n"[..],
            &b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nbad"[..],
        ] {
            let (url, server) = response_server(response).await;
            let error = request_json(&client, reqwest::Method::GET, &url, &[], None, 4).await.err().unwrap();
            assert_eq!(error.code, "E-HTTP-RESPONSE");
            server.await.unwrap();
        }
    }

    #[tokio::test]
    async fn credentials_and_redirects_are_not_forwarded() {
        let client = client(Duration::from_secs(2)).unwrap();
        assert!(request_json(
            &client,
            reqwest::Method::GET,
            "http://user:private@localhost/",
            &[],
            None,
            100
        )
        .await
        .is_err());
        let (url, server) = response_server(b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await;
        let response = request_json(
            &client,
            reqwest::Method::GET,
            &url,
            &[("Authorization".into(), "Bearer synthetic".into())],
            None,
            100,
        )
        .await
        .unwrap();
        assert_eq!(response.status, 302);
        assert!(response.body.is_null());
        server.await.unwrap();
    }

    #[tokio::test]
    async fn connection_failure_and_elapsed_deadline_have_distinct_codes() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        drop(listener);
        // Windowsの接続拒否通知を、短い要求期限と取り違えない。
        let client = client(Duration::from_secs(5)).unwrap();
        let error = request_json(
            &client,
            reqwest::Method::GET,
            &format!("http://{address}/"),
            &[],
            None,
            100,
        )
        .await
        .err()
        .unwrap();
        assert_eq!(error.code, "E-HTTP-OFFLINE");
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (_socket, _) = listener.accept().await.unwrap();
            std::future::pending::<()>().await;
        });
        let bounded_client = super::client(Duration::from_millis(100)).unwrap();
        let error = request_json(
            &bounded_client,
            reqwest::Method::GET,
            &format!("http://{address}/"),
            &[],
            None,
            100,
        )
        .await
        .err()
        .unwrap();
        server.abort();
        assert!(server.await.unwrap_err().is_cancelled());
        assert_eq!(error.code, "E-HTTP-DEADLINE");
    }
}
