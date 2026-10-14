use crate::{AppError, Result};
use serde::{Deserialize, Serialize};

/// チャンネル境界を明示する識別子。保存値の検証も同じ入口を通す。
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct ChannelId(String);

impl ChannelId {
    pub fn new(value: impl Into<String>) -> Result<Self> {
        let value = value.into();
        if value.is_empty() || value.trim() != value || value.chars().any(char::is_control) {
            tracing::error!("チャンネル識別子の検証に失敗");
            return Err(AppError::new(
                "E-CHANNEL-ID",
                "チャンネル識別子が不正です",
                "空文字・制御文字・前後の空白を含まない識別子を指定してください",
            ));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for ChannelId {
    type Error = AppError;

    fn try_from(value: String) -> Result<Self> {
        Self::new(value)
    }
}

impl From<ChannelId> for String {
    fn from(value: ChannelId) -> Self {
        value.0
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn deserialization_validates_and_round_trips_identifiers() {
        for value in [
            "",
            " channel",
            "channel ",
            "\u{3000}channel",
            "channel\n",
            "chan\0nel",
        ] {
            let json = serde_json::to_string(value).unwrap();
            assert!(serde_json::from_str::<ChannelId>(&json).is_err());
        }
        let id = ChannelId::new("チャンネル-01").unwrap();
        let json = serde_json::to_string(&id).unwrap();
        assert_eq!(serde_json::from_str::<ChannelId>(&json).unwrap(), id);
        assert_eq!(id.as_str(), "チャンネル-01");
    }
}
