use crate::failure;
use picocast_core::{clock::Timestamp, ChannelId, Result};
use picocast_store::{
    repository::{ReadingCandidate, ReadingCandidateKey, ReadingEntry, ReadingEntryKey},
    Store,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::PathBuf,
    sync::Arc,
};
use sudachi::{
    analysis::{stateful_tokenizer::StatefulTokenizer, Mode},
    config::Config,
    dic::dictionary::JapaneseDictionary,
    prelude::MorphemeList,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReadingMode {
    Off,
    Dictionary,
    SafeAuto,
}

/// パスは呼出元が指定する。Python・辞書探索・ダウンロードを実行しない。
#[derive(Clone, Debug)]
pub struct SudachiPaths {
    pub system_dictionary: PathBuf,
    pub resources_directory: PathBuf,
    pub configuration_file: PathBuf,
}

pub struct SudachiAnalyzer {
    dictionary: Arc<JapaneseDictionary>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadingToken {
    pub surface: String,
    pub reading: String,
    pub part_of_speech: Vec<String>,
    pub out_of_vocabulary: bool,
}

pub trait ReadingAnalyzer {
    fn tokenize(&mut self, text: &str) -> Result<Vec<ReadingToken>>;
}

impl SudachiAnalyzer {
    pub fn open(paths: &SudachiPaths) -> Result<Self> {
        if !paths.system_dictionary.is_absolute()
            || !paths.system_dictionary.is_file()
            || !paths.resources_directory.is_absolute()
            || !paths.resources_directory.is_dir()
            || !paths.configuration_file.is_absolute()
            || !paths.configuration_file.is_file()
        {
            return Err(failure("E-VOICE-DICTIONARY"));
        }
        // 外部定義が欠けたときに上流の開発用resource探索へ降格しない。
        for filename in ["char.def", "unk.def", "rewrite.def"] {
            if !paths.resources_directory.join(filename).is_file() {
                return Err(failure("E-VOICE-DICTIONARY"));
            }
        }
        let config = Config::new(
            Some(paths.configuration_file.clone()),
            Some(paths.resources_directory.clone()),
            Some(paths.system_dictionary.clone()),
        )
        .map_err(|_| failure("E-VOICE-DICTIONARY"))?;
        let dictionary =
            JapaneseDictionary::from_cfg(&config).map_err(|_| failure("E-VOICE-DICTIONARY"))?;
        Ok(Self {
            dictionary: Arc::new(dictionary),
        })
    }
}

impl ReadingAnalyzer for SudachiAnalyzer {
    fn tokenize(&mut self, text: &str) -> Result<Vec<ReadingToken>> {
        let mut tokenizer = StatefulTokenizer::new(self.dictionary.clone(), Mode::C);
        tokenizer.reset().push_str(text);
        tokenizer
            .do_tokenize()
            .map_err(|_| failure("E-VOICE-READING"))?;
        let mut results = MorphemeList::empty(self.dictionary.clone());
        results
            .collect_results(&mut tokenizer)
            .map_err(|_| failure("E-VOICE-READING"))?;
        Ok(results
            .iter()
            .map(|token| ReadingToken {
                surface: token.surface().to_string(),
                reading: token.reading_form().to_owned(),
                part_of_speech: token.part_of_speech().to_vec(),
                out_of_vocabulary: token.is_oov(),
            })
            .collect())
    }
}

#[derive(Clone, Debug)]
pub struct ReadingPolicy {
    pub mode: ReadingMode,
    pub minimum_noun_characters: usize,
}

/// 共通 DB の順序を受け取り、同じ長さの置換は入力順を維持する。
#[derive(Clone, Default)]
pub struct ReadingDictionary {
    pub base: Vec<(String, String)>,
    pub user: Vec<(String, String)>,
    pub candidates: BTreeMap<String, ReadingCandidate>,
}

impl ReadingDictionary {
    pub fn load(store: &Store) -> Result<Self> {
        let mut result = Self::default();
        for entry in store.global_repository().list::<ReadingEntry>()? {
            let target = match entry.source.as_str() {
                "base" => &mut result.base,
                "user" => &mut result.user,
                _ => return Err(failure("E-VOICE-DICTIONARY")),
            };
            target.push((entry.surface, entry.reading));
        }
        for candidate in store.global_repository().list::<ReadingCandidate>()? {
            result
                .candidates
                .insert(candidate.surface.clone(), candidate);
        }
        result.validate()?;
        Ok(result)
    }
    pub fn validate(&self) -> Result<()> {
        for entries in [&self.base, &self.user] {
            let mut seen = BTreeSet::new();
            for (surface, reading) in entries {
                if surface.is_empty()
                    || reading.is_empty()
                    || !seen.insert(surface)
                    || surface.chars().any(char::is_control)
                    || reading.chars().any(char::is_control)
                {
                    return Err(failure("E-VOICE-DICTIONARY"));
                }
            }
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct ReadingReport {
    pub readings: BTreeMap<String, String>,
    pub applied_base: BTreeSet<String>,
    pub applied_user: BTreeSet<String>,
    pub applied_auto: BTreeSet<String>,
    pub skipped: BTreeSet<String>,
    pub proposed_entries: Vec<ReadingEntry>,
    pub proposed_candidates: Vec<ReadingCandidate>,
    pub inspections: Vec<ReadingInspection>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InspectionReason {
    ProperNoun,
    Number,
    Latin,
    UnknownWord,
    MissingReading,
    UnsafePartOfSpeech,
}

/// LLM 点検の入力候補。音声層から LLM を呼ばず、字幕の原文も変更しない。
#[derive(Clone)]
pub struct ReadingInspection {
    pub surface: String,
    pub reading: String,
    pub reason: InspectionReason,
    pub review_required: bool,
}

impl ReadingReport {
    /// 保存は typed repository を通す。呼出側が点検結果を確認してから明示適用する。
    pub fn persist_proposals(&self, store: &Store) -> Result<()> {
        let repository = store.global_repository();
        for entry in &self.proposed_entries {
            let key = ReadingEntryKey {
                surface: entry.surface.clone(),
                source: entry.source.clone(),
            };
            if let Some(existing) = repository.get::<ReadingEntry>(&key)? {
                if existing.reading != entry.reading {
                    return Err(failure("E-VOICE-DICTIONARY"));
                }
                // 既存のアクセント編集や更新日時を、自動学習で初期化しない。
            } else {
                repository.save(entry)?;
            }
        }
        for candidate in &self.proposed_candidates {
            let key = ReadingCandidateKey {
                surface: candidate.surface.clone(),
            };
            if repository.get::<ReadingCandidate>(&key)?.is_none() {
                repository.save(candidate)?;
            }
        }
        Ok(())
    }
}

pub struct ReadingNormalizer<A> {
    channel: ChannelId,
    policy: ReadingPolicy,
    dictionary: ReadingDictionary,
    analyzer: Option<A>,
}

impl<A: ReadingAnalyzer> ReadingNormalizer<A> {
    pub fn new(
        channel: ChannelId,
        policy: ReadingPolicy,
        dictionary: ReadingDictionary,
        analyzer: Option<A>,
    ) -> Result<Self> {
        dictionary.validate()?;
        if policy.minimum_noun_characters == 0
            || policy.mode == ReadingMode::SafeAuto && analyzer.is_none()
        {
            return Err(failure("E-VOICE-DICTIONARY"));
        }
        Ok(Self {
            channel,
            policy,
            dictionary,
            analyzer,
        })
    }

    pub fn normalize(
        &mut self,
        channel: &ChannelId,
        texts: &[String],
        at: &Timestamp,
    ) -> Result<ReadingReport> {
        if &self.channel != channel {
            return Err(failure("E-VOICE-CHANNEL"));
        }
        let before = self.dictionary.clone();
        let result = (|| {
            let mut report = ReadingReport::default();
            for text in texts {
                let value = match self.policy.mode {
                    ReadingMode::Off => text.clone(),
                    ReadingMode::Dictionary => self.dictionary_only(text, &mut report),
                    ReadingMode::SafeAuto => self.safe_auto(text, at, &mut report)?,
                };
                report.readings.insert(text.clone(), value);
            }
            Ok(report)
        })();
        if result.is_err() {
            // バッチ途中の解析失敗では、未確定の自動学習も保持しない。
            self.dictionary = before;
        }
        result
    }

    fn dictionary_only(&self, text: &str, report: &mut ReadingReport) -> String {
        let mut merged = self.dictionary.user.clone();
        for (surface, reading) in &self.dictionary.base {
            if let Some(entry) = merged.iter_mut().find(|entry| &entry.0 == surface) {
                entry.1 = reading.clone();
            } else {
                merged.push((surface.clone(), reading.clone()));
            }
        }
        longest_first(&mut merged);
        let mut result = text.to_owned();
        for (surface, reading) in merged {
            if result.contains(&surface) {
                result = result.replace(&surface, &reading);
                let target = if self.dictionary.base.iter().any(|entry| entry.0 == surface) {
                    &mut report.applied_base
                } else {
                    &mut report.applied_user
                };
                target.insert(surface);
            }
        }
        result
    }

    fn safe_auto(
        &mut self,
        text: &str,
        at: &Timestamp,
        report: &mut ReadingReport,
    ) -> Result<String> {
        let mut pre_text = text.to_owned();
        let mut base = self.dictionary.base.clone();
        longest_first(&mut base);
        for (surface, reading) in base {
            if pre_text.contains(&surface) {
                pre_text = pre_text.replace(&surface, &reading);
                report.applied_base.insert(surface);
            }
        }
        let analyzer = self
            .analyzer
            .as_mut()
            .ok_or_else(|| failure("E-VOICE-DICTIONARY"))?;
        let tokens = analyzer.tokenize(&pre_text)?;
        // 解析器の欠落を空文字で継続せず、原文が分割結果で完全に復元することを要求する。
        if tokens
            .iter()
            .map(|token| token.surface.as_str())
            .collect::<String>()
            != pre_text
        {
            return Err(failure("E-VOICE-READING"));
        }
        let mut output = String::new();
        for token in tokens {
            let surface = &token.surface;
            let pos1 = token
                .part_of_speech
                .first()
                .ok_or_else(|| failure("E-VOICE-READING"))?;
            let pos2 = token
                .part_of_speech
                .get(1)
                .ok_or_else(|| failure("E-VOICE-READING"))?;
            if let Some((_, reading)) = self
                .dictionary
                .user
                .iter()
                .find(|entry| &entry.0 == surface)
            {
                output.push_str(reading);
                report.applied_user.insert(surface.clone());
                continue;
            }
            let has_kanji = surface
                .chars()
                .any(|character| ('\u{4e00}'..='\u{9fff}').contains(&character));
            let reading = katakana_to_hiragana(&token.reading)?;
            let inspection = if token.out_of_vocabulary {
                Some(InspectionReason::UnknownWord)
            } else if pos2 == "固有名詞" {
                Some(InspectionReason::ProperNoun)
            } else if surface.chars().any(|value| value.is_ascii_digit()) || pos2 == "数詞" {
                Some(InspectionReason::Number)
            } else if surface.chars().any(|value| value.is_ascii_alphabetic()) {
                Some(InspectionReason::Latin)
            } else {
                None
            };
            if let Some(reason) = inspection {
                report.inspections.push(ReadingInspection {
                    surface: surface.clone(),
                    reading: reading.clone(),
                    reason,
                    review_required: true,
                });
            }
            if surface.chars().count() == 1 && has_kanji {
                report.skipped.insert(surface.clone());
                output.push_str(surface);
                continue;
            }
            if ["動詞", "形容詞", "助詞", "助動詞", "補助記号", "記号"].contains(&pos1.as_str())
                || !has_kanji
            {
                output.push_str(surface);
                continue;
            }
            if token.reading.is_empty() || token.reading == "*" {
                report.skipped.insert(surface.clone());
                report.inspections.push(ReadingInspection {
                    surface: surface.clone(),
                    reading: reading.clone(),
                    reason: InspectionReason::MissingReading,
                    review_required: true,
                });
                output.push_str(surface);
                continue;
            }
            if pos1 == "名詞"
                && ((surface.chars().count() >= self.policy.minimum_noun_characters
                    && pos2 != "数詞")
                    || pos2 == "固有名詞")
            {
                self.dictionary
                    .user
                    .push((surface.clone(), reading.clone()));
                report.proposed_entries.push(ReadingEntry {
                    surface: surface.clone(),
                    source: "user".into(),
                    reading: reading.clone(),
                    accent_json: serde_json::Value::Null,
                    updated_at: at.clone(),
                });
                report.applied_auto.insert(surface.clone());
                output.push_str(&reading);
                continue;
            }
            if !self.dictionary.candidates.contains_key(surface) {
                let candidate = ReadingCandidate {
                    surface: surface.clone(),
                    reading: reading.clone(),
                    reason: format!("POS: {pos1},{pos2}"),
                    source: "safe_auto".into(),
                    auto_applied: false,
                    review_required: true,
                    updated_at: at.clone(),
                };
                self.dictionary
                    .candidates
                    .insert(surface.clone(), candidate.clone());
                report.proposed_candidates.push(candidate);
            }
            report.skipped.insert(surface.clone());
            report.inspections.push(ReadingInspection {
                surface: surface.clone(),
                reading,
                reason: InspectionReason::UnsafePartOfSpeech,
                review_required: true,
            });
            output.push_str(surface);
        }
        Ok(output)
    }
}

fn longest_first(entries: &mut [(String, String)]) {
    entries.sort_by_key(|entry| std::cmp::Reverse(entry.0.chars().count()));
}

pub fn katakana_to_hiragana(text: &str) -> Result<String> {
    text.chars()
        .map(|character| {
            if ('\u{30a1}'..='\u{30f6}').contains(&character) {
                // カナの対応は Unicode の固定写像で、調整設定ではない。
                char::from_u32(character as u32 - 0x60).ok_or_else(|| failure("E-VOICE-READING"))
            } else {
                Ok(character)
            }
        })
        .collect()
}
