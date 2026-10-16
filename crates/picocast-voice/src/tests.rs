#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;
use picocast_core::{clock::Timestamp, ChannelId};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    path::PathBuf,
    time::Duration,
};

fn channel() -> ChannelId {
    ChannelId::new("voice-fixture").unwrap()
}
fn at() -> Timestamp {
    Timestamp::parse("2026-10-16T00:00:00Z").unwrap()
}
fn wave_policy() -> WavePolicy {
    WavePolicy {
        tail_silence: Duration::from_millis(500),
        silence_threshold: 0,
        maximum_bytes: 1_000_000,
    }
}

fn wave(samples: &[i16], rate: u32, channels: u16) -> Vec<u8> {
    let size = samples.len() as u32 * 2;
    let mut result = Vec::new();
    result.extend_from_slice(b"RIFF");
    result.extend_from_slice(&(size + 36).to_le_bytes());
    result.extend_from_slice(b"WAVEfmt ");
    result.extend_from_slice(&16_u32.to_le_bytes());
    result.extend_from_slice(&1_u16.to_le_bytes());
    result.extend_from_slice(&channels.to_le_bytes());
    result.extend_from_slice(&rate.to_le_bytes());
    result.extend_from_slice(&(rate * u32::from(channels) * 2).to_le_bytes());
    result.extend_from_slice(&(channels * 2).to_le_bytes());
    result.extend_from_slice(&16_u16.to_le_bytes());
    result.extend_from_slice(b"data");
    result.extend_from_slice(&size.to_le_bytes());
    for sample in samples {
        result.extend_from_slice(&sample.to_le_bytes());
    }
    result
}

#[test]
fn pcm_tail_exact_boundary_partial_and_stereo() {
    let policy = wave_policy();
    // 10Hzの合成録画は、0.5秒=5フレームを端数なしで比較するためのfixture。
    for samples in [vec![32767], vec![32767, 0, 0], vec![32767, 0, 0, 0, 0, 0]] {
        let output = ensure_trailing_silence(&wave(&samples, 10, 1), &policy).unwrap();
        assert_eq!(output.frames, 6);
        assert_eq!(output.trailing_silent_frames, 5);
        assert_eq!(output.duration_seconds(), 0.6);
        let repeated = ensure_trailing_silence(&output.bytes, &policy).unwrap();
        assert_eq!(repeated.bytes, output.bytes);
    }
    let output = ensure_trailing_silence(&wave(&[0, -32768, 0, 0], 10, 2), &policy).unwrap();
    assert_eq!(output.channels, 2);
    assert_eq!(output.frames, 6);
    assert_eq!(output.trailing_silent_frames, 5);
    let rounding = ensure_trailing_silence(&wave(&[200], 3, 1), &policy).unwrap();
    assert_eq!(rounding.trailing_silent_frames, 2);
}

#[test]
fn corrupt_or_silent_audio_never_becomes_a_success() {
    let valid = wave(&[1, 0], 10, 1);
    for bytes in [
        Vec::new(),
        b"not a wav".to_vec(),
        valid[..valid.len() - 1].to_vec(),
        wave(&[], 10, 1),
        wave(&[0, 0], 10, 1),
        wave(&[1], 0, 1),
        wave(&[1], 10, 2),
    ] {
        assert!(ensure_trailing_silence(&bytes, &wave_policy()).is_err());
    }
    let mut wrong_size = valid.clone();
    wrong_size[4] = 0;
    assert!(ensure_trailing_silence(&wrong_size, &wave_policy()).is_err());
    let mut encoding = valid.clone();
    encoding[20] = 3;
    assert!(ensure_trailing_silence(&encoding, &wave_policy()).is_err());
    let mut bounded = wave_policy();
    bounded.maximum_bytes = valid.len();
    assert!(ensure_trailing_silence(&valid, &bounded).is_err());
}

struct NoAnalyzer;
impl ReadingAnalyzer for NoAnalyzer {
    fn tokenize(&mut self, _text: &str) -> picocast_core::Result<Vec<ReadingToken>> {
        Err(failure("E-VOICE-READING"))
    }
}

#[test]
fn dictionary_oracle_and_channel_boundary() {
    let input: Value =
        serde_json::from_str(include_str!("../../../tests/oracle/inputs/v1.json")).unwrap();
    let expected: Value =
        serde_json::from_str(include_str!("../../../tests/oracle/expected/v1.json")).unwrap();
    let case = input["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == "reading-dictionary-overlap")
        .unwrap();
    let dictionary = dictionary_from_case(case);
    let texts = texts_from_case(case);
    let mut normalizer = ReadingNormalizer::<NoAnalyzer>::new(
        channel(),
        ReadingPolicy {
            mode: ReadingMode::Dictionary,
            minimum_noun_characters: 2,
        },
        dictionary,
        None,
    )
    .unwrap();
    let result = normalizer.normalize(&channel(), &texts, &at()).unwrap();
    let expected = expected["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == "reading-dictionary-overlap")
        .unwrap();
    assert_eq!(
        serde_json::to_value(&result.readings).unwrap(),
        expected["output"]
    );
    assert!(normalizer
        .normalize(&ChannelId::new("another").unwrap(), &texts, &at())
        .is_err());
    assert!(ReadingNormalizer::<NoAnalyzer>::new(
        channel(),
        ReadingPolicy {
            mode: ReadingMode::SafeAuto,
            minimum_noun_characters: 2
        },
        ReadingDictionary::default(),
        None
    )
    .is_err());
    assert_eq!(
        katakana_to_hiragana("アイヴヵヶーABC").unwrap(),
        "あいゔゕゖーABC"
    );
}

fn dictionary_from_case(case: &Value) -> ReadingDictionary {
    let entries = |key: &str| {
        case["input"][key]
            .as_object()
            .unwrap()
            .iter()
            .map(|(key, value)| (key.clone(), value.as_str().unwrap().to_owned()))
            .collect()
    };
    ReadingDictionary {
        base: entries("base"),
        user: entries("user"),
        ..Default::default()
    }
}
fn texts_from_case(case: &Value) -> Vec<String> {
    serde_json::from_value(case["input"]["texts"].clone()).unwrap()
}

/// 辞書の巨大な配布・取得を検証へ紛れ込ませず、明示して実行する。
#[test]
#[ignore = "既存 .venv の Sudachi 辞書だけを使うローカル受入"]
fn installed_sudachi_matches_reading_oracle_and_analyzes_unknown_words() {
    // Cargo のテスト実行ディレクトリはこのパッケージのルート。
    let root = PathBuf::from("../..").canonicalize().unwrap();
    let packages = root.join(".venv/Lib/site-packages");
    let paths = SudachiPaths {
        system_dictionary: packages.join("sudachidict_core/resources/system.dic"),
        resources_directory: packages.join("sudachipy/resources"),
        configuration_file: packages.join("sudachipy/resources/sudachi.json"),
    };
    let analyzer = SudachiAnalyzer::open(&paths).unwrap();
    let input: Value =
        serde_json::from_str(include_str!("../../../tests/oracle/inputs/v1.json")).unwrap();
    let expected: Value =
        serde_json::from_str(include_str!("../../../tests/oracle/expected/v1.json")).unwrap();
    let case = input["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == "reading-safe-auto")
        .unwrap();
    let mut normalizer = ReadingNormalizer::new(
        channel(),
        ReadingPolicy {
            mode: ReadingMode::SafeAuto,
            minimum_noun_characters: 2,
        },
        dictionary_from_case(case),
        Some(analyzer),
    )
    .unwrap();
    let result = normalizer
        .normalize(&channel(), &texts_from_case(case), &at())
        .unwrap();
    let expected = expected["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == "reading-safe-auto")
        .unwrap();
    assert_eq!(
        serde_json::to_value(&result.readings).unwrap(),
        expected["output"]
    );
    let text = "東京でPicoCast987を点検する".to_owned();
    let result = normalizer
        .normalize(&channel(), std::slice::from_ref(&text), &at())
        .unwrap();
    assert!(result.readings.contains_key(&text));
    assert!(!result.inspections.is_empty());
}

fn query() -> Value {
    json!({"accent_phrases":[{"moras":[{"text":"テ","vowel":"e","vowel_length":0.1,"pitch":5.0},{"text":"ス","vowel":"u","vowel_length":0.1,"pitch":5.0}],"accent":1,"pause_mora":null,"is_interrogative":false}], "speedScale":1.0,"pitchScale":0.0,"intonationScale":1.0,"volumeScale":1.0,"prePhonemeLength":0.1,"postPhonemeLength":0.1,"outputSamplingRate":10,"outputStereo":false,"kana":"テ'ス"})
}
fn settings() -> VoicevoxSettings {
    VoicevoxSettings {
        endpoint: "http://127.0.0.1:50021".into(),
        local_only: true,
        volume_scale: 2.0,
        speed_scale: 1.2,
        post_phoneme_length: Duration::from_millis(500),
        maximum_query_bytes: 65536,
        maximum_text_characters: 1024,
        wave: wave_policy(),
    }
}
fn styles() -> CharacterStyles {
    CharacterStyles {
        character_id: "zundamon".into(),
        normal_style: 3,
        emotion_styles: BTreeMap::from([("ノーマル".into(), 3), ("ささやき".into(), 22)]),
        available_styles: BTreeSet::from([3, 22]),
    }
}

struct Replay {
    responses: VecDeque<VoiceResponse>,
    requests: Vec<VoiceRequest>,
}
impl Replay {
    fn standard() -> Self {
        Self {
            responses: VecDeque::from([
                VoiceResponse {
                    status: 200,
                    body: serde_json::to_vec(&query()).unwrap(),
                },
                VoiceResponse {
                    status: 200,
                    body: wave(&[3000, 0], 10, 1),
                },
            ]),
            requests: Vec::new(),
        }
    }
}
impl VoiceTransport for Replay {
    fn send<'a>(&'a mut self, request: VoiceRequest) -> VoiceFuture<'a, VoiceResponse> {
        self.requests.push(request);
        Box::pin(async move {
            self.responses
                .pop_front()
                .ok_or_else(|| failure("E-VOICE-ENGINE"))
        })
    }
}

#[tokio::test]
async fn legacy_query_and_synthesis_parameters_record_exactly() {
    let mut provider = Voicevox::new(channel(), settings(), Replay::standard()).unwrap();
    let character = styles();
    let result = provider
        .synthesize(SynthesisRequest {
            channel_id: &channel(),
            text: "検証 &？",
            character: &character,
            emotion: Some("ノーマル"),
            accent: None,
        })
        .await
        .unwrap();
    assert_eq!(result.style_id, 3);
    assert_eq!(result.audio.trailing_silent_frames, 5);
    let transport = provider.into_transport();
    assert_eq!(transport.requests.len(), 2);
    let first = &transport.requests[0];
    assert_eq!(first.method, VoiceMethod::Post);
    assert!(first.body.is_none());
    let url = reqwest::Url::parse(&first.url).unwrap();
    assert_eq!(url.path(), "/audio_query");
    assert_eq!(
        url.query_pairs().collect::<Vec<_>>(),
        vec![
            ("text".into(), "検証 &？".into()),
            ("speaker".into(), "3".into())
        ]
    );
    let second = &transport.requests[1];
    let url = reqwest::Url::parse(&second.url).unwrap();
    assert_eq!(url.path(), "/synthesis");
    assert_eq!(
        url.query_pairs().collect::<Vec<_>>(),
        vec![("speaker".into(), "3".into())]
    );
    let mut legacy = query();
    legacy["volumeScale"] = json!(2.0);
    legacy["speedScale"] = json!(1.2);
    legacy["postPhonemeLength"] = json!(0.5);
    assert_eq!(second.body.as_ref(), Some(&legacy));
    let recording: Value = serde_json::from_str(include_str!(
        "../tests/fixtures/legacy-voicevox-requests.json"
    ))
    .unwrap();
    for (request, expected) in transport
        .requests
        .iter()
        .zip(recording["requests"].as_array().unwrap())
    {
        let url = reqwest::Url::parse(&request.url).unwrap();
        assert_eq!(url.path(), expected["path"].as_str().unwrap());
        let parameters: BTreeMap<String, String> = url.query_pairs().into_owned().collect();
        for (key, value) in expected["params"].as_object().unwrap() {
            let expected = value
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| value.to_string());
            assert_eq!(parameters.get(key), Some(&expected));
        }
        assert_eq!(
            request.body.as_ref().unwrap_or(&Value::Null),
            &expected["body"]
        );
    }
    let directory = tempfile::tempdir().unwrap();
    let destination = directory.path().join("sample.wav");
    result.save_new(&destination).unwrap();
    assert!(result.save_new(&destination).is_err());
    assert_eq!(std::fs::read(destination).unwrap(), result.audio.bytes);
}

struct BatchAnalyzer;
impl ReadingAnalyzer for BatchAnalyzer {
    fn tokenize(&mut self, text: &str) -> picocast_core::Result<Vec<ReadingToken>> {
        if text == "失敗" {
            return Err(failure("E-VOICE-READING"));
        }
        let (reading, pos, pos2) = match text {
            "成功" => ("セイコウ", "名詞", "普通名詞"),
            "二十" => ("ニジュウ", "名詞", "数詞"),
            "曖昧" => ("アイマイ", "形状詞", "一般"),
            _ => return Err(failure("E-VOICE-READING")),
        };
        Ok(vec![ReadingToken {
            surface: text.into(),
            reading: reading.into(),
            part_of_speech: vec![pos.into(), pos2.into()],
            out_of_vocabulary: false,
        }])
    }
}

#[test]
fn failed_batch_rolls_back_learning_and_global_dictionary_retains_accents() {
    use picocast_store::{repository::ReadingEntry, DataMode, Store, StoreOptions, StorePaths};
    let mut normalizer = ReadingNormalizer::new(
        channel(),
        ReadingPolicy {
            mode: ReadingMode::SafeAuto,
            minimum_noun_characters: 2,
        },
        ReadingDictionary::default(),
        Some(BatchAnalyzer),
    )
    .unwrap();
    assert!(normalizer
        .normalize(&channel(), &["成功".into(), "失敗".into()], &at())
        .is_err());
    let report = normalizer
        .normalize(
            &channel(),
            &["成功".into(), "二十".into(), "曖昧".into()],
            &at(),
        )
        .unwrap();
    assert!(report.applied_auto.contains("成功"));
    assert!(!report.applied_user.contains("成功"));
    assert_eq!(report.proposed_candidates.len(), 2);
    assert!(report
        .inspections
        .iter()
        .any(|entry| entry.reason == InspectionReason::Number));
    let temporary = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
    let store = Store::open(
        &paths,
        StoreOptions {
            busy_timeout: Duration::from_secs(2),
            backup_pages_per_step: 8,
            backup_pause: Duration::from_millis(1),
        },
    )
    .unwrap();
    report.persist_proposals(&store).unwrap();
    let plan = AccentPlan {
        version: 1,
        overrides: vec![AccentOverride {
            phrase_index: 0,
            accent: 1,
        }],
    };
    plan.save_entry(&store, "成功", "user", &at()).unwrap();
    report.persist_proposals(&store).unwrap();
    assert_eq!(
        AccentPlan::load_entry(&store, "成功", "user").unwrap(),
        Some(plan)
    );
    let dictionary = ReadingDictionary::load(&store).unwrap();
    assert_eq!(dictionary.user, vec![("成功".into(), "せいこう".into())]);
    assert_eq!(dictionary.candidates.len(), 2);
    let mut edited = store
        .global_repository()
        .list::<ReadingEntry>()
        .unwrap()
        .remove(0);
    edited.reading = "しゅどう".into();
    store.global_repository().save(&edited).unwrap();
    assert!(report.persist_proposals(&store).is_err());
}

#[tokio::test]
async fn style_and_accent_edit_recompute_mora_without_fallback() {
    let plan = AccentPlan {
        version: 1,
        overrides: vec![AccentOverride {
            phrase_index: 0,
            accent: 2,
        }],
    };
    assert_eq!(
        AccentPlan::from_json(&serde_json::to_value(&plan).unwrap()).unwrap(),
        plan
    );
    let mut updated = query()["accent_phrases"].clone();
    updated[0]["accent"] = json!(2);
    let mut replay = Replay::standard();
    replay.responses.insert(
        1,
        VoiceResponse {
            status: 200,
            body: serde_json::to_vec(&updated).unwrap(),
        },
    );
    let mut provider = Voicevox::new(channel(), settings(), replay).unwrap();
    let character = styles();
    let result = provider
        .synthesize(SynthesisRequest {
            channel_id: &channel(),
            text: "テス",
            character: &character,
            emotion: Some("ささやき"),
            accent: Some(&plan),
        })
        .await
        .unwrap();
    assert_eq!(result.style_id, 22);
    assert_eq!(result.query["accent_phrases"][0]["accent"], 2);
    let replay = provider.into_transport();
    assert_eq!(
        reqwest::Url::parse(&replay.requests[1].url).unwrap().path(),
        "/mora_data"
    );
    assert_eq!(replay.requests[1].body, Some(updated));
    assert!(character.select(Some("未登録感情")).is_err());
    for accent in [0, 3] {
        let mut value = query();
        let plan = AccentPlan {
            version: 1,
            overrides: vec![AccentOverride {
                phrase_index: 0,
                accent,
            }],
        };
        assert!(crate::voicevox::apply_accents(&mut value, &plan).is_err());
    }
}

#[tokio::test]
async fn invalid_query_audio_and_cross_channel_stop() {
    let character = styles();
    let mut provider = Voicevox::new(channel(), settings(), Replay::standard()).unwrap();
    assert!(provider
        .synthesize(SynthesisRequest {
            channel_id: &ChannelId::new("other").unwrap(),
            text: "テス",
            character: &character,
            emotion: None,
            accent: None
        })
        .await
        .is_err());
    assert!(provider.into_transport().requests.is_empty());
    for response in [
        VoiceResponse {
            status: 200,
            body: b"invalid".to_vec(),
        },
        VoiceResponse {
            status: 503,
            body: b"private-response".to_vec(),
        },
    ] {
        let replay = Replay {
            responses: VecDeque::from([response]),
            requests: Vec::new(),
        };
        let mut provider = Voicevox::new(channel(), settings(), replay).unwrap();
        assert!(provider
            .synthesize(SynthesisRequest {
                channel_id: &channel(),
                text: "テス",
                character: &character,
                emotion: None,
                accent: None
            })
            .await
            .is_err());
        assert_eq!(provider.into_transport().requests.len(), 1);
    }
    let mut replay = Replay::standard();
    replay.responses[1].body = b"not audio".to_vec();
    let mut provider = Voicevox::new(channel(), settings(), replay).unwrap();
    assert!(provider
        .synthesize(SynthesisRequest {
            channel_id: &channel(),
            text: "テス",
            character: &character,
            emotion: None,
            accent: None
        })
        .await
        .is_err());
}
