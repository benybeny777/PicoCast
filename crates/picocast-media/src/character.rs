//! チャンネル内の検証済みCASレイヤーだけを使う、画素と音素時刻の合成境界。
use image::{imageops::FilterType, ImageEncoder, Rgba, RgbaImage};
use picocast_core::{fsutil, AppError, ChannelId, Result};
use picocast_store::{
    character_layers,
    repository::{Asset, AssetKey, AssetRef, Character, CharacterKey},
    Store,
};
use picocast_voice::SynthesisResult;
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read, path::Path, time::Duration};

fn failure(code: &str) -> AppError {
    tracing::error!(code, "キャラクター合成を停止しました");
    AppError::new(
        code,
        "キャラクター画像または口の時刻を合成できませんでした",
        "チャンネル・登録済みレイヤー・画素検査・音素時刻と描画設定を確認してください",
    )
}

#[derive(Clone, Debug)]
pub struct CharacterLimits {
    pub maximum_file_bytes: usize,
    pub maximum_pixels: u64,
    pub maximum_layers: usize,
    pub maximum_variants: usize,
    pub maximum_decoded_bytes: u64,
}
impl CharacterLimits {
    fn validate(&self) -> Result<()> {
        if self.maximum_file_bytes == 0
            || self.maximum_pixels == 0
            || self.maximum_layers == 0
            || self.maximum_variants == 0
            || self.maximum_decoded_bytes == 0
        {
            return Err(failure("E-CHARACTER-CONFIG"));
        }
        Ok(())
    }
    fn image_bytes(&self, width: u32, height: u32) -> Result<u64> {
        let pixels = u64::from(width) * u64::from(height);
        if width == 0 || height == 0 || pixels > self.maximum_pixels {
            return Err(failure("E-CHARACTER-ASSET"));
        }
        pixels
            .checked_mul(4)
            .filter(|bytes| *bytes <= self.maximum_decoded_bytes)
            .ok_or_else(|| failure("E-CHARACTER-ASSET"))
    }
}

#[derive(Deserialize)]
struct ImageRecord {
    path: String,
    sha256: String,
    bytes: u64,
}
#[derive(Deserialize)]
struct LayerRecord {
    id: String,
    parent_id: Option<String>,
    is_group: bool,
    image: ImageRecord,
}
#[derive(Deserialize)]
struct VariantRecord {
    id: String,
    visibility: BTreeMap<String, bool>,
    image: ImageRecord,
}
#[derive(Deserialize)]
struct Canvas {
    width: u32,
    height: u32,
}
/// 全体の意味検証はR1の所有者に委ね、描画で読むフィールドだけを保持する。
#[derive(Deserialize)]
struct Manifest {
    canvas: Canvas,
    pixel_tolerance: u8,
    layers: Vec<LayerRecord>,
    variants: Vec<VariantRecord>,
}

struct Layer {
    id: String,
    parent_id: Option<String>,
    image: Option<RgbaImage>,
}

pub struct CharacterLayers {
    channel: ChannelId,
    character_id: String,
    manifest: Manifest,
    layers: Vec<Layer>,
    limits: CharacterLimits,
}

impl CharacterLayers {
    pub fn load(
        store: &Store,
        channel: &ChannelId,
        character_id: &str,
        assets_root: &Path,
        limits: CharacterLimits,
    ) -> Result<Self> {
        limits.validate()?;
        if !assets_root.is_absolute() {
            return Err(failure("E-CHARACTER-CONFIG"));
        }
        let repository = store.repository(channel)?;
        let character = repository
            .get::<Character>(&CharacterKey {
                channel_id: channel.clone(),
                id: character_id.to_owned(),
            })?
            .ok_or_else(|| failure("E-CHARACTER-CHANNEL"))?;
        let hash = character
            .layer_manifest_sha256
            .ok_or_else(|| failure("E-CHARACTER-ASSET"))?;
        let references: Vec<_> = repository
            .list::<AssetRef>()?
            .into_iter()
            .filter(|entry| entry.owner_kind == "character" && entry.owner_id == character_id)
            .collect();
        let mut assets = BTreeMap::new();
        for reference in &references {
            let asset = store
                .global_repository()
                .get::<Asset>(&AssetKey {
                    sha256: reference.sha256.clone(),
                })?
                .ok_or_else(|| failure("E-CHARACTER-ASSET"))?;
            assets.insert(asset.sha256.clone(), asset);
        }
        let root = assets_root
            .canonicalize()
            .map_err(|_| failure("E-CHARACTER-ASSET"))?;
        let bytes = read_asset(
            &root,
            &references,
            &assets,
            "psd:manifest",
            &hash,
            None,
            &limits,
        )?;
        character_layers::validate_manifest(&bytes)?;
        let manifest: Manifest =
            serde_json::from_slice(&bytes).map_err(|_| failure("E-CHARACTER-ASSET"))?;
        let image_bytes = limits.image_bytes(manifest.canvas.width, manifest.canvas.height)?;
        let raster_count = manifest
            .layers
            .iter()
            .filter(|layer| !layer.is_group)
            .count();
        if manifest.layers.len() > limits.maximum_layers
            || manifest.variants.len() > limits.maximum_variants
            || image_bytes
                .checked_mul(raster_count as u64 + 2)
                .is_none_or(|bytes| bytes > limits.maximum_decoded_bytes)
        {
            return Err(failure("E-CHARACTER-ASSET"));
        }
        let mut layers = Vec::new();
        for layer in &manifest.layers {
            let bytes = read_asset(
                &root,
                &references,
                &assets,
                &format!("psd:{}", layer.image.path),
                &layer.image.sha256,
                Some(layer.image.bytes),
                &limits,
            )?;
            let image = if layer.is_group {
                None
            } else {
                Some(decode_png(&bytes, &manifest.canvas, &limits)?)
            };
            layers.push(Layer {
                id: layer.id.clone(),
                parent_id: layer.parent_id.clone(),
                image,
            });
        }
        // 再合成と登録済みの旧版基準画像を比較する。画質不一致を無言で許可しない。
        for variant in &manifest.variants {
            let bytes = read_asset(
                &root,
                &references,
                &assets,
                &format!("psd:{}", variant.image.path),
                &variant.image.sha256,
                Some(variant.image.bytes),
                &limits,
            )?;
            let reference = decode_png(&bytes, &manifest.canvas, &limits)?;
            let composed = compose_layers(&layers, &variant.visibility, &manifest.canvas)?;
            if maximum_difference(&composed, &reference)? > manifest.pixel_tolerance {
                return Err(failure("E-CHARACTER-PIXELS"));
            }
        }
        Ok(Self {
            channel: channel.clone(),
            character_id: character_id.to_owned(),
            manifest,
            layers,
            limits,
        })
    }

    pub fn prepare(self, binding: &CharacterBinding) -> Result<PreparedCharacter> {
        binding.validate()?;
        let base = self.variant(&binding.base_variant)?.visibility.clone();
        let mouth_options = if binding.lipsync {
            vec![MouthShape::Closed, MouthShape::Half, MouthShape::Open]
        } else {
            vec![MouthShape::Closed]
        };
        let blink_options = if binding.blink {
            vec![false, true]
        } else {
            vec![false]
        };
        let image_bytes = self
            .limits
            .image_bytes(self.manifest.canvas.width, self.manifest.canvas.height)?;
        let resident_layers = self
            .layers
            .iter()
            .filter(|layer| layer.image.is_some())
            .count() as u64;
        let output_count = mouth_options.len() * blink_options.len() + binding.expressions.len();
        if image_bytes
            .checked_mul(resident_layers + output_count as u64)
            .is_none_or(|bytes| bytes > self.limits.maximum_decoded_bytes)
        {
            return Err(failure("E-CHARACTER-ASSET"));
        }
        let mut frames = BTreeMap::new();
        for mouth in mouth_options {
            let mouth_id = match mouth {
                MouthShape::Closed => None,
                MouthShape::Half => binding.mouth_half_variant.as_deref(),
                MouthShape::Open => binding.mouth_open_variant.as_deref(),
            };
            for blink in &blink_options {
                let mut visibility = base.clone();
                let mut altered = BTreeMap::new();
                let mouth_changes =
                    self.merge_variant(&base, &mut visibility, &mut altered, mouth_id)?;
                let blink_id = if *blink {
                    binding.blink_variant.as_deref()
                } else {
                    None
                };
                let blink_changes =
                    self.merge_variant(&base, &mut visibility, &mut altered, blink_id)?;
                frames.insert(
                    (mouth, *blink),
                    CachedFrame {
                        image: compose_layers(&self.layers, &visibility, &self.manifest.canvas)?,
                        mouth_changes,
                        blink_changes,
                    },
                );
            }
        }
        let mut expressions = BTreeMap::new();
        for (name, id) in &binding.expressions {
            let variant = self.variant(id)?;
            expressions.insert(
                name.clone(),
                compose_layers(&self.layers, &variant.visibility, &self.manifest.canvas)?,
            );
        }
        Ok(PreparedCharacter {
            channel: self.channel,
            character_id: self.character_id,
            frames,
            expressions,
            limits: self.limits,
            lipsync: binding.lipsync,
            blink: binding.blink,
        })
    }
    fn variant(&self, id: &str) -> Result<&VariantRecord> {
        self.manifest
            .variants
            .iter()
            .find(|variant| variant.id == id)
            .ok_or_else(|| failure("E-CHARACTER-RIG"))
    }
    fn merge_variant(
        &self,
        base: &BTreeMap<String, bool>,
        selected: &mut BTreeMap<String, bool>,
        altered: &mut BTreeMap<String, bool>,
        id: Option<&str>,
    ) -> Result<usize> {
        let Some(id) = id else { return Ok(0) };
        let variant = self.variant(id)?;
        let mut count = 0;
        for (layer, value) in &variant.visibility {
            if base.get(layer) != Some(value) {
                if altered
                    .insert(layer.clone(), *value)
                    .is_some_and(|previous| previous != *value)
                {
                    return Err(failure("E-CHARACTER-RIG"));
                }
                selected.insert(layer.clone(), *value);
                count += 1;
            }
        }
        Ok(count)
    }
}

fn read_asset(
    root: &Path,
    references: &[AssetRef],
    assets: &BTreeMap<String, Asset>,
    role: &str,
    hash: &str,
    expected: Option<u64>,
    limits: &CharacterLimits,
) -> Result<Vec<u8>> {
    if !references
        .iter()
        .any(|entry| entry.role == role && entry.sha256 == hash)
    {
        return Err(failure("E-CHARACTER-CHANNEL"));
    }
    let asset = assets
        .get(hash)
        .ok_or_else(|| failure("E-CHARACTER-ASSET"))?;
    if asset.ext
        != if role == "psd:manifest" {
            "json"
        } else {
            "png"
        }
    {
        return Err(failure("E-CHARACTER-ASSET"));
    }
    let size = u64::try_from(asset.bytes).map_err(|_| failure("E-CHARACTER-ASSET"))?;
    if size == 0
        || size > limits.maximum_file_bytes as u64
        || expected.is_some_and(|expected| size != expected)
    {
        return Err(failure("E-CHARACTER-ASSET"));
    }
    let path = fsutil::content_asset_path(root, hash, &asset.ext)?;
    let metadata = std::fs::symlink_metadata(&path).map_err(|_| failure("E-CHARACTER-ASSET"))?;
    let canonical = path
        .canonicalize()
        .map_err(|_| failure("E-CHARACTER-ASSET"))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || !canonical.starts_with(root) {
        return Err(failure("E-CHARACTER-ASSET"));
    }
    let file = std::fs::File::open(&canonical).map_err(|_| failure("E-CHARACTER-ASSET"))?;
    let mut bytes = Vec::new();
    file.take(size + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| failure("E-CHARACTER-ASSET"))?;
    if bytes.len() as u64 != size || digest_hex(&bytes) != hash {
        return Err(failure("E-CHARACTER-ASSET"));
    }
    Ok(bytes)
}

fn digest_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn decode_png(bytes: &[u8], canvas: &Canvas, limits: &CharacterLimits) -> Result<RgbaImage> {
    limits.image_bytes(canvas.width, canvas.height)?;
    if bytes.get(..16) != Some(&[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82])
        || bytes.get(16..20) != Some(canvas.width.to_be_bytes().as_slice())
        || bytes.get(20..24) != Some(canvas.height.to_be_bytes().as_slice())
        || bytes.get(24..26) != Some(&[8, 6])
    {
        return Err(failure("E-CHARACTER-ASSET"));
    }
    let image = image::load_from_memory_with_format(bytes, image::ImageFormat::Png)
        .map_err(|_| failure("E-CHARACTER-ASSET"))?;
    Ok(image.into_rgba8())
}

fn compose_layers(
    layers: &[Layer],
    selected: &BTreeMap<String, bool>,
    canvas: &Canvas,
) -> Result<RgbaImage> {
    let parents: BTreeMap<_, _> = layers
        .iter()
        .map(|layer| (layer.id.as_str(), layer.parent_id.as_deref()))
        .collect();
    let mut output = RgbaImage::from_pixel(canvas.width, canvas.height, Rgba([255, 255, 255, 0]));
    for layer in layers {
        let Some(image) = &layer.image else { continue };
        let mut visible = *selected
            .get(&layer.id)
            .ok_or_else(|| failure("E-CHARACTER-RIG"))?;
        let mut parent = layer.parent_id.as_deref();
        let mut depth = 0;
        while let Some(id) = parent {
            depth += 1;
            if depth > layers.len() {
                return Err(failure("E-CHARACTER-RIG"));
            }
            visible &= *selected.get(id).ok_or_else(|| failure("E-CHARACTER-RIG"))?;
            parent = *parents.get(id).ok_or_else(|| failure("E-CHARACTER-RIG"))?;
        }
        if visible {
            composite_at(&mut output, image, 0, 0);
        }
    }
    Ok(output)
}

/// Pillow のRGBA8整数丸めに合わせたsource-over。合成の所有者はこの関数だけ。
pub(crate) fn composite_at(destination: &mut RgbaImage, source: &RgbaImage, left: i64, top: i64) {
    for (x, y, foreground) in source.enumerate_pixels() {
        let dx = i64::from(x) + left;
        let dy = i64::from(y) + top;
        if dx < 0
            || dy < 0
            || dx >= i64::from(destination.width())
            || dy >= i64::from(destination.height())
            || foreground[3] == 0
        {
            continue;
        }
        composite_pixel(destination.get_pixel_mut(dx as u32, dy as u32), *foreground);
    }
}

#[inline]
pub(crate) fn composite_pixel(background: &mut Rgba<u8>, foreground: Rgba<u8>) {
    if foreground[3] == 0 {
        return;
    }
    let divide_255 = |value: u32| ((value >> 8) + value) >> 8;
    let front_alpha = u32::from(foreground[3]);
    let combined = front_alpha * 255 + u32::from(background[3]) * (255 - front_alpha);
    let front_weight = front_alpha * 255 * 255 * 128 / combined;
    let back_weight = 255 * 128 - front_weight;
    for channel in 0..3 {
        background[channel] = (divide_255(
            u32::from(foreground[channel]) * front_weight
                + u32::from(background[channel]) * back_weight
                + (128 * 128),
        ) >> 7) as u8;
    }
    background[3] = divide_255(combined + 128) as u8;
}

fn maximum_difference(left: &RgbaImage, right: &RgbaImage) -> Result<u8> {
    if left.dimensions() != right.dimensions() {
        return Err(failure("E-CHARACTER-PIXELS"));
    }
    Ok(left
        .as_raw()
        .iter()
        .zip(right.as_raw())
        .map(|(a, b)| a.abs_diff(*b))
        .fold(0, u8::max))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum MouthShape {
    Closed,
    Half,
    Open,
}

#[derive(Clone, Debug)]
pub struct CharacterBinding {
    pub base_variant: String,
    pub mouth_half_variant: Option<String>,
    pub mouth_open_variant: Option<String>,
    pub blink_variant: Option<String>,
    pub expressions: BTreeMap<String, String>,
    pub lipsync: bool,
    pub blink: bool,
}
impl CharacterBinding {
    fn validate(&self) -> Result<()> {
        if self.base_variant.is_empty()
            || self.lipsync
                && (self.mouth_half_variant.is_none() || self.mouth_open_variant.is_none())
            || self.blink && self.blink_variant.is_none()
            || self.expressions.keys().any(|key| key.is_empty())
        {
            return Err(failure("E-CHARACTER-RIG"));
        }
        Ok(())
    }
}

struct CachedFrame {
    image: RgbaImage,
    mouth_changes: usize,
    blink_changes: usize,
}
pub struct PreparedCharacter {
    channel: ChannelId,
    character_id: String,
    frames: BTreeMap<(MouthShape, bool), CachedFrame>,
    expressions: BTreeMap<String, RgbaImage>,
    limits: CharacterLimits,
    lipsync: bool,
    blink: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct FrameRate {
    pub numerator: u32,
    pub denominator: u32,
}
impl FrameRate {
    pub fn timestamp(&self, frame: u64) -> Result<Duration> {
        if self.numerator == 0 || self.denominator == 0 {
            return Err(failure("E-CHARACTER-TIMING"));
        }
        let nanos = u128::from(frame)
            .checked_mul(u128::from(self.denominator))
            .and_then(|value| value.checked_mul(1_000_000_000))
            .ok_or_else(|| failure("E-CHARACTER-TIMING"))?
            / u128::from(self.numerator);
        duration_nanos(nanos)
    }
}
fn duration_nanos(nanos: u128) -> Result<Duration> {
    let seconds =
        u64::try_from(nanos / 1_000_000_000).map_err(|_| failure("E-CHARACTER-TIMING"))?;
    Ok(Duration::new(seconds, (nanos % 1_000_000_000) as u32))
}

#[derive(Clone, Debug)]
pub struct TimeRange {
    pub start: Duration,
    pub end: Duration,
}
impl TimeRange {
    fn contains(&self, time: Duration) -> bool {
        self.start <= time && time < self.end
    }
}

#[derive(Clone, Debug)]
pub struct TalkWiggle {
    pub x_pixels: f64,
    pub y_pixels: f64,
    pub cycles_per_second: f64,
}
#[derive(Clone, Debug)]
pub struct EntranceBounce {
    pub duration: Duration,
    pub scale_amplitude: f64,
}
#[derive(Clone, Debug)]
pub struct CharacterMotion {
    pub blinks: Vec<TimeRange>,
    pub blink_only_speaking: bool,
    pub wiggle: Option<TalkWiggle>,
    pub bounce: Option<EntranceBounce>,
}
impl CharacterMotion {
    fn validate(&self) -> Result<()> {
        if self.blinks.iter().any(|range| range.start >= range.end)
            || self
                .blinks
                .windows(2)
                .any(|pair| pair[0].end > pair[1].start)
        {
            return Err(failure("E-CHARACTER-CONFIG"));
        }
        if let Some(wiggle) = &self.wiggle {
            if !wiggle.x_pixels.is_finite()
                || !wiggle.y_pixels.is_finite()
                || !wiggle.cycles_per_second.is_finite()
                || wiggle.cycles_per_second <= 0.0
            {
                return Err(failure("E-CHARACTER-CONFIG"));
            }
        }
        if let Some(bounce) = &self.bounce {
            if bounce.duration.is_zero()
                || !bounce.scale_amplitude.is_finite()
                || !(0.0..1.0).contains(&bounce.scale_amplitude)
            {
                return Err(failure("E-CHARACTER-CONFIG"));
            }
        }
        Ok(())
    }
}

pub struct CharacterFrameRequest<'a> {
    pub channel_id: &'a ChannelId,
    pub character_id: &'a str,
    pub speaking: bool,
    pub expression: Option<&'a str>,
    pub frame: u64,
    pub frame_rate: FrameRate,
    pub phonemes: &'a PhonemeTimeline,
    pub mouth_map: &'a BTreeMap<String, MouthShape>,
    pub motion: &'a CharacterMotion,
}
pub struct CharacterFrame {
    pub image: RgbaImage,
    pub mouth: MouthShape,
    pub blinking: bool,
    pub mouth_layer_changes: usize,
    pub blink_layer_changes: usize,
    pub expression_active: bool,
    pub offset_x: i64,
    pub offset_y: i64,
    pub scale: f64,
}
impl CharacterFrame {
    pub fn save_new_png(&self, path: &Path) -> Result<()> {
        let mut bytes = Vec::new();
        image::codecs::png::PngEncoder::new(&mut bytes)
            .write_image(
                self.image.as_raw(),
                self.image.width(),
                self.image.height(),
                image::ExtendedColorType::Rgba8,
            )
            .map_err(|_| failure("E-CHARACTER-ASSET"))?;
        fsutil::atomic_write_new(path, &bytes)
    }
}
impl PreparedCharacter {
    pub fn frame(&self, request: &CharacterFrameRequest<'_>) -> Result<CharacterFrame> {
        if request.channel_id != &self.channel || request.character_id != self.character_id {
            return Err(failure("E-CHARACTER-CHANNEL"));
        }
        if request.phonemes.channel != self.channel {
            return Err(failure("E-CHARACTER-CHANNEL"));
        }
        request.motion.validate()?;
        let time = request.frame_rate.timestamp(request.frame)?;
        let expression = request
            .expression
            .map(|name| {
                self.expressions
                    .get(name)
                    .ok_or_else(|| failure("E-CHARACTER-RIG"))
            })
            .transpose()?;
        // 表情PNGは口・目を含む完成画像。表情指定時の追加変更は必ず両方0にする。
        let mouth = if expression.is_some() || !request.speaking || !self.lipsync {
            MouthShape::Closed
        } else {
            match request.phonemes.phoneme_at(time) {
                None => MouthShape::Closed,
                Some(phoneme) => *request
                    .mouth_map
                    .get(phoneme)
                    .ok_or_else(|| failure("E-CHARACTER-TIMING"))?,
            }
        };
        let blink = expression.is_none()
            && self.blink
            && (!request.motion.blink_only_speaking || request.speaking)
            && request
                .motion
                .blinks
                .iter()
                .any(|range| range.contains(time));
        let (image, mouth_changes, blink_changes) = if let Some(image) = expression {
            (image.clone(), 0, 0)
        } else {
            let cached = self
                .frames
                .get(&(mouth, blink))
                .ok_or_else(|| failure("E-CHARACTER-RIG"))?;
            (
                cached.image.clone(),
                cached.mouth_changes,
                cached.blink_changes,
            )
        };
        let mut frame = CharacterFrame {
            image,
            mouth,
            blinking: blink,
            mouth_layer_changes: mouth_changes,
            blink_layer_changes: blink_changes,
            expression_active: expression.is_some(),
            offset_x: 0,
            offset_y: 0,
            scale: 1.0,
        };
        if request.speaking {
            if let Some(wiggle) = &request.motion.wiggle {
                let phase = std::f64::consts::TAU * time.as_secs_f64() * wiggle.cycles_per_second;
                let x = wiggle.x_pixels * phase.sin();
                let y = wiggle.y_pixels * phase.cos();
                if !x.is_finite()
                    || !y.is_finite()
                    || x.abs() >= i64::MAX as f64
                    || y.abs() >= i64::MAX as f64
                {
                    return Err(failure("E-CHARACTER-CONFIG"));
                }
                frame.offset_x = x.round_ties_even() as i64;
                frame.offset_y = y.round_ties_even() as i64;
            }
            if let Some(bounce) = &request.motion.bounce {
                if time < bounce.duration {
                    frame.scale += bounce.scale_amplitude
                        * (std::f64::consts::PI * time.as_secs_f64()
                            / bounce.duration.as_secs_f64())
                        .sin();
                }
            }
        }
        self.limits
            .image_bytes(frame.image.width(), frame.image.height())?;
        Ok(frame)
    }
}

/// 倍率は明示指定する。元解像度はそのまま保持し、縮小時もアルファを前乗算して縁の色漏れを防ぐ。
pub fn place_character(
    canvas: &mut RgbaImage,
    frame: &CharacterFrame,
    left: i64,
    top: i64,
    scale: f64,
    allow_clipping: bool,
    limits: &CharacterLimits,
) -> Result<()> {
    if !scale.is_finite() || scale <= 0.0 || !frame.scale.is_finite() || frame.scale <= 0.0 {
        return Err(failure("E-CHARACTER-CONFIG"));
    }
    let scale = scale * frame.scale;
    let width = (f64::from(frame.image.width()) * scale).round_ties_even();
    let height = (f64::from(frame.image.height()) * scale).round_ties_even();
    if !width.is_finite()
        || !height.is_finite()
        || width < 1.0
        || height < 1.0
        || width > f64::from(u32::MAX)
        || height > f64::from(u32::MAX)
    {
        return Err(failure("E-CHARACTER-CONFIG"));
    }
    limits.image_bytes(width as u32, height as u32)?;
    let left = left
        .checked_add(frame.offset_x)
        .ok_or_else(|| failure("E-CHARACTER-CONFIG"))?;
    let top = top
        .checked_add(frame.offset_y)
        .ok_or_else(|| failure("E-CHARACTER-CONFIG"))?;
    let right = left
        .checked_add(width as i64)
        .ok_or_else(|| failure("E-CHARACTER-CONFIG"))?;
    let bottom = top
        .checked_add(height as i64)
        .ok_or_else(|| failure("E-CHARACTER-CONFIG"))?;
    if !allow_clipping
        && (left < 0
            || top < 0
            || right > i64::from(canvas.width())
            || bottom > i64::from(canvas.height()))
    {
        return Err(failure("E-CHARACTER-CONFIG"));
    }
    let resized;
    let image = if (width as u32, height as u32) == frame.image.dimensions() {
        &frame.image
    } else {
        let original_bytes = (u64::from(frame.image.width()) * u64::from(frame.image.height()))
            .checked_mul(16)
            .ok_or_else(|| failure("E-CHARACTER-ASSET"))?;
        let temporary_bytes = (width as u64 * height as u64)
            .checked_mul(20)
            .and_then(|value| value.checked_add(original_bytes))
            .ok_or_else(|| failure("E-CHARACTER-ASSET"))?;
        if temporary_bytes > limits.maximum_decoded_bytes {
            return Err(failure("E-CHARACTER-ASSET"));
        }
        resized = resize_premultiplied(&frame.image, width as u32, height as u32);
        &resized
    };
    composite_at(canvas, image, left, top);
    Ok(())
}
pub(crate) fn resize_premultiplied(image: &RgbaImage, width: u32, height: u32) -> RgbaImage {
    let premultiplied = image::Rgba32FImage::from_fn(image.width(), image.height(), |x, y| {
        let pixel = image.get_pixel(x, y);
        let alpha = f32::from(pixel[3]) / 255.0;
        Rgba([
            f32::from(pixel[0]) / 255.0 * alpha,
            f32::from(pixel[1]) / 255.0 * alpha,
            f32::from(pixel[2]) / 255.0 * alpha,
            alpha,
        ])
    });
    let resized = image::imageops::resize(&premultiplied, width, height, FilterType::Lanczos3);
    RgbaImage::from_fn(width, height, |x, y| {
        let pixel = resized.get_pixel(x, y);
        let alpha = pixel[3].clamp(0.0, 1.0);
        if alpha <= 0.0 {
            Rgba([0, 0, 0, 0])
        } else {
            Rgba([
                (pixel[0] / alpha * 255.0).round().clamp(0.0, 255.0) as u8,
                (pixel[1] / alpha * 255.0).round().clamp(0.0, 255.0) as u8,
                (pixel[2] / alpha * 255.0).round().clamp(0.0, 255.0) as u8,
                (alpha * 255.0).round() as u8,
            ])
        }
    })
}

#[derive(Clone, Debug)]
pub struct PhonemeTimingPolicy {
    pub decoder_sample_rate: u32,
    pub decoder_hop_samples: u32,
    pub interrogative_upspeak: bool,
    pub interrogative_length: Duration,
    pub legacy_pause_scale: f64,
    pub maximum_phonemes: usize,
    pub allowed_audio_drift: Duration,
}
#[derive(Clone, Debug)]
pub struct PhonemeSpan {
    pub phoneme: String,
    pub range: TimeRange,
}
#[derive(Clone, Debug)]
pub struct PhonemeTimeline {
    channel: ChannelId,
    pub spans: Vec<PhonemeSpan>,
    pub audio_duration: Duration,
}
impl PhonemeTimeline {
    pub fn from_synthesis(speech: &SynthesisResult, policy: &PhonemeTimingPolicy) -> Result<Self> {
        if speech.audio.sample_rate == 0 {
            return Err(failure("E-CHARACTER-TIMING"));
        }
        let audio_duration = Duration::try_from_secs_f64(speech.audio.duration_seconds())
            .map_err(|_| failure("E-CHARACTER-TIMING"))?;
        let tail = Duration::try_from_secs_f64(
            speech.audio.trailing_silent_frames as f64 / f64::from(speech.audio.sample_rate),
        )
        .map_err(|_| failure("E-CHARACTER-TIMING"))?;
        Self::build(
            &speech.channel_id,
            &speech.query,
            audio_duration,
            policy,
            Some(tail),
        )
    }
    pub fn from_query(
        channel: &ChannelId,
        query: &Value,
        audio_duration: Duration,
        policy: &PhonemeTimingPolicy,
    ) -> Result<Self> {
        Self::build(channel, query, audio_duration, policy, None)
    }
    fn build(
        channel: &ChannelId,
        query: &Value,
        audio_duration: Duration,
        policy: &PhonemeTimingPolicy,
        verified_tail: Option<Duration>,
    ) -> Result<Self> {
        if policy.decoder_sample_rate == 0
            || policy.decoder_hop_samples == 0
            || policy.maximum_phonemes == 0
            || !policy.legacy_pause_scale.is_finite()
            || policy.legacy_pause_scale < 0.0
            || policy.interrogative_upspeak && policy.interrogative_length.is_zero()
        {
            return Err(failure("E-CHARACTER-TIMING"));
        }
        let speed = number(query, "speedScale")?;
        if speed <= 0.0 {
            return Err(failure("E-CHARACTER-TIMING"));
        }
        let pause_scale = match query.get("pauseLengthScale") {
            Some(value) => value
                .as_f64()
                .filter(|value| value.is_finite() && *value >= 0.0)
                .ok_or_else(|| failure("E-CHARACTER-TIMING"))?,
            None => policy.legacy_pause_scale,
        };
        let mut units = vec![("sil".to_owned(), number(query, "prePhonemeLength")?)];
        let phrases = query
            .get("accent_phrases")
            .and_then(Value::as_array)
            .ok_or_else(|| failure("E-CHARACTER-TIMING"))?;
        for phrase in phrases {
            let moras = phrase
                .get("moras")
                .and_then(Value::as_array)
                .filter(|moras| !moras.is_empty())
                .ok_or_else(|| failure("E-CHARACTER-TIMING"))?;
            for mora in moras {
                append_mora(&mut units, mora, None, pause_scale)?;
            }
            let interrogative = phrase
                .get("is_interrogative")
                .and_then(Value::as_bool)
                .ok_or_else(|| failure("E-CHARACTER-TIMING"))?;
            if policy.interrogative_upspeak && interrogative {
                let last = moras.last().ok_or_else(|| failure("E-CHARACTER-TIMING"))?;
                if number(last, "pitch")? > 0.0 {
                    units.push((
                        string(last, "vowel")?.to_owned(),
                        policy.interrogative_length.as_secs_f64(),
                    ));
                }
            }
            if let Some(pause) = phrase.get("pause_mora").filter(|value| !value.is_null()) {
                let pause_length = query
                    .get("pauseLength")
                    .filter(|value| !value.is_null())
                    .map(|value| {
                        value
                            .as_f64()
                            .filter(|value| value.is_finite() && *value >= 0.0)
                            .ok_or_else(|| failure("E-CHARACTER-TIMING"))
                    })
                    .transpose()?;
                append_mora(&mut units, pause, pause_length, pause_scale)?;
            }
            if units.len() > policy.maximum_phonemes {
                return Err(failure("E-CHARACTER-TIMING"));
            }
        }
        units.push(("sil".to_owned(), number(query, "postPhonemeLength")?));
        if units.len() > policy.maximum_phonemes {
            return Err(failure("E-CHARACTER-TIMING"));
        }
        let mut frames = 0_u64;
        let mut spans = Vec::new();
        let timestamp = |frame: u64| -> Result<Duration> {
            duration_nanos(
                u128::from(frame) * u128::from(policy.decoder_hop_samples) * 1_000_000_000
                    / u128::from(policy.decoder_sample_rate),
            )
        };
        for (phoneme, length) in units {
            let decoder_rate =
                f64::from(policy.decoder_sample_rate) / f64::from(policy.decoder_hop_samples);
            let count = (length / speed * decoder_rate).round_ties_even();
            if !count.is_finite() || count < 0.0 || count >= u64::MAX as f64 {
                return Err(failure("E-CHARACTER-TIMING"));
            }
            let next = frames
                .checked_add(count as u64)
                .ok_or_else(|| failure("E-CHARACTER-TIMING"))?;
            if next > frames {
                spans.push(PhonemeSpan {
                    phoneme,
                    range: TimeRange {
                        start: timestamp(frames)?,
                        end: timestamp(next)?,
                    },
                });
            }
            frames = next;
        }
        let generated = timestamp(frames)?;
        let excess_tail = audio_duration.saturating_sub(generated);
        if generated > audio_duration.saturating_add(policy.allowed_audio_drift)
            || excess_tail > policy.allowed_audio_drift
                && verified_tail.is_none_or(|tail| excess_tail > tail)
        {
            return Err(failure("E-CHARACTER-TIMING"));
        }
        // voice層が補った末尾無音も閉口とし、音声末尾まで時刻を所有する。
        if audio_duration > generated {
            spans.push(PhonemeSpan {
                phoneme: "sil".into(),
                range: TimeRange {
                    start: generated,
                    end: audio_duration,
                },
            });
        }
        Ok(Self {
            channel: channel.clone(),
            spans,
            audio_duration,
        })
    }
    pub fn phoneme_at(&self, time: Duration) -> Option<&str> {
        self.spans
            .iter()
            .find(|span| span.range.contains(time))
            .map(|span| span.phoneme.as_str())
    }
}
fn append_mora(
    units: &mut Vec<(String, f64)>,
    mora: &Value,
    pause_length: Option<f64>,
    pause_scale: f64,
) -> Result<()> {
    if let Some(consonant) = mora.get("consonant").filter(|value| !value.is_null()) {
        let consonant = consonant
            .as_str()
            .filter(|value| !value.is_empty())
            .ok_or_else(|| failure("E-CHARACTER-TIMING"))?;
        units.push((consonant.to_owned(), number(mora, "consonant_length")?));
    }
    let vowel = string(mora, "vowel")?;
    let mut length = number(mora, "vowel_length")?;
    if vowel == "pau" {
        length = pause_length.unwrap_or(length) * pause_scale;
    }
    units.push((vowel.to_owned(), length));
    Ok(())
}
fn number(value: &Value, key: &str) -> Result<f64> {
    value
        .get(key)
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite() && *value >= 0.0)
        .ok_or_else(|| failure("E-CHARACTER-TIMING"))
}
fn string<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| failure("E-CHARACTER-TIMING"))
}

#[cfg(test)]
#[path = "character_tests.rs"]
mod tests;
