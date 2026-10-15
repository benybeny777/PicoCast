use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fmt;
use std::sync::OnceLock;

/// エラーの意味と再試行可否。表示文言は日本語カタログのキーで参照する。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ErrorDef {
    pub code: String,
    pub category: String,
    pub retry_recommended: bool,
    pub message_key: String,
    pub fix_key: String,
}

/// 画面へ渡す安定した契約。内部例外やトレースを引数に入れない。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorPayload {
    pub code: String,
    pub message_key: String,
    pub args: BTreeMap<String, String>,
    pub fix_key: String,
}

struct Catalog {
    entries: BTreeMap<String, ErrorDef>,
    labels: BTreeMap<String, String>,
}

static CATALOG: OnceLock<Result<Catalog>> = OnceLock::new();

fn invalid_catalog() -> AppError {
    AppError::new(
        "E-CATALOG-INVALID",
        "エラー文言カタログを読み込めません。",
        "アプリのファイルを正しい版に戻して再起動し、解決しない場合はデバッグログを開発者へ伝えてください。",
    )
}

fn load_catalog() -> Result<Catalog> {
    let definitions: Vec<ErrorDef> = serde_json::from_str(include_str!("error_catalog.json"))
        .map_err(|error| {
            tracing::error!(%error, "エラー定義の読込みに失敗しました");
            invalid_catalog()
        })?;
    let labels: BTreeMap<String, String> =
        serde_json::from_str(include_str!("../../../ui/i18n/ja.json")).map_err(|error| {
            tracing::error!(%error, "日本語文言の読込みに失敗しました");
            invalid_catalog()
        })?;
    let mut entries = BTreeMap::new();
    for definition in definitions {
        for key in [&definition.message_key, &definition.fix_key] {
            if labels.get(key).is_none_or(|text| text.trim().is_empty()) {
                tracing::error!(code = %definition.code, %key, "エラー文言または対処手順がありません");
                return Err(invalid_catalog());
            }
        }
        let code = definition.code.clone();
        if entries.insert(code.clone(), definition).is_some() {
            tracing::error!(%code, "エラーコードが重複しています");
            return Err(invalid_catalog());
        }
    }
    Ok(Catalog { entries, labels })
}

fn catalog() -> Result<&'static Catalog> {
    CATALOG
        .get_or_init(load_catalog)
        .as_ref()
        .map_err(Clone::clone)
}

/// 未登録コードを既知コードへ読み替えず、明示的に失敗させる。
pub fn get_error(code: &str) -> Result<&'static ErrorDef> {
    catalog()?.entries.get(code).ok_or_else(|| {
        tracing::error!(%code, "未登録のエラーコードです");
        AppError::new(
            "E-CATALOG-CODE",
            "未登録のエラーコードが指定されました。",
            "アプリを更新し、解決しない場合は発生した操作とデバッグログを開発者へ伝えてください。",
        )
    })
}

pub fn error_catalog() -> Result<&'static BTreeMap<String, ErrorDef>> {
    Ok(&catalog()?.entries)
}

/// 利用者向けのコード・説明・対処。秘密値や内部例外は渡さない。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppError {
    pub code: String,
    pub message: String,
    pub fix: String,
}

impl AppError {
    pub fn from_code(code: &str) -> Result<Self> {
        let definition = get_error(code)?;
        let labels = &catalog()?.labels;
        let message = labels
            .get(&definition.message_key)
            .ok_or_else(invalid_catalog)?;
        let fix = labels
            .get(&definition.fix_key)
            .ok_or_else(invalid_catalog)?;
        Ok(Self::new(code, message, fix))
    }

    pub fn payload(&self) -> Result<ErrorPayload> {
        let definition = get_error(&self.code)?;
        Ok(ErrorPayload {
            code: definition.code.clone(),
            message_key: definition.message_key.clone(),
            args: BTreeMap::new(),
            fix_key: definition.fix_key.clone(),
        })
    }

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_definition_resolves_to_nonempty_localized_error() -> Result<()> {
        for (code, definition) in error_catalog()? {
            let error = AppError::from_code(code)?;
            assert!(!error.message.trim().is_empty());
            assert!(!error.fix.trim().is_empty());
            let payload = error.payload()?;
            assert_eq!(payload.message_key, definition.message_key);
            assert_eq!(payload.fix_key, definition.fix_key);
            assert!(payload.args.is_empty());
        }
        Ok(())
    }

    #[test]
    fn unknown_code_does_not_silently_use_unknown_error() {
        assert!(
            matches!(get_error("E-DOES-NOT-EXIST"), Err(error) if error.code == "E-CATALOG-CODE")
        );
    }

    #[test]
    fn payload_does_not_disclose_custom_detail() -> Result<()> {
        let error = AppError::new("E-NET", "内部の詳細", "内部の対処");
        let payload = serde_json::to_string(&error.payload()?).map_err(|_| invalid_catalog())?;
        assert!(!payload.contains("内部"));
        Ok(())
    }
}
