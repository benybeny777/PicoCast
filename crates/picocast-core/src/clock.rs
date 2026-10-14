#![allow(clippy::disallowed_methods)]

use crate::{AppError, Result};
use chrono::{DateTime, SecondsFormat, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
pub use std::time::Instant;

pub fn now_utc_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

/// タイムゾーンのない日時を受け付けず、保存時は UTC に統一する。
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Timestamp(DateTime<Utc>);

impl Timestamp {
    pub fn parse(value: &str) -> Result<Self> {
        DateTime::parse_from_rfc3339(value)
            .map(|v| Self(v.with_timezone(&Utc)))
            .map_err(|_| {
                tracing::error!("保存日時のRFC3339解析に失敗");
                AppError::new(
                    "E-TIME-INVALID",
                    "タイムゾーン付き日時が必要です",
                    "RFC3339形式で Z または時差を指定してください",
                )
            })
    }
    pub fn to_utc_iso(&self) -> String {
        self.0.to_rfc3339_opts(SecondsFormat::AutoSi, true)
    }
    pub fn in_timezone(&self, zone: Tz) -> DateTime<Tz> {
        self.0.with_timezone(&zone)
    }
    pub fn as_utc(&self) -> &DateTime<Utc> {
        &self.0
    }
}

impl std::str::FromStr for Timestamp {
    type Err = AppError;
    fn from_str(s: &str) -> Result<Self> {
        Self::parse(s)
    }
}
impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_utc_iso())
    }
}
impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        Self::parse(&value).map_err(serde::de::Error::custom)
    }
}
pub fn timezone(name: &str) -> Result<Tz> {
    name.parse().map_err(|_| {
        tracing::error!("タイムゾーン名の解析に失敗");
        AppError::new(
            "E-TIME-ZONE",
            "タイムゾーンが不正です",
            "IANAタイムゾーン名を指定してください",
        )
    })
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    #[test]
    fn timestamp_rejects_naive_and_normalizes_offset() {
        assert!(Timestamp::parse("2026-10-15T12:00:00").is_err());
        assert_eq!(
            Timestamp::parse("2026-10-15T12:00:00+09:00")
                .unwrap()
                .to_utc_iso(),
            "2026-10-15T03:00:00Z"
        );
        assert!(serde_json::from_str::<Timestamp>("\"2026-10-15T12:00:00\"").is_err());
    }
}
