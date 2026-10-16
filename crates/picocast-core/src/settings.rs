use crate::{AppError, Result};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, sync::RwLock};

/// OSから渡される実行環境情報だけを扱い、設定DBの代わりには使わない。
#[derive(Debug, Clone)]
pub struct StorageEnvironment {
    pub data_parent: std::path::PathBuf,
    pub sync_roots: Vec<std::path::PathBuf>,
}

#[cfg(test)]
#[allow(clippy::disallowed_methods)]
pub(crate) fn test_environment_value(name: &str) -> Option<std::ffi::OsString> {
    std::env::var_os(name)
}

/// 開発用の明示実ツール受入だけで使う。製品設定や環境変数の一般取得APIではない。
#[allow(clippy::disallowed_methods)]
pub fn validation_ffmpeg_path() -> Result<std::path::PathBuf> {
    std::env::var_os("PICOCAST_TEST_FFMPEG")
        .map(std::path::PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| {
            tracing::error!(
                code = "E-SETTING-INVALID",
                "実ツール検証用のffmpeg絶対パスが未指定です"
            );
            AppError::new(
                "E-SETTING-INVALID",
                "実ツール検証用のパスが不正です",
                "ローカル受入時だけPICOCAST_TEST_FFMPEGへ既存ffmpegの絶対パスを指定してください",
            )
        })
}

#[cfg(windows)]
#[allow(clippy::disallowed_methods)]
pub fn windows_storage_environment() -> Result<StorageEnvironment> {
    let data_parent = std::env::var_os("APPDATA")
        .map(std::path::PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| {
            tracing::error!(code = "E-SETTING-ENV", "OSのAPPDATA保存先を取得できません");
            AppError::new(
                "E-SETTING-ENV",
                "OSのデータ保存先を取得できません",
                "WindowsのユーザープロファイルとAPPDATAの設定を確認してください",
            )
        })?;
    let mut sync_roots = Vec::new();
    for name in ["OneDrive", "OneDriveConsumer", "OneDriveCommercial"] {
        if let Some(value) = std::env::var_os(name) {
            let path = std::path::PathBuf::from(value);
            if !path.is_absolute() {
                tracing::error!(
                    code = "E-SETTING-ENV",
                    environment_name = name,
                    "OSの同期先が絶対パスではありません"
                );
                return Err(AppError::new(
                    "E-SETTING-ENV",
                    "OSの同期先が不正です",
                    "Windowsの同期ソフトとユーザープロファイル設定を確認してください",
                ));
            }
            if !sync_roots.contains(&path) {
                sync_roots.push(path);
            }
        }
    }
    Ok(StorageEnvironment {
        data_parent,
        sync_roots,
    })
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum Value {
    Boolean(bool),
    Integer(i64),
    Decimal(f64),
    Text(String),
}

#[derive(Debug, Clone)]
pub enum Constraint {
    Boolean,
    Integer { min: i64, max: i64 },
    Decimal { min: f64, max: f64 },
    Text { max_chars: usize },
    Choice { values: Vec<String> },
}

#[derive(Debug, Clone)]
pub struct Definition {
    pub default: Value,
    pub constraint: Constraint,
}

impl Definition {
    fn accepts(&self, value: &Value) -> bool {
        match (&self.constraint, value) {
            (Constraint::Boolean, Value::Boolean(_)) => true,
            (Constraint::Integer { min, max }, Value::Integer(v)) => min <= v && v <= max,
            (Constraint::Decimal { min, max }, Value::Decimal(v)) => {
                min.is_finite() && max.is_finite() && v.is_finite() && min <= v && v <= max
            }
            (Constraint::Text { max_chars }, Value::Text(v)) => v.chars().count() <= *max_chars,
            (Constraint::Choice { values }, Value::Text(v)) => values.contains(v),
            _ => false,
        }
    }
}

/// 設定の型と範囲の正本。永続化側は保存成功後に更新し、利用時に毎回読む。
pub struct Registry {
    definitions: BTreeMap<String, Definition>,
    values: RwLock<BTreeMap<String, Value>>,
}

impl Registry {
    pub fn new(definitions: BTreeMap<String, Definition>) -> Result<Self> {
        let mut values = BTreeMap::new();
        for (key, definition) in &definitions {
            if key.trim().is_empty() || !definition.accepts(&definition.default) {
                return Err(invalid());
            }
            values.insert(key.clone(), definition.default.clone());
        }
        Ok(Self {
            definitions,
            values: RwLock::new(values),
        })
    }
    pub fn validate(&self, key: &str, value: &Value) -> Result<()> {
        if self.definitions.get(key).is_some_and(|d| d.accepts(value)) {
            Ok(())
        } else {
            Err(invalid())
        }
    }
    pub fn set(&self, key: &str, value: Value) -> Result<()> {
        self.validate(key, &value)?;
        self.values
            .write()
            .map_err(|_| locked())?
            .insert(key.to_owned(), value);
        Ok(())
    }
    pub fn get(&self, key: &str) -> Result<Value> {
        self.values
            .read()
            .map_err(|_| locked())?
            .get(key)
            .cloned()
            .ok_or_else(invalid)
    }
    pub fn boolean(&self, key: &str) -> Result<bool> {
        match self.get(key)? {
            Value::Boolean(v) => Ok(v),
            _ => Err(invalid()),
        }
    }
    pub fn integer(&self, key: &str) -> Result<i64> {
        match self.get(key)? {
            Value::Integer(v) => Ok(v),
            _ => Err(invalid()),
        }
    }
    pub fn decimal(&self, key: &str) -> Result<f64> {
        match self.get(key)? {
            Value::Decimal(v) => Ok(v),
            _ => Err(invalid()),
        }
    }
    pub fn text(&self, key: &str) -> Result<String> {
        match self.get(key)? {
            Value::Text(v) => Ok(v),
            _ => Err(invalid()),
        }
    }
}
fn invalid() -> AppError {
    tracing::error!("設定の型・範囲または登録名が不正");
    AppError::new(
        "E-SETTING-INVALID",
        "設定値が不正です",
        "登録された設定名・型・範囲を確認してください",
    )
}
fn locked() -> AppError {
    tracing::error!("設定レジストリのロックが破損");
    AppError::new(
        "E-SETTING-LOCK",
        "設定を読み書きできません",
        "アプリを再起動してください",
    )
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    #[test]
    fn validates_type_bounds_and_reads_updates_immediately() {
        let registry = Registry::new(BTreeMap::from([(
            "speed".into(),
            Definition {
                default: Value::Integer(2),
                constraint: Constraint::Integer { min: 1, max: 5 },
            },
        )]))
        .unwrap();
        assert!(registry.set("speed", Value::Integer(6)).is_err());
        assert!(registry.set("speed", Value::Text("3".into())).is_err());
        assert!(registry.set("unknown", Value::Integer(3)).is_err());
        assert_eq!(registry.integer("speed").unwrap(), 2);
        registry.set("speed", Value::Integer(5)).unwrap();
        assert_eq!(registry.integer("speed").unwrap(), 5);
    }
}
