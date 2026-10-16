//! チャンネル内の不変なテンプレート版と有効なキャラクターだけから組み立てる。

use crate::{invalid, DIALOGUE_RULES};
use picocast_core::{ChannelId, Result};
use picocast_store::{
    repository::{Character, PromptTemplate, PromptTemplateVersion},
    Store,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Script,
    Title,
    Meeting,
}
impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Script => "script",
            Self::Title => "title",
            Self::Meeting => "meeting",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TemplateRef {
    pub id: String,
    pub version: i64,
}

pub struct PromptContext<'a> {
    pub existing_titles: &'a [String],
    pub analytics_tsv: Option<&'a str>,
    pub expansion_criteria: &'a [String],
}

#[derive(Debug, Clone)]
pub struct PreparedPrompt {
    pub text: String,
    pub template: TemplateRef,
    pub speakers: Vec<ActiveCharacter>,
}

#[derive(Debug, Clone)]
pub struct ActiveCharacter {
    pub channel_id: ChannelId,
    pub id: String,
    pub character_name: String,
    pub display_name: String,
    pub role: String,
    pub tone_style: String,
    pub speaking_rules: String,
    pub forbidden_phrases: String,
    pub dialogue_rules: String,
    pub sort_order: i64,
    pub styles: std::collections::BTreeMap<String, String>,
}

pub fn active_characters(store: &Store, channel: &ChannelId) -> Result<Vec<ActiveCharacter>> {
    let rows = store.repository(channel)?.list::<Character>()?;
    let mut active = Vec::new();
    for record in rows {
        let (format, fields) = envelope(&record.usage_rules_json)?;
        if !matches!(format, "legacy-character-v1" | "character-rules-v1") {
            return Err(invalid());
        }
        if format == "legacy-character-v1"
            && fields.get("profile_id").and_then(Value::as_str) != Some(channel.as_str())
        {
            return Err(invalid());
        }
        if !enabled(fields, format.starts_with("legacy-"), "enabled")? {
            continue;
        }
        let styles = record
            .style_map_json
            .as_object()
            .ok_or_else(invalid)?
            .iter()
            .map(|(name, value)| {
                let id = match value {
                    Value::Number(number) => number.as_u64().map(|number| number.to_string()),
                    Value::String(value) => Some(value.clone()),
                    _ => None,
                }
                .filter(|value| !value.is_empty())
                .ok_or_else(invalid)?;
                Ok((name.clone(), id))
            })
            .collect::<Result<_>>()?;
        active.push(ActiveCharacter {
            channel_id: channel.clone(),
            id: record.id,
            character_name: text(fields, "character_name", true)?,
            display_name: record.name,
            role: text(fields, "role", false)?,
            tone_style: text(fields, "tone_style", false)?,
            speaking_rules: text(fields, "speaking_rules", false)?,
            forbidden_phrases: text(fields, "forbidden_phrases", false)?,
            dialogue_rules: text(fields, "dialogue_rules", false)?,
            sort_order: fields
                .get("sort_order")
                .and_then(Value::as_i64)
                .ok_or_else(invalid)?,
            styles,
        });
    }
    if active.is_empty() {
        return Err(invalid());
    }
    active.sort_by(|left, right| {
        left.sort_order
            .cmp(&right.sort_order)
            .then_with(|| left.id.cmp(&right.id))
    });
    let mut names = std::collections::BTreeSet::new();
    if active
        .iter()
        .any(|character| !names.insert(&character.character_name))
    {
        return Err(invalid());
    }
    Ok(active)
}

pub fn build(
    store: &Store,
    channel: &ChannelId,
    kind: Kind,
    context: &PromptContext<'_>,
) -> Result<PreparedPrompt> {
    let repository = store.repository(channel)?;
    let defaults = repository
        .list::<PromptTemplate>()?
        .into_iter()
        .filter(|template| template.kind == kind.as_str() && template.is_default)
        .collect::<Vec<_>>();
    let template = match defaults.as_slice() {
        [one] => one,
        _ => return Err(invalid()),
    };
    let version = repository
        .list::<PromptTemplateVersion>()?
        .into_iter()
        .filter(|version| version.template_id == template.id)
        .max_by_key(|version| version.version)
        .ok_or_else(invalid)?;
    let speakers = if kind == Kind::Script {
        active_characters(store, channel)?
    } else {
        Vec::new()
    };
    build_from_version(channel, template, &version, &speakers, kind, context)
}

pub fn build_from_version(
    channel: &ChannelId,
    template: &PromptTemplate,
    version: &PromptTemplateVersion,
    speakers: &[ActiveCharacter],
    kind: Kind,
    context: &PromptContext<'_>,
) -> Result<PreparedPrompt> {
    if &template.channel_id != channel
        || &version.channel_id != channel
        || template.id != version.template_id
        || template.kind != kind.as_str()
        || version.version <= 0
        || speakers
            .iter()
            .any(|speaker| &speaker.channel_id != channel)
    {
        return Err(invalid());
    }
    let body: Value = serde_json::from_str(&version.body).map_err(|_| invalid())?;
    let (format, fields) = envelope(&body)?;
    if !matches!(format, "legacy-template-v1" | "template-v1")
        || !enabled(fields, format.starts_with("legacy-"), "is_enabled")?
    {
        return Err(invalid());
    }
    if format == "legacy-template-v1"
        && fields.get("profile_id").and_then(Value::as_str) != Some(channel.as_str())
    {
        return Err(invalid());
    }
    let mut base = text(fields, "system_rules", false)?;
    let section = match kind {
        Kind::Script => Some("script_rules"),
        Kind::Meeting => Some("meeting_rules"),
        Kind::Title => None,
    };
    for name in section.into_iter().chain(std::iter::once("ng_rules")) {
        let content = text(fields, name, false)?;
        if !content.is_empty() {
            base.push_str("\n\n");
            base.push_str(&content);
        }
    }
    if kind == Kind::Script {
        if speakers.is_empty() {
            return Err(invalid());
        }
        base.push_str("\n\n");
        base.push_str(&character_section(speakers));
        base.push_str("\n\n");
        base.push_str(DIALOGUE_RULES);
        if !context.existing_titles.is_empty() {
            base.push_str("\n\n━━━━━━━━━━━━━━━━━━\n既存タイトル重複禁止（台本生成時も適用）\n━━━━━━━━━━━━━━━━━━\n\n以下と同じ、またはほぼ同じテーマの台本を作らないこと。\n\n");
            base.push_str(&title_lines(context.existing_titles));
        }
        base.push_str("\n\n構造化出力では、話者IDに次の対応を使う。\n");
        for speaker in speakers {
            base.push_str(&format!(
                "{}: {} / style_id={}\n",
                speaker.id,
                speaker.character_name,
                serde_json::to_string(&speaker.styles).map_err(|_| invalid())?
            ));
        }
    } else {
        if context.expansion_criteria.is_empty() {
            return Err(invalid());
        }
        let criteria = context
            .expansion_criteria
            .iter()
            .map(|line| format!("- {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        let analytics = context
            .analytics_tsv
            .filter(|value| !value.trim().is_empty())
            .map(str::trim)
            .map(str::to_owned)
            .unwrap_or_else(|| {
                format!(
                    "{}\n（実績データ未取得。実績根拠がない案は「新規開拓枠」と書く）",
                    include_str!("analytics_header.tsv").trim_end()
                )
            });
        base.push_str(&format!("\n\n━━━━━━━━━━━━━━━━━━\n実績データ・既存タイトル\n━━━━━━━━━━━━━━━━━━\n\n【実績データ（Analytics TSV）】\n{analytics}\n\n【横展開判定】\n{criteria}\n\n【既存タイトル重複禁止】\n{}\n",title_lines(context.existing_titles)));
        if kind == Kind::Meeting {
            base.push_str("実績は勝ちパターンではなく参考観察として扱い、新規開拓枠を主軸に、可能性がある構造は仮説強化枠として検討する。完全な既存重複は既存重複リスクとして示す。\n");
        }
    }
    Ok(PreparedPrompt {
        text: base,
        template: TemplateRef {
            id: template.id.clone(),
            version: version.version,
        },
        speakers: speakers.to_vec(),
    })
}

fn character_section(speakers: &[ActiveCharacter]) -> String {
    let mut blocks=vec!["━━━━━━━━━━━━━━━━━━".into(),"キャラクター設定（最優先・厳守）".into(),"━━━━━━━━━━━━━━━━━━".into(),
        "本チャンネルの登場キャラクターは以下に固定する。役割・口調・禁止表現・掛け合いを厳守する。".into(),
        "上の共通ルールや分量ルールにキャラ口調の指定があっても、本セクションを最優先する。".into()];
    for speaker in speakers {
        let mut lines = vec![format!(
            "### {}（{}）",
            speaker.character_name, speaker.display_name
        )];
        for (label, value, multiline) in [
            ("役割", &speaker.role, false),
            ("口調", &speaker.tone_style, false),
            ("話し方", &speaker.speaking_rules, true),
            ("禁止表現", &speaker.forbidden_phrases, false),
            ("掛け合いルール", &speaker.dialogue_rules, true),
        ] {
            if !value.is_empty() {
                lines.push(format!(
                    "- {label}:{}{value}",
                    if multiline { "\n" } else { " " }
                ));
            }
        }
        blocks.push(lines.join("\n"));
    }
    blocks.join("\n\n")
}

fn title_lines(titles: &[String]) -> String {
    if titles.is_empty() {
        "・既存タイトルなし".into()
    } else {
        titles
            .iter()
            .map(|title| format!("・{title}"))
            .collect::<Vec<_>>()
            .join("\n")
    }
}

fn envelope(body: &Value) -> Result<(&str, &Value)> {
    if body.as_object().is_none_or(|object| object.len() != 2) {
        return Err(invalid());
    }
    let format = body
        .get("format")
        .and_then(Value::as_str)
        .ok_or_else(invalid)?;
    let fields = body
        .get("fields")
        .filter(|value| value.is_object())
        .ok_or_else(invalid)?;
    Ok((format, fields))
}

fn enabled(fields: &Value, legacy: bool, key: &str) -> Result<bool> {
    match fields.get(key) {
        Some(Value::Bool(value)) if !legacy => Ok(*value),
        Some(Value::Number(value)) if legacy => match value.as_i64() {
            Some(0) => Ok(false),
            Some(1) => Ok(true),
            _ => Err(invalid()),
        },
        _ => Err(invalid()),
    }
}

fn text(fields: &Value, key: &str, required: bool) -> Result<String> {
    match fields.get(key) {
        Some(Value::String(value)) if !required || !value.trim().is_empty() => Ok(value.clone()),
        None | Some(Value::Null) if !required => Ok(String::new()),
        _ => Err(invalid()),
    }
}
