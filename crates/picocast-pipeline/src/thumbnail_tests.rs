#![cfg(test)]
#![cfg(windows)]
#![allow(clippy::unwrap_used, clippy::panic)]
use super::*;
use picocast_ai::{
    image::{Assessment, ImageCompletion, ImageOptions, Originality, SeedPolicy},
    image_fake::{FakeImageInspector, FakeImageProvider},
    Completion, GatewayOptions, ModelRegistry, NoCache, ProviderId, StageModel, Usage,
};
use picocast_core::clock::Timestamp;
use picocast_media::subtitle::FontSource;
use picocast_store::{
    repository::{CostLedger, PromptTemplate, PromptTemplateVersion},
    DataMode, StoreOptions, StorePaths,
};
use picocast_testkit::FakeProvider;
use std::{collections::BTreeMap, time::Duration};

#[derive(Clone, Copy, PartialEq, Eq)]
enum FixtureCase {
    Ready,
    Unreadable,
    WrongText,
    Cancelled,
}

async fn run(case: FixtureCase) -> Result<ThumbnailOutcome> {
    let dir = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(dir.path(), DataMode::Development).unwrap();
    let mut store = Store::open(
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
    let repo = store.repository(&channel).unwrap();
    repo.save(&PromptTemplate {
        channel_id: channel.clone(),
        id: "title".into(),
        kind: "title".into(),
        name: "合成用".into(),
        is_default: true,
    })
    .unwrap();
    repo.save(&PromptTemplateVersion{channel_id:channel.clone(),template_id:"title".into(),version:1,
        body:json!({"format":"template-v1","fields":{"is_enabled":true,"system_rules":"事実を短く","ng_rules":"誇張禁止"}}).to_string(),
        created_at:Timestamp::parse("2026-10-16T00:00:00Z").unwrap(),author:"fixture".into(),reason:"検査".into()}).unwrap();
    let teasers = ["月の秘密", "太陽の仕組み", "星のひみつ"];
    let title = json!({"candidates":teasers.map(|text| json!({"text":text,"background_prompt":"原創の宇宙背景、文字なし","evidence":"月と太陽と星"}))});
    let mut responses = vec![title];
    responses.extend(teasers.map(|text| json!({"readable":case!=FixtureCase::Unreadable,"transcribed_text":if case==FixtureCase::WrongText {"別の文字"} else {text},"factual":true,"appropriate":true,"uncertain":false})));
    let provider = FakeProvider::new(
        channel.clone(),
        vec!["fixture".into()],
        responses
            .into_iter()
            .map(|value| {
                Ok(Completion {
                    text: value.to_string(),
                    usage: Usage {
                        input_tokens: 100,
                        output_tokens: 100,
                    },
                })
            })
            .collect(),
    );
    let model = StageModel {
        provider: ProviderId::Fake,
        model: "fixture".into(),
        max_input_tokens: 10000,
        max_output_tokens: 10000,
        input_micros_per_million: 0,
        output_micros_per_million: 0,
    };
    let mut gateway = Gateway::new(
        channel.clone(),
        ModelRegistry {
            stages: BTreeMap::from([(Stage::Title, model.clone()), (Stage::Review, model)]),
        },
        GatewayOptions {
            max_attempts: 1,
            request_timeout: Duration::from_secs(1),
            retry_base: Duration::from_millis(1),
            retry_max: Duration::from_millis(1),
            daily_budget_micros: 1000,
            daily_token_budget: 100000,
            max_prompt_bytes: 10000,
            development: true,
            allow_paid: false,
        },
        vec![Box::new(provider)],
        Box::new(NoCache),
    )
    .unwrap();
    let template: ThumbnailTemplate = serde_json::from_str(include_str!(
        "../../picocast-media/src/thumbnail_fixture.json"
    ))
    .unwrap();
    let limits = ImageLimits {
        max_images: 1,
        max_total_bytes: 2000000,
        max_width: 640,
        max_height: 360,
        max_decoded_bytes: 1000000,
    };
    let mut engine = TextLayoutEngine::new(
        &[FontSource {
            path: "C:/Windows/Fonts/YuGothB.ttc".into(),
        }],
        "ja-JP".into(),
    )
    .unwrap();
    let pixels = image::RgbaImage::from_fn(640, 360, |x, y| {
        image::Rgba([(x % 200) as u8, (y % 200) as u8, 80, 255])
    });
    let mut bytes = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels)
        .write_to(&mut bytes, image::ImageFormat::Png)
        .unwrap();
    let image = InlineImage {
        mime: "image/png".into(),
        bytes: bytes.into_inner(),
    };
    let clear = Assessment {
        text_score: 100,
        anatomy_score: 100,
        content_score: 100,
        originality: Originality::Clear,
    };
    let mut images = ImageGateway::new(
        channel.clone(),
        Box::new(FakeImageProvider::new(
            channel.clone(),
            (0..3)
                .map(|_| {
                    Ok(ImageCompletion {
                        image: image.clone(),
                        usage: None,
                        actual_seed: Some(42),
                        software_version: "synthetic".into(),
                    })
                })
                .collect(),
        )),
        Box::new(FakeImageInspector::new(vec![clear; 3])),
        ImageOptions {
            max_regenerations: 0,
            timeout_ms: 1000,
            max_prompt_bytes: 10000,
            daily_budget_micros: 1000,
            daily_token_budget: 100000,
            allow_paid: false,
            development: true,
            min_text_score: 80,
            min_anatomy_score: 80,
            min_content_score: 80,
            min_variance: 0.001,
            min_visible_fraction: 0.5,
            limits: limits.clone(),
        },
    )
    .unwrap();
    let style = StyleProfile {
        channel_id: channel.clone(),
        version: 1,
        style: "原創の切り絵".into(),
        negative: "文字・固有人物".into(),
        seed: SeedPolicy::Fixed { seed: 42 },
        loras: vec![],
        prohibited_names: vec!["既存キャラ".into()],
    };
    let spec = ImageSpec {
        width: 640,
        height: 360,
        aspect_ratio: "16:9".into(),
        image_size: None,
        steps: 5,
        sampler: "Euler".into(),
        cfg_scale: 7.0,
        checkpoint_hash: None,
    };
    let criteria = vec!["原文の事実を保つ".into()];
    let context = PromptContext {
        existing_titles: &[],
        analytics_tsv: None,
        expansion_criteria: &criteria,
    };
    let (handle, mut cancel) = Cancellation::pair();
    if case == FixtureCase::Cancelled {
        handle.cancel();
    }
    let result = generate(
        &mut store,
        &mut gateway,
        &mut images,
        &mut engine,
        ThumbnailRequest {
            channel: &channel,
            request_id: "thumbnail-fixture",
            title: "宇宙の解説",
            source: "月と太陽と星について調べる。",
            context: &context,
            template: &template,
            style: &style,
            image_spec: &spec,
            image_model: "fixture",
            image_billing: &ImageBilling::PerImage { micros: 0 },
            image_limits: &limits,
            settings_hash: "fixture-settings",
            maximum_teaser_chars: 12,
            maximum_source_bytes: 1000,
            project_id: None,
            job_id: None,
        },
        None,
        &mut cancel,
    )
    .await;
    let ledger = store
        .repository(&channel)
        .unwrap()
        .list::<CostLedger>()
        .unwrap();
    assert_eq!(
        ledger.len(),
        match case {
            FixtureCase::Ready => 7,
            FixtureCase::Cancelled => 0,
            _ => 3,
        }
    );
    result
}

#[tokio::test]
async fn three_candidates_use_existing_gateways_and_preserve_text() {
    match run(FixtureCase::Ready).await.unwrap() {
        ThumbnailOutcome::Drafts(drafts) => {
            assert_eq!(drafts.candidates.len(), 3);
            assert!(drafts.requires_human_selection);
            for draft in drafts.candidates {
                assert_eq!(draft.teaser.text, draft.composed.metrics.text);
                assert_eq!(draft.composed.metrics.overflowing_pixels, 0);
                assert!(draft.review.readable);
            }
        }
        ThumbnailOutcome::Hold { reason, .. } => panic!("{reason}"),
    }
}
#[tokio::test]
async fn unreadable_preview_stops_before_remaining_candidates() {
    assert!(matches!(
        run(FixtureCase::Unreadable).await.unwrap(),
        ThumbnailOutcome::Hold { candidate: 0, .. }
    ));
}

#[tokio::test]
async fn wrong_transcription_holds_and_cancellation_never_reserves_cost() {
    assert!(matches!(
        run(FixtureCase::WrongText).await.unwrap(),
        ThumbnailOutcome::Hold { candidate: 0, .. }
    ));
    assert!(run(FixtureCase::Cancelled).await.is_err());
}
