#![allow(clippy::disallowed_methods, clippy::disallowed_types)]

use crate::{AppError, Result};
use chrono::{DateTime, SecondsFormat, TimeZone, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
pub use std::time::Instant;

pub fn now_utc_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

/// リース等の期限をUTC日時に加える。桁あふれや日時の上限を黙って丸めない。
pub fn add_duration(at: &Timestamp, duration: std::time::Duration) -> Result<Timestamp> {
    chrono::TimeDelta::from_std(duration)
        .ok()
        .and_then(|delta| at.0.checked_add_signed(delta))
        .map(Timestamp)
        .ok_or_else(|| {
            tracing::error!(
                code = "E-TIME-INVALID",
                "期限の加算が日時の範囲を超えました"
            );
            AppError::new(
                "E-TIME-INVALID",
                "期限を日時へ加算できません",
                "基準日時と待機・リース期間の上限を確認してください",
            )
        })
}

/// 旧DBだけにあるnaive日時は、呼出元が明示したzoneで一度だけUTCへ変換する。
/// 夏時間の曖昧な日時・存在しない日時を推測で補わない。
pub fn parse_legacy(value: &str, source_timezone: &str) -> Result<Timestamp> {
    if let Ok(value) = DateTime::parse_from_rfc3339(value) {
        return Ok(Timestamp(value.with_timezone(&Utc)));
    }
    let zone = timezone(source_timezone)?;
    let parsed = ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"]
        .iter()
        .find_map(|format| chrono::NaiveDateTime::parse_from_str(value, format).ok())
        .and_then(|naive| zone.from_local_datetime(&naive).single());
    match parsed {
        Some(value) => Ok(Timestamp(value.with_timezone(&Utc))),
        None => {
            tracing::error!(
                code = "E-TIME-LEGACY",
                "旧データの日時を一意に変換できません"
            );
            Err(AppError::new(
                "E-TIME-LEGACY",
                "旧データの日時をUTCへ変換できません",
                "元の日時と指定タイムゾーンを確認し、欠損・夏時間の曖昧さを修正してください",
            ))
        }
    }
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
    fn duration_crosses_leap_day_in_utc_and_rejects_overflow() {
        let at = Timestamp::parse("2024-03-01T08:59:59.500+09:00").unwrap();
        assert_eq!(
            add_duration(&at, std::time::Duration::from_millis(500))
                .unwrap()
                .to_utc_iso(),
            "2024-03-01T00:00:00Z"
        );
        assert_eq!(add_duration(&at, std::time::Duration::ZERO).unwrap(), at);
        assert!(add_duration(&at, std::time::Duration::MAX).is_err());
    }
    #[test]
    fn legacy_timestamps_require_explicit_zone_and_unique_local_time() {
        assert_eq!(
            parse_legacy("2026-10-16T12:00:00", "Asia/Tokyo")
                .unwrap()
                .to_utc_iso(),
            "2026-10-16T03:00:00Z"
        );
        assert_eq!(
            parse_legacy("2026-10-16T12:00:00+09:00", "Asia/Tokyo")
                .unwrap()
                .to_utc_iso(),
            "2026-10-16T03:00:00Z"
        );
        assert!(parse_legacy("", "Asia/Tokyo").is_err());
        assert!(parse_legacy("2026-10-25T01:30:00", "Europe/London").is_err());
        assert!(parse_legacy("2026-03-29T01:30:00", "Europe/London").is_err());
    }
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
