use cosmic_text::skrifa::{instance::Size, raw::types::Tag, FontRef, GlyphId, MetadataProvider};
use cosmic_text::{
    fontdb, Attrs, Buffer, Color, Family, FontSystem, Metrics, Shaping, Weight, Wrap,
};
use picocast_core::{AppError, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    ops::Range,
    path::PathBuf,
};
use unicode_segmentation::UnicodeSegmentation;

fn failure(code: &str) -> AppError {
    tracing::error!(code, "字幕の文字組みを停止しました");
    AppError::new(
        code,
        "字幕を指定領域に配置できませんでした",
        "文字領域・フォント・禁則・表示時間を確認し、文章または明示設定を修正してください",
    )
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FontSource {
    pub path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TextStyle {
    pub family: String,
    pub font_size: f32,
    pub line_height: f32,
    pub normal_weight: u16,
    pub emphasis_weight: u16,
    pub normal_rgba: [u8; 4],
    pub emphasis_rgba: [u8; 4],
    pub stroke_px: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayoutOptions {
    pub width_px: f32,
    pub height_px: f32,
    pub max_lines_per_cue: usize,
    pub max_graphemes_per_line: usize,
    pub min_graphemes_per_line: usize,
    pub max_input_graphemes: usize,
    pub max_measurements: usize,
    pub allow_inside_phrase_break: bool,
    pub prohibited_line_start: String,
    pub prohibited_line_end: String,
    pub minimum_display_ms: u64,
    pub max_graphemes_per_second: f64,
    pub style: TextStyle,
}
impl LayoutOptions {
    pub fn validate(&self) -> Result<()> {
        let style = &self.style;
        if !self.width_px.is_finite()
            || self.width_px <= 0.0
            || !self.height_px.is_finite()
            || self.height_px <= 0.0
            || self.max_lines_per_cue == 0
            || self.min_graphemes_per_line < 2
            || self.max_graphemes_per_line < self.min_graphemes_per_line
            || self.max_input_graphemes == 0
            || self.max_measurements == 0
            || self.minimum_display_ms == 0
            || !self.max_graphemes_per_second.is_finite()
            || self.max_graphemes_per_second <= 0.0
            || !style.font_size.is_finite()
            || style.font_size <= 0.0
            || !style.line_height.is_finite()
            || style.line_height < style.font_size
            || !style.stroke_px.is_finite()
            || style.stroke_px < 0.0
            || style.family.is_empty()
            || !(1..=1000).contains(&style.normal_weight)
            || !(1..=1000).contains(&style.emphasis_weight)
        {
            return Err(failure("E-SUBTITLE-SETTINGS"));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Emphasis {
    pub start: usize,
    pub end: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StyledRun {
    pub text: String,
    pub emphasized: bool,
    pub rgba: [u8; 4],
    pub weight: u16,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TextLine {
    pub source_start: usize,
    pub source_end: usize,
    pub text: String,
    pub width_px: f32,
    pub origin_x: f32,
    pub origin_y: f32,
    pub height_px: f32,
    pub runs: Vec<StyledRun>,
    pub inside_phrase_break: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubtitleCue {
    pub start_ms: u64,
    pub end_ms: u64,
    pub lines: Vec<TextLine>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubtitleLayout {
    pub cues: Vec<SubtitleCue>,
    pub font_families: Vec<String>,
}

/// フォントを自動探索せず、呼出側が指定したファイルだけを読み込む。
pub struct TextLayoutEngine {
    fonts: FontSystem,
    parser: budouy::Parser,
    families: BTreeSet<String>,
}
impl TextLayoutEngine {
    pub fn new(sources: &[FontSource], locale: String) -> Result<Self> {
        if sources.is_empty() || locale.is_empty() {
            return Err(failure("E-SUBTITLE-FONT"));
        }
        let mut db = fontdb::Database::new();
        for source in sources {
            if !source.path.is_absolute() || !source.path.is_file() {
                return Err(failure("E-SUBTITLE-FONT"));
            }
            db.load_font_file(&source.path)
                .map_err(|_| failure("E-SUBTITLE-FONT"))?;
        }
        let families = db
            .faces()
            .flat_map(|face| face.families.iter().map(|(family, _)| family.clone()))
            .collect::<BTreeSet<_>>();
        if families.is_empty() {
            return Err(failure("E-SUBTITLE-FONT"));
        }
        Ok(Self {
            fonts: FontSystem::new_with_locale_and_db(locale, db),
            parser: budouy::model::load_default_japanese_parser(),
            families,
        })
    }

    pub fn font_families(&self) -> impl Iterator<Item = &str> {
        self.families.iter().map(String::as_str)
    }

    pub fn layout(
        &mut self,
        text: &str,
        emphasis: &[Emphasis],
        start_ms: u64,
        end_ms: u64,
        options: &LayoutOptions,
    ) -> Result<SubtitleLayout> {
        options.validate()?;
        if !self.families.contains(&options.style.family) {
            return Err(failure("E-SUBTITLE-FONT"));
        }
        if text.is_empty()
            || start_ms >= end_ms
            || text.chars().any(|ch| ch.is_control() && ch != '\n')
        {
            return Err(failure("E-SUBTITLE-INPUT"));
        }
        let boundaries = text
            .grapheme_indices(true)
            .map(|(index, _)| index)
            .chain(std::iter::once(text.len()))
            .collect::<BTreeSet<_>>();
        if boundaries.len() - 1 > options.max_input_graphemes {
            return Err(failure("E-SUBTITLE-LIMIT"));
        }
        let mut previous = 0;
        for span in emphasis {
            if span.start < span.end
                && span.start >= previous
                && boundaries.contains(&span.start)
                && boundaries.contains(&span.end)
            {
                previous = span.end;
            } else {
                return Err(failure("E-SUBTITLE-INPUT"));
            }
        }
        let mut measurements = 0;
        let mut lines = Vec::new();
        let mut offset = 0;
        for paragraph in text.split('\n') {
            if paragraph.trim().is_empty() {
                return Err(failure("E-SUBTITLE-INPUT"));
            }
            lines.extend(self.paragraph(
                text,
                offset..offset + paragraph.len(),
                emphasis,
                options,
                &mut measurements,
            )?);
            offset = offset
                .checked_add(paragraph.len() + 1)
                .ok_or_else(|| failure("E-SUBTITLE-LIMIT"))?;
        }
        let max_by_height = (options.height_px / options.style.line_height).floor() as usize;
        let per_cue = options.max_lines_per_cue.min(max_by_height);
        if per_cue == 0 {
            return Err(failure("E-SUBTITLE-LAYOUT"));
        }
        let groups = lines.chunks(per_cue).collect::<Vec<_>>();
        let minimum = groups
            .iter()
            .map(|lines| minimum_duration(lines, options))
            .collect::<Result<Vec<_>>>()?;
        let required = minimum.iter().try_fold(0u64, |n, value| {
            n.checked_add(*value)
                .ok_or_else(|| failure("E-SUBTITLE-TIME"))
        })?;
        let available = end_ms - start_ms;
        if required > available {
            return Err(failure("E-SUBTITLE-TIME"));
        }
        let extra = available - required;
        let count = u64::try_from(groups.len()).map_err(|_| failure("E-SUBTITLE-LIMIT"))?;
        let mut cursor = start_ms;
        let mut cues = Vec::new();
        for (index, group) in groups.into_iter().enumerate() {
            let add = extra / count + u64::from((index as u64) < extra % count);
            let next = cursor
                .checked_add(minimum[index])
                .and_then(|n| n.checked_add(add))
                .ok_or_else(|| failure("E-SUBTITLE-TIME"))?;
            cues.push(SubtitleCue {
                start_ms: cursor,
                end_ms: next,
                lines: group.to_vec(),
            });
            cursor = next;
        }
        Ok(SubtitleLayout {
            cues,
            font_families: self.families.iter().cloned().collect(),
        })
    }

    fn paragraph(
        &mut self,
        source: &str,
        range: Range<usize>,
        emphasis: &[Emphasis],
        options: &LayoutOptions,
        measurements: &mut usize,
    ) -> Result<Vec<TextLine>> {
        let text = &source[range.clone()];
        let positions = text
            .grapheme_indices(true)
            .map(|(index, _)| index)
            .chain(std::iter::once(text.len()))
            .collect::<Vec<_>>();
        let char_positions = text
            .char_indices()
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        let phrase = self
            .parser
            .parse_boundaries(text)
            .into_iter()
            .map(|index| {
                char_positions
                    .get(index)
                    .copied()
                    .ok_or_else(|| failure("E-SUBTITLE-INPUT"))
            })
            .collect::<Result<BTreeSet<_>>>()?;
        let mut best = vec![None::<(usize, usize, f64, usize)>; positions.len()];
        best[positions.len() - 1] = Some((0, 0, 0.0, positions.len() - 1));
        let mut measured = BTreeMap::new();
        for begin in (0..positions.len() - 1).rev() {
            for end in begin + 1
                ..positions.len().min(
                    begin
                        .saturating_add(options.max_graphemes_per_line)
                        .saturating_add(1),
                )
            {
                let segment = &text[positions[begin]..positions[end]];
                let visible = segment
                    .graphemes(true)
                    .filter(|cluster| !cluster.trim().is_empty())
                    .count();
                if visible < options.min_graphemes_per_line || !legal_edges(segment, options) {
                    continue;
                }
                let inside = end < positions.len() - 1
                    && !phrase.contains(&positions[end])
                    && !segment.ends_with(char::is_whitespace);
                if inside && !options.allow_inside_phrase_break {
                    continue;
                }
                let Some((tail_inside, tail_lines, tail_ragged, _)) = best[end] else {
                    continue;
                };
                *measurements = measurements
                    .checked_add(1)
                    .ok_or_else(|| failure("E-SUBTITLE-LIMIT"))?;
                if *measurements > options.max_measurements {
                    return Err(failure("E-SUBTITLE-LIMIT"));
                }
                let line = self.measure(
                    source,
                    range.start + positions[begin]..range.start + positions[end],
                    emphasis,
                    inside,
                    options,
                )?;
                if line.width_px > options.width_px || line.height_px > options.style.line_height {
                    continue;
                }
                let score = (
                    tail_inside + usize::from(inside),
                    tail_lines + 1,
                    tail_ragged + f64::from(options.width_px - line.width_px).powi(2),
                    end,
                );
                if best[begin].is_none_or(|old| (score.0, score.1, score.2) < (old.0, old.1, old.2))
                {
                    best[begin] = Some(score);
                    measured.insert((begin, end), line);
                }
            }
        }
        if best[0].is_none() {
            return Err(failure("E-SUBTITLE-LAYOUT"));
        }
        let mut index = 0;
        let mut output = Vec::new();
        while index < positions.len() - 1 {
            let next = best[index].ok_or_else(|| failure("E-SUBTITLE-LAYOUT"))?.3;
            output.push(
                measured
                    .remove(&(index, next))
                    .ok_or_else(|| failure("E-SUBTITLE-LAYOUT"))?,
            );
            index = next;
        }
        Ok(output)
    }

    fn measure(
        &mut self,
        source: &str,
        range: Range<usize>,
        emphasis: &[Emphasis],
        inside_phrase_break: bool,
        options: &LayoutOptions,
    ) -> Result<TextLine> {
        let style = &options.style;
        let text = &source[range.clone()];
        let mut splits = vec![range.start, range.end];
        for span in emphasis {
            if span.start > range.start && span.start < range.end {
                splits.push(span.start);
            }
            if span.end > range.start && span.end < range.end {
                splits.push(span.end);
            }
        }
        splits.sort_unstable();
        splits.dedup();
        let runs = splits
            .windows(2)
            .map(|bounds| {
                let emphasized = emphasis
                    .iter()
                    .any(|span| span.start <= bounds[0] && span.end >= bounds[1]);
                StyledRun {
                    text: source[bounds[0]..bounds[1]].into(),
                    emphasized,
                    rgba: if emphasized {
                        style.emphasis_rgba
                    } else {
                        style.normal_rgba
                    },
                    weight: if emphasized {
                        style.emphasis_weight
                    } else {
                        style.normal_weight
                    },
                }
            })
            .collect::<Vec<_>>();
        let attrs = Attrs::new()
            .family(Family::Name(&style.family))
            .weight(Weight(style.normal_weight));
        let content_height = style.line_height - style.stroke_px * 2.0;
        if content_height < style.font_size {
            return Err(failure("E-SUBTITLE-SETTINGS"));
        }
        let mut buffer = Buffer::new(
            &mut self.fonts,
            Metrics::new(style.font_size, content_height),
        );
        buffer.set_wrap(Wrap::None);
        buffer.set_rich_text(
            runs.iter().map(|run| {
                (
                    run.text.as_str(),
                    attrs.clone().weight(Weight(run.weight)).color(Color::rgba(
                        run.rgba[0],
                        run.rgba[1],
                        run.rgba[2],
                        run.rgba[3],
                    )),
                )
            }),
            &attrs,
            Shaping::Advanced,
            None,
        );
        buffer.shape_until_scroll(&mut self.fonts, false);
        let mut width = 0.0f32;
        let mut height = 0.0f32;
        let mut min_x = 0.0f32;
        let mut min_y = 0.0f32;
        let mut max_y = content_height;
        for run in buffer.layout_runs() {
            width = width.max(run.line_w);
            height += run.line_height;
            for glyph in run.glyphs {
                if glyph.glyph_id == 0 {
                    return Err(failure("E-SUBTITLE-FONT"));
                }
                let face_index = self
                    .fonts
                    .db()
                    .face(glyph.font_id)
                    .ok_or_else(|| failure("E-SUBTITLE-FONT"))?
                    .index;
                let font = self
                    .fonts
                    .get_font(glyph.font_id, glyph.font_weight)
                    .ok_or_else(|| failure("E-SUBTITLE-FONT"))?;
                let font_ref = FontRef::from_index(font.data(), face_index)
                    .map_err(|_| failure("E-SUBTITLE-FONT"))?;
                let location = font_ref
                    .axes()
                    .location([(Tag::new(b"wght"), f32::from(glyph.font_weight.0))]);
                let bounds = font_ref
                    .glyph_metrics(Size::new(glyph.font_size), &location)
                    .bounds(GlyphId::new(u32::from(glyph.glyph_id)))
                    .ok_or_else(|| failure("E-SUBTITLE-FONT"))?;
                let x = glyph.x + glyph.font_size * glyph.x_offset;
                let baseline = run.line_y + glyph.y - glyph.font_size * glyph.y_offset;
                min_x = min_x.min((x + bounds.x_min).floor());
                width = width.max((x + bounds.x_max).ceil());
                min_y = min_y.min((baseline - bounds.y_max).floor());
                max_y = max_y.max((baseline - bounds.y_min).ceil());
            }
        }
        if !width.is_finite() || width <= 0.0 || !height.is_finite() {
            return Err(failure("E-SUBTITLE-FONT"));
        }
        Ok(TextLine {
            source_start: range.start,
            source_end: range.end,
            text: text.into(),
            width_px: width - min_x + style.stroke_px * 2.0,
            origin_x: style.stroke_px - min_x,
            origin_y: style.stroke_px - min_y,
            height_px: max_y - min_y + style.stroke_px * 2.0,
            runs,
            inside_phrase_break,
        })
    }
}

pub fn legal_edges(text: &str, options: &LayoutOptions) -> bool {
    let trimmed = text.trim();
    trimmed
        .chars()
        .next()
        .is_some_and(|ch| !options.prohibited_line_start.contains(ch))
        && trimmed
            .chars()
            .next_back()
            .is_some_and(|ch| !options.prohibited_line_end.contains(ch))
}
fn minimum_duration(lines: &[TextLine], options: &LayoutOptions) -> Result<u64> {
    let count = lines
        .iter()
        .map(|line| {
            line.text
                .graphemes(true)
                .filter(|cluster| !cluster.trim().is_empty())
                .count()
        })
        .sum::<usize>();
    let reading = (count as f64 / options.max_graphemes_per_second * 1000.0).ceil();
    if !reading.is_finite() || reading >= u64::MAX as f64 {
        return Err(failure("E-SUBTITLE-TIME"));
    }
    Ok(options.minimum_display_ms.max(reading as u64))
}

#[cfg(test)]
#[path = "subtitle_tests.rs"]
mod tests;
