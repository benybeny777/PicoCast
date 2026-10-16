//! 旧記法からの明示的な変換。原文は元revisionと来歴へ残す。
use crate::{
    document::{
        self, Limits, LineDraft, Metadata, ProjectDraft, SaveContext, SceneDraft, StructuredScript,
        VideoFormat,
    },
    invalid,
    legacy::{self, Item, ParserOptions},
    prompt::{self, ActiveCharacter},
};
use picocast_core::{ChannelId, Result};
use picocast_store::{
    repository::{ProjectRevision, ProjectRevisionKey},
    Store,
};
use serde_json::json;

/// ヘッダにない情報と旧版の未指定pauseは呼出側が明示する。
pub struct ImportOptions {
    pub format: VideoFormat,
    pub title: String,
    pub initial_background: Option<String>,
    pub pause_after_ms: i64,
}

pub fn convert(
    items: &[Item],
    speakers: &[ActiveCharacter],
    options: &ImportOptions,
) -> Result<StructuredScript> {
    let mut project = ProjectDraft {
        format: options.format.clone(),
        title: options.title.clone(),
        description: String::new(),
        tags: Vec::new(),
        metadata: Metadata::default(),
    };
    let mut scenes: Vec<SceneDraft> = Vec::new();
    let mut next_line = 0;
    for item in items {
        match item.kind.as_str() {
            "video_format" => {
                project.format = match item.text.to_lowercase().as_str() {
                    "shorts" => VideoFormat::Shorts,
                    "long" => VideoFormat::Long,
                    _ => return Err(invalid()),
                };
            }
            "video_title" => project.title = item.text.clone(),
            "description" => project.description = item.text.clone(),
            "tags" => {
                project.tags = item
                    .text
                    .split([',', '、'])
                    .map(str::trim)
                    .filter(|text| !text.is_empty())
                    .map(str::to_owned)
                    .collect()
            }
            "thumbnail_text" => project.metadata.thumbnail_text = Some(item.text.clone()),
            "fixed_comment" => project.metadata.fixed_comment = Some(item.text.clone()),
            "generation_kind" => project.metadata.generation_kind = Some(item.text.clone()),
            "source_video_title" => project.metadata.source_video_title = Some(item.text.clone()),
            "generation_purpose" => project.metadata.generation_purpose = Some(item.text.clone()),
            "character_pattern" => project.metadata.character_pattern = Some(item.text.clone()),
            "genre_group" => project.metadata.genre_group = Some(item.text.clone()),
            "topic_request_cta" => project.metadata.topic_request_cta = Some(item.text.clone()),
            "topic_request_cta_reason" => {
                project.metadata.topic_request_cta_reason = Some(item.text.clone())
            }
            "playlist_categories" => {
                project.metadata.playlist_categories = item
                    .text
                    .split([',', '、'])
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .map(str::to_owned)
                    .collect()
            }
            "background" => scenes.push(scene(scenes.len(), &item.text)),
            "telop" => scenes
                .last_mut()
                .ok_or_else(invalid)?
                .telops
                .push(item.text.clone()),
            "dialogue" => {
                if scenes.is_empty() {
                    scenes.push(scene(
                        0,
                        options.initial_background.as_deref().ok_or_else(invalid)?,
                    ));
                }
                let dialogue = item.dialogue.as_ref().ok_or_else(invalid)?;
                let speaker = speakers
                    .iter()
                    .find(|speaker| speaker.character_name == dialogue.character)
                    .ok_or_else(invalid)?;
                let style = speaker
                    .styles
                    .get(&dialogue.emotion)
                    .ok_or_else(invalid)?
                    .clone();
                scenes
                    .last_mut()
                    .ok_or_else(invalid)?
                    .lines
                    .push(LineDraft {
                        id: format!("line-{next_line}"),
                        speaker_id: speaker.id.clone(),
                        text: item.text.clone(),
                        reading_override: None,
                        expression: dialogue.expression.clone(),
                        style_id: Some(style),
                        pause_after_ms: options.pause_after_ms,
                    });
                next_line += 1;
            }
            // 専用列がないメタも消さずimport_revisionの原文・全Itemで保護する。
            kind if legacy::is_meta(kind) => {}
            _ => return Err(invalid()),
        }
    }
    Ok(StructuredScript { project, scenes })
}
fn scene(index: usize, background: &str) -> SceneDraft {
    SceneDraft {
        id: format!("scene-{index}"),
        background_prompt: background.into(),
        mood: String::new(),
        notes: String::new(),
        telops: Vec::new(),
        lines: Vec::new(),
    }
}

pub fn import_revision(
    store: &mut Store,
    channel: &ChannelId,
    source_revision: i64,
    parser: &ParserOptions,
    options: &ImportOptions,
    limits: &Limits,
    context: &SaveContext,
) -> Result<StructuredScript> {
    let source = store
        .repository(channel)?
        .get::<ProjectRevision>(&ProjectRevisionKey {
            channel_id: channel.clone(),
            project_id: context.project_id.clone(),
            revision: source_revision,
        })?
        .ok_or_else(invalid)?;
    if source
        .snapshot_json
        .get("kind")
        .and_then(|value| value.as_str())
        != Some("legacy_metadata")
        || context.revision != source_revision.checked_add(1).ok_or_else(invalid)?
    {
        return Err(invalid());
    }
    let raw = source
        .snapshot_json
        .get("script_content")
        .and_then(|value| value.as_str())
        .ok_or_else(invalid)?;
    let items = legacy::parse(raw, parser)?;
    let speakers = prompt::active_characters(store, channel)?;
    let script = convert(&items, &speakers, options)?;
    let context = SaveContext {
        project_id: context.project_id.clone(),
        revision: context.revision,
        language: context.language.clone(),
        synthetic_media: context.synthetic_media,
        publish_at: context.publish_at.clone(),
        created_at: context.created_at.clone(),
        at: context.at.clone(),
        template: context.template.clone(),
        provenance: json!({"kind":"legacy-script-import","source_revision":source_revision,"source_snapshot":source.snapshot_json,"items":items,"conversion":context.provenance}),
        author: "import".into(),
        reason: context.reason.clone(),
    };
    document::save(store, channel, &script, &speakers, limits, &context)?;
    Ok(script)
}
