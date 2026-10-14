use serde::{Deserialize, Serialize};
use std::fmt;

/// 利用者向けのコード・説明・対処。秘密値や内部例外は渡さない。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppError {
    pub code: String,
    pub message: String,
    pub fix: String,
}

impl AppError {
    pub fn new(
        code: impl Into<String>,
        message: impl Into<String>,
        fix: impl Into<String>,
    ) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            fix: fix.into(),
        }
    }
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[{}] {} 対処: {}", self.code, self.message, self.fix)
    }
}

impl std::error::Error for AppError {}
pub type Result<T> = std::result::Result<T, AppError>;
