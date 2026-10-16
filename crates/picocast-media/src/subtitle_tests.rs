#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;

fn options() -> LayoutOptions {
    LayoutOptions {
        width_px: 280.0,
        height_px: 150.0,
        max_lines_per_cue: 3,
        max_graphemes_per_line: 24,
        min_graphemes_per_line: 2,
        max_input_graphemes: 400,
        max_measurements: 20_000,
        allow_inside_phrase_break: true,
        prohibited_line_start: "、。，．！？!?)]｝〉》」』】ーぁぃぅぇぉっゃゅょァィゥェォッャュョ"
            .into(),
        prohibited_line_end: "([｛〈《「『【".into(),
        minimum_display_ms: 500,
        max_graphemes_per_second: 12.0,
        style: TextStyle {
            family: "Yu Gothic".into(),
            font_size: 28.0,
            line_height: 44.0,
            normal_weight: 400,
            emphasis_weight: 700,
            normal_rgba: [255, 255, 255, 255],
            emphasis_rgba: [250, 100, 60, 255],
            stroke_px: 1.5,
        },
    }
}

#[test]
fn invalid_limits_and_missing_font_are_explicit_errors() {
    let mut settings = options();
    settings.width_px = f32::NAN;
    assert_eq!(
        settings.validate().err().unwrap().code,
        "E-SUBTITLE-SETTINGS"
    );
    settings = options();
    settings.min_graphemes_per_line = 1;
    assert!(settings.validate().is_err());
    assert!(TextLayoutEngine::new(&[], "ja-JP".into()).is_err());
}

#[cfg(windows)]
mod measured {
    use super::*;
    use proptest::{
        prelude::*,
        test_runner::{Config, RngSeed, TestRunner},
    };

    fn engine() -> TextLayoutEngine {
        TextLayoutEngine::new(
            &[
                FontSource {
                    path: "C:/Windows/Fonts/YuGothR.ttc".into(),
                },
                FontSource {
                    path: "C:/Windows/Fonts/YuGothB.ttc".into(),
                },
                FontSource {
                    path: "C:/Windows/Fonts/seguiemj.ttf".into(),
                },
            ],
            "ja-JP".into(),
        )
        .unwrap()
    }
    fn assert_layout(source: &str, layout: &SubtitleLayout, settings: &LayoutOptions) {
        let mut rebuilt = String::new();
        let mut last = 0;
        for cue in &layout.cues {
            assert!(cue.start_ms >= last && cue.end_ms > cue.start_ms);
            assert!(cue.end_ms - cue.start_ms >= settings.minimum_display_ms);
            assert!(cue.lines.len() <= settings.max_lines_per_cue);
            assert!(cue.lines.iter().map(|line| line.height_px).sum::<f32>() <= settings.height_px);
            assert!(cue.end_ms - cue.start_ms >= minimum_duration(&cue.lines, settings).unwrap());
            for line in &cue.lines {
                assert!(line.width_px <= settings.width_px);
                assert!(
                    line.text
                        .graphemes(true)
                        .filter(|cluster| !cluster.trim().is_empty())
                        .count()
                        >= 2
                );
                assert!(legal_edges(&line.text, settings));
                assert_eq!(
                    line.runs
                        .iter()
                        .map(|run| run.text.as_str())
                        .collect::<String>(),
                    line.text
                );
                assert_eq!(line.text, source[line.source_start..line.source_end]);
                rebuilt.push_str(&line.text);
            }
            last = cue.end_ms;
        }
        assert_eq!(rebuilt, source.replace('\n', ""));
    }

    #[test]
    fn real_fonts_measure_japanese_english_punctuation_emoji_emphasis_and_page_splits() {
        let mut engine = engine();
        for source in [
            "今日は良い天気です。字幕は実際の幅で折り返します。",
            "This is an English subtitle with punctuation.",
            "「日本語の禁則」を守ります。開き括弧と閉じ括弧を確認します。",
            "😀😀日本語と絵文字を同じサイズで表示します。",
            "がっこうとカフェの字幕を確認します。",
        ] {
            let emphasis = vec![Emphasis {
                start: 0,
                end: source.grapheme_indices(true).nth(2).unwrap().0,
            }];
            let settings = options();
            let layout = engine
                .layout(source, &emphasis, 100, 60_100, &settings)
                .unwrap();
            assert_layout(source, &layout, &settings);
            assert_eq!(layout.cues.first().unwrap().start_ms, 100);
            assert_eq!(layout.cues.last().unwrap().end_ms, 60_100);
            assert!(layout
                .cues
                .iter()
                .flat_map(|cue| &cue.lines)
                .flat_map(|line| &line.runs)
                .any(|run| run.emphasized
                    && run.weight == 700
                    && run.rgba == settings.style.emphasis_rgba));
            tracing::info!(
                fixture=source, widths=?layout
                    .cues
                    .iter()
                    .flat_map(|cue| &cue.lines)
                    .map(|line| line.width_px)
                    .collect::<Vec<_>>(),"実測字幕fixture"
            );
        }
    }

    #[test]
    fn impossible_width_single_grapheme_bad_ranges_and_short_display_are_rejected() {
        let mut engine = engine();
        let mut settings = options();
        settings.width_px = 1.0;
        assert_eq!(
            engine
                .layout("日本語です。", &[], 0, 10_000, &settings)
                .err()
                .unwrap()
                .code,
            "E-SUBTITLE-LAYOUT"
        );
        settings = options();
        assert!(engine.layout("字", &[], 0, 10_000, &settings).is_err());
        assert!(engine
            .layout("日本語です。", &[], 0, 50, &settings)
            .is_err());
        assert!(engine
            .layout(
                "日本語です。",
                &[Emphasis { start: 1, end: 5 }],
                0,
                10_000,
                &settings
            )
            .is_err());
        assert!(engine
            .layout("、禁止の行頭です。", &[], 0, 10_000, &settings)
            .is_err());
        settings.max_measurements = 1;
        assert_eq!(
            engine
                .layout(
                    "複数の字幕を実測して配置します。",
                    &[],
                    0,
                    10_000,
                    &settings
                )
                .err()
                .unwrap()
                .code,
            "E-SUBTITLE-LIMIT"
        );
    }

    #[test]
    fn property_successful_layouts_never_overflow_split_graphemes_or_violate_kinsoku() {
        let engine = std::cell::RefCell::new(engine());
        let config = Config {
            cases: 48,
            failure_persistence: None,
            rng_seed: RngSeed::Fixed(20261016),
            ..Config::default()
        };
        let mut runner = TestRunner::new(config);
        let strategy = (
            prop::collection::vec(
                prop_oneof![
                    Just("日本"),
                    Just("字幕"),
                    Just("かな"),
                    Just("カナ"),
                    Just("😀😀"),
                    Just("ab")
                ],
                2..15,
            ),
            100u16..500,
            16u16..32,
        );
        runner
            .run(&strategy, |(parts, width, font)| {
                let source = parts.concat();
                let mut settings = options();
                settings.width_px = f32::from(width);
                settings.style.font_size = f32::from(font);
                settings.style.line_height = f32::from(font) * 1.7;
                let layout = engine
                    .borrow_mut()
                    .layout(&source, &[], 0, 120_000, &settings)
                    .map_err(|error| TestCaseError::fail(error.code))?;
                assert_layout(&source, &layout, &settings);
                Ok(())
            })
            .unwrap();
    }
}
