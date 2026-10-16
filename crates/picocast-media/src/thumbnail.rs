//! サムネイルの実測配置と縮小画像の検査。生成や課金は pipeline が所有する。
use crate::{
    character::{composite_at, resize_premultiplied},
    subtitle::{LayoutOptions, SubtitleLayout, SubtitleRasterOptions, TextLayoutEngine},
};
use image::{DynamicImage, ImageFormat, Rgba, RgbaImage};
use picocast_core::{AppError, ChannelId, Result};
use serde::{Deserialize, Serialize};
use std::io::Cursor;

fn failure() -> AppError {
    tracing::error!(
        code = "E-THUMBNAIL-SETTINGS",
        "サムネイルの配置設定または画像が不正です"
    );
    AppError::new(
        "E-THUMBNAIL-SETTINGS",
        "サムネイルを配置できません",
        "チャンネル・画像寸法・文字領域・縮小検査の設定を確認してください",
    )
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Placement {
    pub left: u32,
    pub top: u32,
    pub width: u32,
    pub height: u32,
}
impl Placement {
    fn fits(&self, width: u32, height: u32) -> bool {
        self.width > 0
            && self.height > 0
            && self
                .left
                .checked_add(self.width)
                .is_some_and(|x| x <= width)
            && self
                .top
                .checked_add(self.height)
                .is_some_and(|y| y <= height)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadabilityOptions {
    pub preview_width: u32,
    pub preview_height: u32,
    pub minimum_glyph_height_px: u32,
    pub minimum_contrast_ratio: f64,
    pub minimum_passing_fraction: f64,
    pub minimum_mask_alpha: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ThumbnailTemplate {
    pub channel_id: ChannelId,
    pub version: i64,
    pub width: u32,
    pub height: u32,
    pub maximum_pixels: u64,
    pub text_left: u32,
    pub text_top: u32,
    pub panel_rgba: [u8; 4],
    pub character: Option<Placement>,
    pub layout_duration_ms: u64,
    pub layout: LayoutOptions,
    pub raster: SubtitleRasterOptions,
    pub readability: ReadabilityOptions,
}
impl ThumbnailTemplate {
    pub fn validate(&self, channel: &ChannelId) -> Result<()> {
        self.layout.validate()?;
        let r = &self.readability;
        let rect = Placement {
            left: self.text_left,
            top: self.text_top,
            width: self.layout.width_px.ceil() as u32,
            height: self.layout.height_px.ceil() as u32,
        };
        if &self.channel_id != channel
            || self.version < 1
            || self.width == 0
            || self.height == 0
            || u64::from(self.width) * u64::from(self.height) > self.maximum_pixels
            || !rect.fits(self.width, self.height)
            || self
                .character
                .as_ref()
                .is_some_and(|p| !p.fits(self.width, self.height))
            || self.layout_duration_ms == 0
            || r.preview_width == 0
            || r.preview_height == 0
            || r.preview_width > self.width
            || r.preview_height > self.height
            || u64::from(r.preview_width) * u64::from(self.height)
                != u64::from(r.preview_height) * u64::from(self.width)
            || r.minimum_glyph_height_px == 0
            || r.minimum_mask_alpha == 0
            || !r.minimum_contrast_ratio.is_finite()
            || !(1.0..=21.0).contains(&r.minimum_contrast_ratio)
            || !r.minimum_passing_fraction.is_finite()
            || r.minimum_passing_fraction <= 0.0
            || r.minimum_passing_fraction > 1.0
        {
            return Err(failure());
        }
        Ok(())
    }
}

pub struct CharacterOverlay<'a> {
    pub channel_id: &'a ChannelId,
    pub image: &'a RgbaImage,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ThumbnailIssue {
    TextDoesNotFit,
    TextLost,
    TextTooSmall,
    LowContrast,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThumbnailMetrics {
    pub text: String,
    pub line_heights_px: Vec<u32>,
    pub contrast_passing_fraction: f64,
    pub overflowing_pixels: u64,
}
pub struct ComposedThumbnail {
    pub image: RgbaImage,
    pub preview: RgbaImage,
    pub layout: SubtitleLayout,
    pub metrics: ThumbnailMetrics,
}
impl ComposedThumbnail {
    pub fn preview_png(&self) -> Result<Vec<u8>> {
        encode_png(&self.preview)
    }
    pub fn png(&self) -> Result<Vec<u8>> {
        encode_png(&self.image)
    }
}
fn encode_png(image: &RgbaImage) -> Result<Vec<u8>> {
    let mut bytes = Cursor::new(Vec::new());
    DynamicImage::ImageRgba8(image.clone())
        .write_to(&mut bytes, ImageFormat::Png)
        .map_err(|error| {
            tracing::error!(%error, "サムネイルのPNG変換が失敗しました");
            failure()
        })?;
    Ok(bytes.into_inner())
}
pub enum CompositionOutcome {
    Ready(Box<ComposedThumbnail>),
    Hold(Vec<ThumbnailIssue>),
}
fn hold(issue: ThumbnailIssue) -> CompositionOutcome {
    tracing::warn!(
        ?issue,
        code = "E-THUMBNAIL-HOLD",
        "サムネイル候補を保留しました"
    );
    CompositionOutcome::Hold(vec![issue])
}

#[tracing::instrument(skip_all,fields(channel_id=channel.as_str()))]
pub fn compose(
    engine: &mut TextLayoutEngine,
    channel: &ChannelId,
    template: &ThumbnailTemplate,
    text: &str,
    background: &RgbaImage,
    character: Option<CharacterOverlay<'_>>,
) -> Result<CompositionOutcome> {
    template.validate(channel)?;
    if background.dimensions() != (template.width, template.height)
        || background.pixels().any(|p| p[3] != 255)
        || character.is_some() != template.character.is_some()
    {
        return Err(failure());
    }
    let layout = match engine.layout(text, &[], 0, template.layout_duration_ms, &template.layout) {
        Ok(layout) => layout,
        Err(error)
            if matches!(
                error.code.as_str(),
                "E-SUBTITLE-LAYOUT" | "E-SUBTITLE-LIMIT" | "E-SUBTITLE-TIME"
            ) =>
        {
            return Ok(hold(ThumbnailIssue::TextDoesNotFit))
        }
        Err(error) => return Err(error),
    };
    if layout.cues.len() != 1 {
        return Ok(hold(ThumbnailIssue::TextDoesNotFit));
    }
    let retained: String = layout.cues[0]
        .lines
        .iter()
        .map(|line| line.text.as_str())
        .collect();
    if retained != text.replace('\n', "") {
        return Ok(hold(ThumbnailIssue::TextLost));
    }
    let raster = engine.rasterize_cue(&layout, 0, &template.raster)?;
    let mut mask_options = template.raster.clone();
    mask_options.stroke_rgba = [0; 4];
    let mask = engine.rasterize_cue(&layout, 0, &mask_options)?;
    let mut canvas = background.clone();
    if let (Some(overlay), Some(p)) = (character, &template.character) {
        if overlay.channel_id != channel
            || overlay.image.width() == 0
            || overlay.image.height() == 0
            || u64::from(overlay.image.width()) * u64::from(overlay.image.height())
                > template.maximum_pixels
        {
            return Err(failure());
        }
        composite_at(
            &mut canvas,
            &resize_premultiplied(overlay.image, p.width, p.height),
            i64::from(p.left),
            i64::from(p.top),
        );
    }
    let panel = RgbaImage::from_pixel(
        raster.image.width(),
        raster.image.height(),
        Rgba(template.panel_rgba),
    );
    composite_at(
        &mut canvas,
        &panel,
        i64::from(template.text_left),
        i64::from(template.text_top),
    );
    let r = &template.readability;
    let before = resize_premultiplied(&canvas, r.preview_width, r.preview_height);
    composite_at(
        &mut canvas,
        &raster.image,
        i64::from(template.text_left),
        i64::from(template.text_top),
    );
    let preview = resize_premultiplied(&canvas, r.preview_width, r.preview_height);
    let mut full_mask = RgbaImage::new(template.width, template.height);
    composite_at(
        &mut full_mask,
        &mask.image,
        i64::from(template.text_left),
        i64::from(template.text_top),
    );
    let preview_mask = resize_premultiplied(&full_mask, r.preview_width, r.preview_height);
    let mut total = 0_u64;
    let mut passing = 0_u64;
    for (x, y, pixel) in preview_mask.enumerate_pixels() {
        if pixel[3] >= r.minimum_mask_alpha {
            total += 1;
            let a = luminance(preview.get_pixel(x, y));
            let b = luminance(before.get_pixel(x, y));
            if (a.max(b) + 0.05) / (a.min(b) + 0.05) >= r.minimum_contrast_ratio {
                passing += 1;
            }
        }
    }
    let scale = f64::from(r.preview_height) / f64::from(template.height);
    let mut heights = Vec::new();
    for index in 0..layout.cues[0].lines.len() {
        let top = ((f64::from(template.text_top)
            + index as f64 * f64::from(template.layout.style.line_height))
            * scale)
            .floor() as u32;
        let bottom = ((f64::from(template.text_top)
            + (index + 1) as f64 * f64::from(template.layout.style.line_height))
            * scale)
            .ceil() as u32;
        let rows: Vec<u32> = (top..bottom.min(r.preview_height))
            .filter(|y| {
                (0..r.preview_width)
                    .any(|x| preview_mask.get_pixel(x, *y)[3] >= r.minimum_mask_alpha)
            })
            .collect();
        heights.push(rows.first().zip(rows.last()).map_or(0, |(a, b)| b - a + 1));
    }
    if heights
        .iter()
        .any(|height| *height < r.minimum_glyph_height_px)
    {
        return Ok(hold(ThumbnailIssue::TextTooSmall));
    }
    let fraction = if total == 0 {
        0.0
    } else {
        passing as f64 / total as f64
    };
    if fraction < r.minimum_passing_fraction {
        return Ok(hold(ThumbnailIssue::LowContrast));
    }
    Ok(CompositionOutcome::Ready(Box::new(ComposedThumbnail {
        image: canvas,
        preview,
        layout,
        metrics: ThumbnailMetrics {
            text: text.into(),
            line_heights_px: heights,
            contrast_passing_fraction: fraction,
            overflowing_pixels: 0,
        },
    })))
}
fn luminance(pixel: &Rgba<u8>) -> f64 {
    let linear = |v: u8| {
        let v = f64::from(v) / 255.0;
        if v <= 0.04045 {
            v / 12.92
        } else {
            ((v + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * linear(pixel[0]) + 0.7152 * linear(pixel[1]) + 0.0722 * linear(pixel[2])
}

#[cfg(test)]
#[path = "thumbnail_tests.rs"]
mod tests;
