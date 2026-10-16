//! LLMの構造化出力。独自記法を生成の本番経路へ戻さない。

use crate::{
    invalid,
    prompt::{ActiveCharacter, TemplateRef},
};
use picocast_core::{clock::Timestamp, ChannelId, Result};
use picocast_store::{
    repository::{Line, Project, ProjectRevision, Scene},
    Store,
};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VideoFormat {
    Shorts,
    Long,
}
impl VideoFormat {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Shorts => "shorts",
            Self::Long => "long",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectDraft {
    pub format: VideoFormat,
    pub title: String,
    pub description: String,
    pub tags: Vec<String>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct Metadata {
    #[serde(deserialize_with = "nullable")]
    pub thumbnail_text: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub fixed_comment: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub generation_kind: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub source_video_title: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub generation_purpose: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub character_pattern: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub genre_group: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub topic_request_cta: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub topic_request_cta_reason: Option<String>,
    pub playlist_categories: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SceneDraft {
    pub id: String,
    pub background_prompt: String,
    pub mood: String,
    pub notes: String,
    pub telops: Vec<String>,
    pub lines: Vec<LineDraft>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LineDraft {
    pub id: String,
    pub speaker_id: String,
    pub text: String,
    #[serde(deserialize_with = "nullable")]
    pub reading_override: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub expression: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub style_id: Option<String>,
    pub pause_after_ms: i64,
}

fn nullable<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<String>, D::Error> {
    Option::<String>::deserialize(deserializer)
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct StructuredScript {
    pub project: ProjectDraft,
    pub scenes: Vec<SceneDraft>,
}

impl<'de> Deserialize<'de> for StructuredScript {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Fields {
            project: ProjectDraft,
            scenes: Vec<SceneDraft>,
        }
        let fields = Fields::deserialize(deserializer)?;
        let script = Self {
            project: fields.project,
            scenes: fields.scenes,
        };
        if !script.shape_is_valid() {
            return Err(serde::de::Error::custom(
                "台本の必須項目・識別子・並びが不正です",
            ));
        }
        Ok(script)
    }
}

#[derive(Debug, Clone)]
pub struct Limits {
    pub max_scenes: usize,
    pub max_lines: usize,
    pub max_line_chars: usize,
    pub max_pause_ms: i64,
}

impl Limits {
    pub fn validate(&self) -> Result<()> {
        if self.max_scenes == 0
            || self.max_lines == 0
            || self.max_line_chars == 0
            || self.max_pause_ms < 0
        {
            return Err(invalid());
        }
        Ok(())
    }
}

impl StructuredScript {
    fn shape_is_valid(&self) -> bool {
        if self.project.title.trim().is_empty()
            || self.scenes.is_empty()
            || self.project.tags.iter().any(|tag| tag.trim().is_empty())
        {
            return false;
        }
        let mut scenes = BTreeSet::new();
        let mut lines = BTreeSet::new();
        for scene in &self.scenes {
            if !logical_id(&scene.id)
                || !scenes.insert(&scene.id)
                || scene.background_prompt.trim().is_empty()
                || scene.lines.is_empty()
            {
                return false;
            }
            for line in &scene.lines {
                if !logical_id(&line.id)
                    || !lines.insert(&line.id)
                    || line.speaker_id.is_empty()
                    || line.text.trim().is_empty()
                    || line.pause_after_ms < 0
                {
                    return false;
                }
            }
        }
        true
    }

    pub fn validate(
        &self,
        channel: &ChannelId,
        speakers: &[ActiveCharacter],
        limits: &Limits,
    ) -> Result<()> {
        limits.validate()?;
        if !self.shape_is_valid()
            || self.scenes.len() > limits.max_scenes
            || self
                .scenes
                .iter()
                .map(|scene| scene.lines.len())
                .sum::<usize>()
                > limits.max_lines
        {
            return Err(invalid());
        }
        for line in self.scenes.iter().flat_map(|scene| &scene.lines) {
            let speaker = speakers
                .iter()
                .find(|speaker| speaker.id == line.speaker_id && &speaker.channel_id == channel)
                .ok_or_else(invalid)?;
            if line.text.chars().count() > limits.max_line_chars
                || line.pause_after_ms > limits.max_pause_ms
                || line
                    .style_id
                    .as_ref()
                    .is_some_and(|id| !speaker.styles.values().any(|style| style == id))
            {
                return Err(invalid());
            }
        }
        Ok(())
    }
}

fn logical_id(value: &str) -> bool {
    !value.is_empty()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}

pub struct SaveContext {
    pub project_id: String,
    pub revision: i64,
    pub language: String,
    pub synthetic_media: bool,
    pub publish_at: Option<Timestamp>,
    pub created_at: Timestamp,
    pub at: Timestamp,
    pub template: TemplateRef,
    pub provenance: Value,
    pub author: String,
    pub reason: String,
}

pub(crate) fn validate_save_context(
    store: &Store,
    channel: &ChannelId,
    context: &SaveContext,
) -> Result<Option<Project>> {
    if context.project_id.is_empty() || context.revision <= 0 || context.language.is_empty() {
        return Err(invalid());
    }
    let template = store
        .repository(channel)?
        .get::<picocast_store::repository::PromptTemplateVersion>(
            &picocast_store::repository::PromptTemplateVersionKey {
                channel_id: channel.clone(),
                template_id: context.template.id.clone(),
                version: context.template.version,
            },
        )?;
    if template.is_none() {
        return Err(invalid());
    }
    store.check_project_revision(channel, &context.project_id, context.revision)
}

pub fn save(
    store: &mut Store,
    channel: &ChannelId,
    script: &StructuredScript,
    speakers: &[ActiveCharacter],
    limits: &Limits,
    context: &SaveContext,
) -> Result<()> {
    script.validate(channel, speakers, limits)?;
    let previous = validate_save_context(store, channel, context)?;
    let mut project = Project {
        channel_id: channel.clone(),
        id: context.project_id.clone(),
        format: script.project.format.as_str().into(),
        language: context.language.clone(),
        status: "draft".into(),
        topic_id: None,
        title: script.project.title.clone(),
        description: script.project.description.clone(),
        tags_json: json!(script.project.tags),
        publish_at: context.publish_at.clone(),
        synthetic_media: context.synthetic_media,
        youtube_video_id: None,
        current_revision: context.revision,
        created_at: context.created_at.clone(),
        updated_at: context.at.clone(),
    };
    if let Some(previous) = previous {
        project.status = previous.status;
        project.topic_id = previous.topic_id;
        project.publish_at = previous.publish_at;
        project.youtube_video_id = previous.youtube_video_id;
        project.created_at = previous.created_at;
        project.synthetic_media |= previous.synthetic_media;
    }
    let revision = ProjectRevision {
        channel_id: channel.clone(),
        project_id: context.project_id.clone(),
        revision: context.revision,
        snapshot_json: json!({"format":"structured-script-v1","script":script,"template":context.template,"provenance":context.provenance}),
        author: context.author.clone(),
        reason: context.reason.clone(),
        created_at: context.at.clone(),
    };
    let (previous_scenes, previous_lines) = store.project_graph(channel, &context.project_id)?;
    let mut scenes = Vec::new();
    let mut lines = Vec::new();
    for (scene_order, scene) in script.scenes.iter().enumerate() {
        let id = format!("{}/scenes/{}", context.project_id, scene.id);
        let mut stored_scene = Scene {
            channel_id: channel.clone(),
            id: id.clone(),
            project_id: context.project_id.clone(),
            ord: i64::try_from(scene_order).map_err(|_| invalid())?,
            background_sha256: None,
            background_prompt: Some(scene.background_prompt.clone()),
            camera_json: json!({}),
            mood: scene.mood.clone(),
            notes: scene.notes.clone(),
        };
        if let Some(previous) = previous_scenes
            .iter()
            .find(|previous| previous.id == id && previous.project_id == context.project_id)
        {
            stored_scene.camera_json = previous.camera_json.clone();
            if previous.background_prompt == stored_scene.background_prompt {
                stored_scene.background_sha256 = previous.background_sha256.clone();
            }
        }
        scenes.push(stored_scene);
        for (line_order, line) in scene.lines.iter().enumerate() {
            let mut stored_line = Line {
                channel_id: channel.clone(),
                id: format!("{}/lines/{}", context.project_id, line.id),
                scene_id: id.clone(),
                ord: i64::try_from(line_order).map_err(|_| invalid())?,
                speaker_id: line.speaker_id.clone(),
                text: line.text.clone(),
                reading_override: line.reading_override.clone(),
                accent_json: Value::Null,
                expression: line.expression.clone(),
                style_id: line.style_id.clone(),
                emphasis_json: json!({}),
                pause_after_ms: line.pause_after_ms,
            };
            if let Some(previous) = previous_lines.iter().find(|previous| {
                previous.id == stored_line.id
                    && previous.text == line.text
                    && previous.speaker_id == line.speaker_id
            }) {
                if previous.reading_override == stored_line.reading_override {
                    stored_line.accent_json = previous.accent_json.clone();
                }
                stored_line.emphasis_json = previous.emphasis_json.clone();
            }
            lines.push(stored_line);
        }
    }
    store.save_project_revision(channel, &project, &revision, &scenes, &lines)
}

/// Gatewayへ渡すJSON schema。同じ型の既定値や別のプロバイダ用schemaを増やさない。
pub fn schema(speakers: &[ActiveCharacter], limits: &Limits) -> Result<Value> {
    limits.validate()?;
    if speakers.is_empty() {
        return Err(invalid());
    }
    let nullable = json!({"type":["string","null"]});
    let line = json!({"type":"object","additionalProperties":false,"required":["id","speaker_id","text","reading_override","expression","style_id","pause_after_ms"],
        "properties":{"id":{"type":"string","pattern":"^[A-Za-z0-9_-]+$"},"speaker_id":{"type":"string","enum":speakers.iter().map(|speaker|speaker.id.clone()).collect::<Vec<_>>()},
            "text":{"type":"string","minLength":1,"maxLength":limits.max_line_chars},"reading_override":nullable,"expression":nullable,"style_id":nullable,
            "pause_after_ms":{"type":"integer","minimum":0,"maximum":limits.max_pause_ms}}});
    let scene = json!({"type":"object","additionalProperties":false,"required":["id","background_prompt","mood","notes","telops","lines"],
        "properties":{"id":{"type":"string","pattern":"^[A-Za-z0-9_-]+$"},"background_prompt":{"type":"string","minLength":1},"mood":{"type":"string"},"notes":{"type":"string"},
            "telops":{"type":"array","items":{"type":"string"}},"lines":{"type":"array","minItems":1,"maxItems":limits.max_lines,"items":line}}});
    let metadata = json!({"type":"object","additionalProperties":false,"required":["thumbnail_text","fixed_comment","generation_kind","source_video_title","generation_purpose","character_pattern","genre_group","topic_request_cta","topic_request_cta_reason","playlist_categories"],
        "properties":{"thumbnail_text":nullable,"fixed_comment":nullable,"generation_kind":nullable,"source_video_title":nullable,"generation_purpose":nullable,"character_pattern":nullable,"genre_group":nullable,
            "topic_request_cta":nullable,"topic_request_cta_reason":nullable,"playlist_categories":{"type":"array","items":{"type":"string"}}}});
    Ok(
        json!({"type":"object","additionalProperties":false,"required":["project","scenes"],"properties":{
        "project":{"type":"object","additionalProperties":false,"required":["format","title","description","tags","metadata"],"properties":{
            "format":{"type":"string","enum":["shorts","long"]},"title":{"type":"string","minLength":1},"description":{"type":"string"},"tags":{"type":"array","items":{"type":"string","minLength":1}},"metadata":metadata}},
        "scenes":{"type":"array","minItems":1,"maxItems":limits.max_scenes,"items":scene}}}),
    )
}
