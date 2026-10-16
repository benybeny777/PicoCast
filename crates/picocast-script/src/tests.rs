#![cfg(test)]
#![cfg(test)]
#![allow(clippy::unwrap_used)]
use crate::{
    document::*,
    prompt::{self, Kind, PromptContext, TemplateRef},
};
use picocast_core::{clock::Timestamp, ChannelId};
use picocast_store::{repository::*, DataMode, Store, StoreOptions, StorePaths};
use serde_json::json;
use std::time::Duration;

struct Fixture {
    _directory: tempfile::TempDir,
    store: Store,
    channel: ChannelId,
}
impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(&directory.path().join("data"), DataMode::Development).unwrap();
        let store = Store::open(
            &paths,
            StoreOptions {
                busy_timeout: Duration::from_secs(1),
                backup_pages_per_step: 8,
                backup_pause: Duration::from_millis(1),
            },
        )
        .unwrap();
        let channel = ChannelId::new("fixture").unwrap();
        store.create_channel(&channel, "合成fixture").unwrap();
        let mut fixture = Self {
            _directory: directory,
            store,
            channel,
        };
        fixture.template(1, 1);
        fixture.store.repository(&fixture.channel).unwrap().save(&Character{channel_id:fixture.channel.clone(),id:"speaker".into(),name:"キャラクター".into(),voice_provider:"voicevox".into(),speaker_id:"1".into(),style_map_json:json!({"ノーマル":1}),credit_text:"合成用".into(),layer_manifest_sha256:None,
            usage_rules_json:json!({"format":"legacy-character-v1","fields":{"profile_id":"fixture","enabled":1,"character_name":"ずんだもん","sort_order":0,"role":"説明","tone_style":"具体的","speaking_rules":"なのだ","forbidden_phrases":"復唱","dialogue_rules":"疑問を説明する"}})}).unwrap();
        fixture
    }
    fn template(&mut self, version: i64, enabled: i64) {
        let repository = self.store.repository(&self.channel).unwrap();
        repository
            .save(&PromptTemplate {
                channel_id: self.channel.clone(),
                id: "script".into(),
                kind: "script".into(),
                name: "fixture".into(),
                is_default: true,
            })
            .unwrap();
        repository.save(&PromptTemplateVersion{channel_id:self.channel.clone(),template_id:"script".into(),version,body:json!({"format":"legacy-template-v1","fields":{"profile_id":"fixture","is_enabled":enabled,"system_rules":"資料を説明","script_rules":"場面別","ng_rules":"推測しない"}}).to_string(),created_at:at(),author:"fixture".into(),reason:"検証".into()}).unwrap();
    }
    fn save(&mut self, script: &StructuredScript, revision: i64) -> picocast_core::Result<()> {
        let speakers = prompt::active_characters(&self.store, &self.channel)?;
        save(
            &mut self.store,
            &self.channel,
            script,
            &speakers,
            &limits(),
            &SaveContext {
                project_id: "project".into(),
                revision,
                language: "ja".into(),
                synthetic_media: true,
                publish_at: None,
                created_at: at(),
                at: at(),
                template: TemplateRef {
                    id: "script".into(),
                    version: 1,
                },
                provenance: json!({"fixture":true}),
                author: "user".into(),
                reason: "検証".into(),
            },
        )
    }
    fn project(&self) -> Project {
        self.store
            .repository(&self.channel)
            .unwrap()
            .get::<Project>(&ProjectKey {
                channel_id: self.channel.clone(),
                id: "project".into(),
            })
            .unwrap()
            .unwrap()
    }
}
fn at() -> Timestamp {
    Timestamp::parse("2026-01-01T00:00:00Z").unwrap()
}
fn limits() -> Limits {
    Limits {
        max_scenes: 3,
        max_lines: 5,
        max_line_chars: 100,
        max_pause_ms: 1000,
    }
}
fn script() -> StructuredScript {
    StructuredScript {
        project: ProjectDraft {
            format: VideoFormat::Long,
            title: "根拠を説明".into(),
            description: "資料".into(),
            tags: vec!["合成".into()],
            metadata: Metadata::default(),
        },
        scenes: vec![SceneDraft {
            id: "scene".into(),
            background_prompt: "図書館".into(),
            mood: "通常".into(),
            notes: String::new(),
            telops: vec!["具体的な根拠".into()],
            lines: vec![LineDraft {
                id: "line".into(),
                speaker_id: "speaker".into(),
                text: "資料には具体的な理由があるのだ。".into(),
                reading_override: None,
                expression: None,
                style_id: Some("1".into()),
                pause_after_ms: 0,
            }],
        }],
    }
}

#[test]
fn consumes_only_enabled_latest_db_template_and_same_channel_speakers() {
    let mut fixture = Fixture::new();
    let context = PromptContext {
        existing_titles: &[],
        analytics_tsv: None,
        expansion_criteria: &[],
    };
    let prompt = prompt::build(&fixture.store, &fixture.channel, Kind::Script, &context).unwrap();
    assert!(prompt.text.contains(crate::DIALOGUE_RULES));
    assert!(prompt.text.contains("speaker: ずんだもん"));
    fixture.template(2, 0);
    assert!(prompt::build(&fixture.store, &fixture.channel, Kind::Script, &context).is_err());
    let other = ChannelId::new("other").unwrap();
    fixture.store.create_channel(&other, "別").unwrap();
    assert!(prompt::build(&fixture.store, &other, Kind::Script, &context).is_err());
}

#[test]
fn title_and_meeting_use_db_versions_without_requiring_script_characters() {
    let fixture = Fixture::new();
    let channel = ChannelId::new("no-characters").unwrap();
    fixture
        .store
        .create_channel(&channel, "未登録話者")
        .unwrap();
    for (kind, section) in [(Kind::Title, "題名"), (Kind::Meeting, "会議")] {
        let template = PromptTemplate {
            channel_id: channel.clone(),
            id: kind.as_str().into(),
            kind: kind.as_str().into(),
            name: section.into(),
            is_default: true,
        };
        fixture
            .store
            .repository(&channel)
            .unwrap()
            .save(&template)
            .unwrap();
        fixture.store.repository(&channel).unwrap().save(&PromptTemplateVersion{channel_id:channel.clone(),template_id:template.id.clone(),version:1,
            body:json!({"format":"legacy-template-v1","fields":{"profile_id":channel.as_str(),"is_enabled":1,"system_rules":section,"meeting_rules":"候補を比較","ng_rules":"推測しない"}}).to_string(),created_at:at(),author:"user".into(),reason:"合成".into()}).unwrap();
        let criteria = vec!["判定は設定から明示".into()];
        let titles = vec!["既存テーマ".into()];
        let prompt = prompt::build(
            &fixture.store,
            &channel,
            kind,
            &PromptContext {
                existing_titles: &titles,
                analytics_tsv: None,
                expansion_criteria: &criteria,
            },
        )
        .unwrap();
        assert!(prompt.text.contains("実績データ未取得"));
        assert!(prompt.text.contains("既存テーマ"));
        assert!(prompt.text.contains("判定は設定から明示"));
        assert!(prompt.speakers.is_empty());
    }
}

#[test]
fn rejects_unknown_fields_speakers_styles_and_limits() {
    let fixture = Fixture::new();
    let speakers = prompt::active_characters(&fixture.store, &fixture.channel).unwrap();
    let mut value = serde_json::to_value(script()).unwrap();
    value["scenes"][0]["lines"][0]["unexpected"] = json!(true);
    assert!(serde_json::from_value::<StructuredScript>(value).is_err());
    let mut value = serde_json::to_value(script()).unwrap();
    value["scenes"][0]["lines"][0]
        .as_object_mut()
        .unwrap()
        .remove("expression");
    assert!(serde_json::from_value::<StructuredScript>(value).is_err());
    let mut invalid = script();
    invalid.scenes[0].lines[0].style_id = Some("999".into());
    assert!(invalid
        .validate(&fixture.channel, &speakers, &limits())
        .is_err());
    invalid.scenes[0].lines[0].style_id = None;
    invalid.scenes[0].lines[0].speaker_id = "missing".into();
    assert!(invalid
        .validate(&fixture.channel, &speakers, &limits())
        .is_err());
    invalid = script();
    let duplicate = invalid.scenes[0].lines[0].clone();
    invalid.scenes[0].lines.push(duplicate);
    assert!(invalid
        .validate(&fixture.channel, &speakers, &limits())
        .is_err());
}

#[test]
fn atomic_versions_retain_refs_and_reject_stale_updates() {
    let mut fixture = Fixture::new();
    let mut draft = script();
    fixture.save(&draft, 1).unwrap();
    let hash = "a".repeat(64);
    fixture
        .store
        .global_repository()
        .save(&Asset {
            sha256: hash.clone(),
            kind: "audio".into(),
            ext: "wav".into(),
            bytes: 1,
            created_at: at(),
            provenance_json: json!({}),
        })
        .unwrap();
    fixture
        .store
        .repository(&fixture.channel)
        .unwrap()
        .save(&AssetRef {
            channel_id: fixture.channel.clone(),
            owner_kind: "line".into(),
            owner_id: "project/lines/line".into(),
            sha256: hash,
            role: "audio".into(),
        })
        .unwrap();
    let second = LineDraft {
        id: "second".into(),
        ..draft.scenes[0].lines[0].clone()
    };
    draft.scenes[0].lines.push(second);
    fixture.save(&draft, 2).unwrap();
    draft.scenes[0].lines.swap(0, 1);
    fixture.save(&draft, 3).unwrap();
    assert_eq!(
        fixture
            .store
            .repository(&fixture.channel)
            .unwrap()
            .list::<AssetRef>()
            .unwrap()
            .len(),
        1
    );
    assert!(fixture.save(&draft, 3).is_err());
    assert_eq!(fixture.project().current_revision, 3);
    let mut changed = draft.clone();
    changed.scenes[0].lines[1].text = "古い音声と一致しない変更".into();
    assert_eq!(
        fixture.save(&changed, 4).unwrap_err().code,
        "E-STORE-IDENTITY"
    );
    assert_eq!(fixture.project().current_revision, 3);
    let retained = fixture
        .store
        .repository(&fixture.channel)
        .unwrap()
        .list::<Line>()
        .unwrap();
    assert!(retained.iter().any(
        |line| line.id == "project/lines/line" && line.text == script().scenes[0].lines[0].text
    ));
    draft.scenes[0].lines.retain(|line| line.id != "line");
    assert!(fixture.save(&draft, 4).is_err());
    assert_eq!(fixture.project().current_revision, 3);
    assert_eq!(
        fixture
            .store
            .repository(&fixture.channel)
            .unwrap()
            .list::<ProjectRevision>()
            .unwrap()
            .len(),
        3
    );
    assert_eq!(
        fixture
            .store
            .repository(&fixture.channel)
            .unwrap()
            .list::<Line>()
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn store_rejects_foreign_graph_ids_and_rolls_back_missing_speaker() {
    let mut fixture = Fixture::new();
    fixture.save(&script(), 1).unwrap();
    let repository = fixture.store.repository(&fixture.channel).unwrap();
    let scenes = repository.list::<Scene>().unwrap();
    let mut lines = repository.list::<Line>().unwrap();
    let mut project = fixture.project();
    let mut revision = repository.list::<ProjectRevision>().unwrap().remove(0);
    project.current_revision = 2;
    revision.revision = 2;
    lines[0].speaker_id = "absent".into();
    assert!(fixture
        .store
        .save_project_revision(&fixture.channel, &project, &revision, &scenes, &lines)
        .is_err());
    assert_eq!(fixture.project().current_revision, 1);
    project.id = "other-project".into();
    project.current_revision = 1;
    revision.project_id = project.id.clone();
    revision.revision = 1;
    let mut stolen = scenes.clone();
    stolen[0].project_id = project.id.clone();
    lines[0].speaker_id = "speaker".into();
    assert!(fixture
        .store
        .save_project_revision(&fixture.channel, &project, &revision, &stolen, &lines)
        .is_err());
    let mut duplicates = scenes.clone();
    duplicates.push(scenes[0].clone());
    project = fixture.project();
    project.current_revision = 2;
    revision.project_id = project.id.clone();
    revision.revision = 2;
    assert!(fixture
        .store
        .save_project_revision(&fixture.channel, &project, &revision, &duplicates, &lines)
        .is_err());
    assert_eq!(fixture.project().current_revision, 1);
}

#[tokio::test]
async fn fake_gateway_retries_invalid_style_once_then_saves_strict_graph() {
    use picocast_ai::*;
    let mut fixture = Fixture::new();
    let mut invalid = script();
    invalid.scenes[0].lines[0].style_id = Some("missing".into());
    let responses = [invalid, script()]
        .into_iter()
        .map(|script| {
            Ok(Completion {
                text: serde_json::to_string(&script).unwrap(),
                usage: Usage {
                    input_tokens: 5,
                    output_tokens: 15,
                },
            })
        })
        .collect();
    let mut gateway = fake_gateway(&fixture.channel, responses);
    let (_handle, mut cancel) = Cancellation::pair();
    let result = crate::generation::generate_and_save(
        &mut gateway,
        &mut fixture.store,
        &fixture.channel,
        &PromptContext {
            existing_titles: &[],
            analytics_tsv: None,
            expansion_criteria: &[],
        },
        &limits(),
        generation_request(1),
        &mut cancel,
    )
    .await
    .unwrap();
    assert_eq!(result.value, script());
    assert_eq!(fixture.project().current_revision, 1);
    assert_eq!(
        fixture
            .store
            .repository(&fixture.channel)
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .len(),
        2
    );
    let revision = fixture
        .store
        .repository(&fixture.channel)
        .unwrap()
        .list::<ProjectRevision>()
        .unwrap()
        .remove(0);
    assert_eq!(revision.snapshot_json["template"]["id"], "script");
    assert_eq!(
        revision.snapshot_json["provenance"]["model"],
        "fixture-model"
    );
}

#[test]
fn legacy_raw_revision_becomes_graph_without_losing_original_or_extra_metadata() {
    let mut fixture = Fixture::new();
    fixture.save(&script(), 1).unwrap();
    let raw="動画形式: Shorts\n動画タイトル: 旧原文\n背景: 図書館\nずんだもん(ノーマル)[驚き]: 資料を説明するのだ。\nサムネイル: 旧プロンプト\n固定コメント: どの資料？";
    let mut project = fixture.project();
    project.current_revision = 2;
    fixture
        .store
        .repository(&fixture.channel)
        .unwrap()
        .save(&project)
        .unwrap();
    fixture.store.repository(&fixture.channel).unwrap().save(&ProjectRevision{channel_id:fixture.channel.clone(),project_id:"project".into(),revision:2,snapshot_json:json!({"kind":"legacy_metadata","script_content":raw,"video":{"source":"preserved"}}),author:"import".into(),reason:"旧原文".into(),created_at:at()}).unwrap();
    let context = SaveContext {
        project_id: "project".into(),
        revision: 3,
        language: "ja".into(),
        synthetic_media: true,
        publish_at: None,
        created_at: at(),
        at: at(),
        template: TemplateRef {
            id: "script".into(),
            version: 1,
        },
        provenance: json!({}),
        author: "import".into(),
        reason: "構造化".into(),
    };
    let parsed = crate::compatibility::import_revision(
        &mut fixture.store,
        &fixture.channel,
        2,
        &crate::legacy::ParserOptions {
            characters: vec![("ずんだもん".into(), "ずんだもん".into())],
            unknown_character: None,
        },
        &crate::compatibility::ImportOptions {
            format: VideoFormat::Long,
            title: "明示既定".into(),
            initial_background: None,
            pause_after_ms: 0,
        },
        &limits(),
        &context,
    )
    .unwrap();
    assert_eq!(parsed.project.format, VideoFormat::Shorts);
    assert_eq!(
        parsed.scenes[0].lines[0].expression.as_deref(),
        Some("驚き")
    );
    assert_eq!(fixture.project().current_revision, 3);
    let revisions = fixture
        .store
        .repository(&fixture.channel)
        .unwrap()
        .list::<ProjectRevision>()
        .unwrap();
    assert_eq!(revisions[1].snapshot_json["script_content"], raw);
    assert_eq!(
        revisions[2].snapshot_json["provenance"]["source_snapshot"]["script_content"],
        raw
    );
    assert!(revisions[2].snapshot_json["provenance"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .any(|item| item["type"] == "thumbnail"));
}

fn fake_gateway(
    channel: &ChannelId,
    responses: Vec<picocast_ai::ProviderResult<picocast_ai::Completion>>,
) -> picocast_ai::Gateway {
    use picocast_ai::*;
    use picocast_testkit::FakeProvider;
    use std::collections::BTreeMap;
    let provider = FakeProvider::new(channel.clone(), vec!["fixture-model".into()], responses);
    Gateway::new(
        channel.clone(),
        ModelRegistry {
            stages: BTreeMap::from([(
                Stage::Script,
                StageModel {
                    provider: ProviderId::Fake,
                    model: "fixture-model".into(),
                    max_input_tokens: 10000,
                    max_output_tokens: 1000,
                    input_micros_per_million: 0,
                    output_micros_per_million: 0,
                },
            )]),
        },
        GatewayOptions {
            max_attempts: 1,
            request_timeout: Duration::from_secs(1),
            retry_base: Duration::from_millis(1),
            retry_max: Duration::from_millis(1),
            daily_budget_micros: 1000,
            daily_token_budget: 100000,
            max_prompt_bytes: 100000,
            development: true,
            allow_paid: false,
        },
        vec![Box::new(provider)],
        Box::new(NoCache),
    )
    .unwrap()
}

fn generation_request(revision: i64) -> crate::generation::RequestContext {
    crate::generation::RequestContext {
        request_id: "script-fixture".into(),
        job_id: None,
        settings_hash: "fixture".into(),
        topic: "資料を説明".into(),
        save: SaveContext {
            project_id: "project".into(),
            revision,
            language: "ja".into(),
            synthetic_media: true,
            publish_at: None,
            created_at: at(),
            at: at(),
            template: TemplateRef {
                id: "replaced-by-db".into(),
                version: 1,
            },
            provenance: json!({}),
            author: "ai".into(),
            reason: "合成応答".into(),
        },
    }
}

#[tokio::test]
async fn invalid_save_revision_or_language_stops_before_generation_and_cost_reservation() {
    use picocast_ai::Cancellation;
    for (existing, revision, language) in [(false, 2, "ja"), (true, 1, "ja"), (false, 1, "")] {
        let mut fixture = Fixture::new();
        if existing {
            fixture.save(&script(), 1).unwrap();
        }
        let mut gateway = fake_gateway(&fixture.channel, vec![]);
        let mut request = generation_request(revision);
        request.save.language = language.into();
        let (_handle, mut cancel) = Cancellation::pair();
        let error = crate::generation::generate_and_save(
            &mut gateway,
            &mut fixture.store,
            &fixture.channel,
            &PromptContext {
                existing_titles: &[],
                analytics_tsv: None,
                expansion_criteria: &[],
            },
            &limits(),
            request,
            &mut cancel,
        )
        .await
        .err()
        .unwrap();
        assert_eq!(
            error.code,
            if language.is_empty() {
                "E-SCRIPT-FORMAT"
            } else {
                "E-STORE-IDENTITY"
            }
        );
        assert!(fixture
            .store
            .repository(&fixture.channel)
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .is_empty());
        if existing {
            assert_eq!(fixture.project().current_revision, 1);
        }
    }
}

#[tokio::test]
async fn archived_channel_never_calls_model_listing_or_cache() {
    use picocast_ai::{
        FutureResult, LlmProvider, Operation, ProviderId, ProviderOutput, ProviderResult,
    };
    struct CountingProvider {
        channel: ChannelId,
        calls: std::rc::Rc<std::cell::Cell<usize>>,
    }
    impl LlmProvider for CountingProvider {
        fn channel_id(&self) -> &ChannelId {
            &self.channel
        }
        fn id(&self) -> ProviderId {
            ProviderId::Fake
        }
        fn call<'a>(
            &'a mut self,
            _operation: Operation<'a>,
        ) -> FutureResult<'a, ProviderResult<ProviderOutput>> {
            self.calls.set(self.calls.get() + 1);
            Box::pin(async { Ok(ProviderOutput::Models(vec!["fixture-model".into()])) })
        }
    }
    let mut fixture = Fixture::new();
    let calls = std::rc::Rc::new(std::cell::Cell::new(0));
    let mut settings = picocast_ai::ModelRegistry {
        stages: std::collections::BTreeMap::new(),
    };
    settings.stages.insert(
        picocast_ai::Stage::Title,
        picocast_ai::StageModel {
            provider: ProviderId::Fake,
            model: "fixture-model".into(),
            max_input_tokens: 100,
            max_output_tokens: 100,
            input_micros_per_million: 0,
            output_micros_per_million: 0,
        },
    );
    let mut gateway = picocast_ai::Gateway::new(
        fixture.channel.clone(),
        settings,
        picocast_ai::GatewayOptions {
            max_attempts: 1,
            request_timeout: Duration::from_secs(1),
            retry_base: Duration::from_millis(1),
            retry_max: Duration::from_millis(1),
            daily_budget_micros: 0,
            daily_token_budget: 1000,
            max_prompt_bytes: 1000,
            development: true,
            allow_paid: false,
        },
        vec![Box::new(CountingProvider {
            channel: fixture.channel.clone(),
            calls: calls.clone(),
        })],
        Box::new(picocast_ai::NoCache),
    )
    .unwrap();
    let repository = fixture.store.repository(&fixture.channel).unwrap();
    let mut channel = repository
        .get::<Channel>(&ChannelKey {
            channel_id: fixture.channel.clone(),
        })
        .unwrap()
        .unwrap();
    channel.archived_at = Some(at());
    repository.save(&channel).unwrap();
    let (_handle, mut cancel) = picocast_ai::Cancellation::pair();
    let result = gateway
        .generate_json::<serde_json::Value>(
            &mut fixture.store,
            picocast_ai::GenerateRequest {
                channel_id: fixture.channel.clone(),
                request_id: "archived".into(),
                project_id: None,
                job_id: None,
                stage: picocast_ai::Stage::Title,
                prompt: "架空".into(),
                template_version: 1,
                settings_hash: "fixture".into(),
            },
            &json!({"type":"object"}),
            &mut cancel,
        )
        .await;
    assert_eq!(result.err().unwrap().code, "E-STORE-CHANNEL");
    assert_eq!(calls.get(), 0);
}
