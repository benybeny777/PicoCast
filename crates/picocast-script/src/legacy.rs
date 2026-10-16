//! 旧ScriptParserの行状態機械。生成の本番入口は構造化出力だけを使う。

use crate::invalid;
use picocast_core::Result;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dialogue {
    pub character: String,
    pub emotion: String,
    pub expression: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Item {
    #[serde(rename = "type")]
    pub kind: String,
    pub text: String,
    #[serde(flatten)]
    pub dialogue: Option<Dialogue>,
}

/// 旧版の未知話者補正を使う場合だけ、呼出側で補正先を明示する。
pub struct ParserOptions {
    pub characters: Vec<(String, String)>,
    pub unknown_character: Option<String>,
}

struct Marker {
    kind: &'static str,
    labels: &'static [&'static str],
    bracket: bool,
    keyword: bool,
}

// 入力の別名と書き出し名を同じ正本から使う。旧版の優先順も維持する。
const MARKERS: &[Marker] = &[
    Marker {
        kind: "background",
        labels: &["背景", "background", "シーン", "scene"],
        bracket: false,
        keyword: true,
    },
    Marker {
        kind: "video_format",
        labels: &["動画形式", "format"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "thumbnail",
        labels: &["サムネイル", "thumbnail"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "thumbnail_text",
        labels: &["サムネ文字", "サムネテキスト"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "video_title",
        labels: &["動画タイトル", "title"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "description",
        labels: &["説明文", "description"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "tags",
        labels: &["タグ", "tags", "tag"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "fixed_comment",
        labels: &["固定コメント", "pinnedcomment"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "generation_kind",
        labels: &["生成区分", "generationkind"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "source_video_title",
        labels: &["元動画", "派生元", "sourcevideo"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "generation_purpose",
        labels: &["目的", "生成目的", "generationpurpose"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "character_pattern",
        labels: &["キャラパターン", "characterpattern"],
        bracket: false,
        keyword: true,
    },
    Marker {
        kind: "genre_group",
        labels: &["ジャンル", "genre", "genregroup"],
        bracket: false,
        keyword: true,
    },
    Marker {
        kind: "topic_request_cta",
        labels: &["ネタ募集cta", "topicrequestcta"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "topic_request_cta_reason",
        labels: &["ネタ募集cta理由", "topicrequestctareason"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "screen_format",
        labels: &["画面形式", "screenformat"],
        bracket: false,
        keyword: false,
    },
    Marker {
        kind: "playlist_categories",
        labels: &["再生リスト", "playlist"],
        bracket: false,
        keyword: true,
    },
    Marker {
        kind: "meeting_candidates",
        labels: &["候補ネタ", "meetingcandidates", "candidates"],
        bracket: true,
        keyword: true,
    },
    Marker {
        kind: "telop",
        labels: &["テロップ", "telop"],
        bracket: false,
        keyword: true,
    },
    Marker {
        kind: "poll_options",
        labels: &["アンケート設定案", "アンケート手動設定用", "polloptions"],
        bracket: false,
        keyword: true,
    },
];

pub fn is_meta(kind: &str) -> bool {
    MARKERS
        .iter()
        .any(|marker| marker.kind == kind && !matches!(kind, "background" | "telop"))
}

fn item(kind: &str, text: &str) -> Item {
    Item {
        kind: kind.into(),
        text: text.into(),
        dialogue: None,
    }
}

fn split_label(line: &str) -> Option<(&str, &str)> {
    line.char_indices()
        .find(|(_, character)| matches!(character, ':' | '：'))
        .map(|(index, character)| (&line[..index], &line[index + character.len_utf8()..]))
}

fn marker(line: &str, bracket: bool) -> Option<(&'static Marker, &str)> {
    let (label, value) = if bracket {
        let text = line.strip_prefix('【')?;
        let (label, value) = text.split_once('】')?;
        (label.trim(), value)
    } else {
        split_label(line)?
    };
    let lowered = label.to_lowercase();
    MARKERS
        .iter()
        .find(|marker| {
            (!bracket || marker.bracket)
                && marker.labels.iter().any(|label| {
                    let label_part = if marker.kind == "background" {
                        lowered.trim_end_matches(|character: char| character.is_numeric())
                    } else {
                        &lowered
                    };
                    label_part == *label
                })
        })
        .map(|marker| (marker, value.trim()))
}

fn poll_marker(line: &str) -> bool {
    line.strip_prefix("---").is_some_and(|rest| {
        let rest = rest.trim_start();
        ["アンケート設定案", "アンケート手動設定用"]
            .iter()
            .any(|label| {
                rest.strip_prefix(label)
                    .is_some_and(|rest| rest.trim_start().starts_with("---"))
            })
    })
}

fn ignored(line: &str) -> bool {
    line.starts_with("```")
        || line.starts_with('#')
        || line.starts_with("---")
        || (line.starts_with('━') && line.ends_with('━') && line.chars().count() >= 2)
        || (line.starts_with(['（', '(']) && line.ends_with(['）', ')']))
        || (line.starts_with('【') && line.ends_with('】'))
        || (line.starts_with('*') && line.ends_with('*') && line.len() >= 2)
}

fn dialogue_parts(line: &str) -> Option<(String, Option<String>, Option<String>, String)> {
    let (prefix, text) = split_label(line)?;
    let boundary = prefix
        .char_indices()
        .find(|(_, character)| matches!(character, '(' | '（' | '[' | ']' | '【'))
        .map_or(prefix.len(), |(index, _)| index);
    let name = prefix[..boundary].trim();
    if name.is_empty() {
        return None;
    }
    let mut rest = prefix[boundary..].trim();
    let mut emotion = None;
    let mut expression = None;
    if rest.starts_with(['(', '（']) {
        let inner = &rest[rest.chars().next()?.len_utf8()..];
        let (end, close) = inner
            .char_indices()
            .find(|(_, character)| matches!(character, ')' | '）'))?;
        if end == 0 {
            return None;
        }
        emotion = Some(inner[..end].into());
        rest = inner[end + close.len_utf8()..].trim();
    }
    if let Some(inner) = rest.strip_prefix('[') {
        let (value, tail) = inner.split_once(']')?;
        if value.is_empty() {
            return None;
        }
        expression = Some(value.trim().into());
        rest = tail.trim();
    }
    rest.is_empty()
        .then(|| (name.into(), emotion, expression, text.trim().into()))
}

fn keyword(line: &str) -> bool {
    marker(line, false).is_some_and(|(marker, _)| marker.keyword)
        || marker(line, true).is_some()
        || split_label(line).is_some_and(|(label, _)| label == "候補番号")
}

fn multiline(kind: &str) -> bool {
    matches!(
        kind,
        "description" | "meeting_candidates" | "fixed_comment" | "poll_options"
    )
}
fn dialogue_safe(kind: &str) -> bool {
    matches!(
        kind,
        "meeting_candidates" | "fixed_comment" | "poll_options"
    )
}

pub fn parse(text: &str, options: &ParserOptions) -> Result<Vec<Item>> {
    if options.characters.is_empty()
        || options
            .characters
            .iter()
            .any(|(alias, name)| alias.is_empty() || name.is_empty())
    {
        return Err(invalid());
    }
    let mut output: Vec<Item> = Vec::new();
    let mut last_dialogue: Option<usize> = None;
    let mut last_meta: Option<usize> = None;
    for raw in text.lines() {
        let line = raw.trim().replace("**", "").replace("__", "");
        let line = line.as_str();
        if line.is_empty() {
            continue;
        }
        if let Some((marker, value)) = marker(line, true).filter(|(marker, _)| {
            !(marker.kind == "tags"
                && line
                    .strip_prefix('【')
                    .and_then(|value| value.split_once('】'))
                    .is_some_and(|(label, _)| label.trim().eq_ignore_ascii_case("tag")))
        }) {
            output.push(item(marker.kind, value));
            last_dialogue = None;
            last_meta = Some(output.len() - 1);
            continue;
        }
        if let Some(index) = last_meta {
            if poll_marker(line) {
                output.push(item("poll_options", ""));
                last_dialogue = None;
                last_meta = Some(output.len() - 1);
                continue;
            }
            let previous = &mut output[index];
            if !keyword(line)
                && (dialogue_parts(line).is_none() || dialogue_safe(&previous.kind))
                && (!ignored(line) || multiline(&previous.kind))
            {
                if multiline(&previous.kind) {
                    previous.text = format!("{}\n{line}", previous.text).trim().into();
                    continue;
                } else if previous.text.is_empty() {
                    previous.text = if previous.kind == "background" {
                        line.trim_matches(['(', ')', '（', '）']).into()
                    } else {
                        line.into()
                    };
                    last_meta = None;
                    continue;
                }
            }
            last_meta = None;
        }
        if poll_marker(line)
            || marker(line, false).is_some_and(|(marker, _)| marker.kind == "poll_options")
        {
            output.push(item("poll_options", ""));
            last_dialogue = None;
            last_meta = Some(output.len() - 1);
            continue;
        }
        if ignored(line) {
            last_dialogue = None;
            last_meta = None;
            continue;
        }
        if split_label(line).is_some_and(|(label, _)| {
            [
                "チャプター",
                "チャプター一覧",
                "chapter",
                "chapters",
                "chapterlist",
            ]
            .contains(&label.to_lowercase().as_str())
        }) {
            last_dialogue = None;
            last_meta = None;
            continue;
        }
        if let Some((marker, value)) = marker(line, false) {
            let value = if marker.kind == "background" {
                value.trim_matches(['(', ')', '（', '）'])
            } else {
                value
            };
            output.push(item(marker.kind, value));
            last_dialogue = None;
            last_meta =
                if marker.kind == "telop" || (marker.kind == "background" && !value.is_empty()) {
                    None
                } else {
                    Some(output.len() - 1)
                };
            continue;
        }
        if split_label(line).is_some_and(|(label, _)| label == "候補番号") {
            let index = match output
                .iter()
                .rposition(|item| item.kind == "meeting_candidates")
            {
                Some(index) => {
                    output[index].text = format!("{}\n{line}", output[index].text).trim().into();
                    index
                }
                None => {
                    output.push(item("meeting_candidates", line));
                    output.len() - 1
                }
            };
            last_dialogue = None;
            last_meta = Some(index);
            continue;
        }
        if let Some((mut name, mut emotion, mut expression, mut text)) = dialogue_parts(line) {
            if name.ends_with([')', '）']) {
                name.pop();
                name = name.trim().into();
                if emotion.is_none() {
                    emotion = Some(
                        if name.contains("めたん") {
                            "ツンツン"
                        } else {
                            "ノーマル"
                        }
                        .into(),
                    );
                }
                tracing::warn!("旧版台本の余分な右括弧を補正しました");
            }
            if expression.is_none() {
                if let Some(inner) = text.strip_prefix('[') {
                    if let Some((value, tail)) =
                        inner.split_once(']').filter(|(value, _)| !value.is_empty())
                    {
                        expression = Some(value.trim().into());
                        text = tail.trim().into();
                    }
                }
            }
            let found = options
                .characters
                .iter()
                .find(|(alias, _)| name.contains(alias))
                .map(|(_, name)| name.clone());
            let character = match found {
                Some(name) => name,
                None => {
                    // フォールバック許可: 旧版の互換取り込みで補正先を呼出側が明示した場合だけ使う。
                    let name = options.unknown_character.clone().ok_or_else(invalid)?;
                    tracing::warn!("旧版の未知話者を明示指定された互換話者へ補正しました");
                    name
                }
            };
            if text
                .trim_matches(['。', '、', '！', '？', '…', '・', '〜', '　', ' '])
                .is_empty()
            {
                last_meta = None;
                continue;
            }
            output.push(Item {
                kind: "dialogue".into(),
                text,
                dialogue: Some(Dialogue {
                    character,
                    emotion: emotion.unwrap_or_else(|| "ノーマル".into()),
                    expression,
                }),
            });
            last_dialogue = Some(output.len() - 1);
            last_meta = None;
            continue;
        }
        if let Some(index) = last_dialogue {
            if line.starts_with(['*', '-', '・']) {
                last_dialogue = None;
                continue;
            }
            let previous = &mut output[index].text;
            if !previous.ends_with(['。', '！', '？', '.', '!', '?']) {
                previous.push(' ');
            }
            previous.push_str(line);
        }
    }
    Ok(output)
}

pub fn write(items: &[Item]) -> Result<String> {
    let mut output = String::new();
    for item in items {
        if let Some(dialogue) = &item.dialogue {
            if item.kind != "dialogue"
                || dialogue
                    .character
                    .contains([':', '：', '\n', '\r', '(', '（', '['])
                || dialogue.emotion.contains([')', '）', '\n', '\r'])
                || dialogue
                    .expression
                    .as_ref()
                    .is_some_and(|value| value.contains([']', '\n', '\r']))
            {
                return Err(invalid());
            }
            let expression = dialogue
                .expression
                .as_ref()
                .map_or(String::new(), |value| format!("[{value}]"));
            output.push_str(&format!(
                "{}({}){expression}: {}\n",
                dialogue.character, dialogue.emotion, item.text
            ));
        } else {
            let marker = MARKERS
                .iter()
                .find(|marker| marker.kind == item.kind)
                .ok_or_else(invalid)?;
            if item.kind == "poll_options" {
                output.push_str(&format!("{}:\n{}\n", marker.labels[0], item.text));
            } else {
                output.push_str(&format!("{}: {}\n", marker.labels[0], item.text));
            }
        }
    }
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn options() -> ParserOptions {
        ParserOptions {
            characters: vec![
                ("ずんだもん".into(), "ずんだもん".into()),
                ("四国めたん".into(), "四国めたん".into()),
            ],
            unknown_character: Some("ずんだもん".into()),
        }
    }
    #[test]
    fn matches_every_script_oracle_case() -> Result<()> {
        let inputs: serde_json::Value =
            serde_json::from_str(include_str!("../../../tests/oracle/inputs/v1.json"))
                .map_err(|_| invalid())?;
        let expected: serde_json::Value =
            serde_json::from_str(include_str!("../../../tests/oracle/expected/v1.json"))
                .map_err(|_| invalid())?;
        for case in inputs["cases"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .filter(|case| case["kind"] == "script")
        {
            let actual = parse(
                case["input"]["text"].as_str().ok_or_else(invalid)?,
                &options(),
            )?;
            let expected = expected["cases"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .find(|expected| expected["id"] == case["id"])
                .ok_or_else(invalid)?;
            assert_eq!(
                serde_json::to_value(&actual).map_err(|_| invalid())?,
                expected["output"]
            );
            assert_eq!(parse(&write(&actual)?, &options())?, actual);
        }
        Ok(())
    }
    #[test]
    fn preserves_multiline_blocks_corrections_and_punctuation_skips() -> Result<()> {
        let input="【説明文】\n説明の続き\n背景1: （図書館）\nずんだもん: 根拠は資料なのだ。\n続きも読む\n四国めたん)[驚き]: [重複タグ]具体例は？\nずんだもん: 。。。！？\n固定コメント: 質問です\nURL: https://example.invalid\n---アンケート設定案---\n質問: どれ？\n選択肢1: A";
        let actual = parse(input, &options())?;
        assert_eq!(actual[0].text, "説明の続き");
        assert_eq!(actual[1].text, "図書館");
        assert_eq!(actual[2].text, "根拠は資料なのだ。続きも読む");
        assert_eq!(
            actual[3].dialogue.as_ref().ok_or_else(invalid)?.emotion,
            "ツンツン"
        );
        assert_eq!(actual[4].text, "質問です\nURL: https://example.invalid");
        assert_eq!(actual[5].kind, "poll_options");
        assert!(actual[5].text.contains("選択肢1"));
        Ok(())
    }
    #[test]
    fn unknown_character_requires_explicit_compatibility_target() {
        let mut config = options();
        config.unknown_character = None;
        assert!(parse("未登録: 本文", &config).is_err());
    }
}
