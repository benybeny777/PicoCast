//! 一度だけ書き出したPSD manifestを検証し、チャンネル内のキャラクターへ登録する。

use crate::repository::{
    Asset, AssetRef, AuditEntry, AuditEntryKey, Channel, ChannelKey, Character, CharacterKey,
};
use crate::{db_failure, failure, imports, repository, Store};
use picocast_core::{
    clock::{self, Timestamp},
    fsutil, AppError, ChannelId, Result,
};
use rusqlite::Connection;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
    path::{Component, Path},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema_version: u32,
    source: Source,
    canvas: Canvas,
    pixel_tolerance: u8,
    layers: Vec<Layer>,
    variants: Vec<Variant>,
    unsupported_composition: Vec<Value>,
    expression_overlay_policy: String,
    coverage: Value,
    qualified: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    sha256: String,
    bytes: u64,
    psd_tools_version: String,
    depth: u32,
    color_mode: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Canvas {
    width: u32,
    height: u32,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ImageRecord {
    path: String,
    sha256: String,
    bytes: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Layer {
    id: String,
    parent_id: Option<String>,
    order: usize,
    name: String,
    kind: String,
    visible: bool,
    opacity: u8,
    blend_mode: String,
    clipping: bool,
    bbox: [i64; 4],
    is_group: bool,
    image: ImageRecord,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Variant {
    id: String,
    visibility: BTreeMap<String, bool>,
    image: ImageRecord,
    validation: Validation,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Validation {
    max_abs_channel_diff: u8,
    mismatched_pixels: u64,
    qualified: bool,
}

impl Manifest {
    fn validate(&self) -> Result<()> {
        if self.schema_version != 1
            || !self.qualified
            || !self.unsupported_composition.is_empty()
            || !digest_valid(&self.source.sha256)
            || self.source.bytes == 0
            || self.source.psd_tools_version.is_empty()
            || ![8, 16, 32].contains(&self.source.depth)
            || self.source.color_mode.is_empty()
            || self.canvas.width == 0
            || self.canvas.height == 0
            || self.layers.is_empty()
            || self.variants.is_empty()
            || self.expression_overlay_policy != "disable_mouth_and_blink_on_expression_png"
            || !self.coverage.is_object()
        {
            return Err(invalid());
        }
        let mut layers = BTreeMap::new();
        for (position, layer) in self.layers.iter().enumerate() {
            let path_parent = layer.id.rsplit_once('/').map(|(parent, _)| parent);
            if layer.order != position
                || layer.id.is_empty()
                || layer
                    .id
                    .split('/')
                    .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
                || path_parent != layer.parent_id.as_deref()
                || layer
                    .parent_id
                    .as_ref()
                    .is_some_and(|parent| !layers.get(parent).is_some_and(|is_group| *is_group))
                || layers.insert(layer.id.clone(), layer.is_group).is_some()
                || layer.kind.is_empty()
                || layer.name.contains('\0')
                || !matches!(layer.blend_mode.as_str(), "norm" | "pass")
                || layer.clipping
                || (layer.is_group && layer.opacity != 255)
                || layer.bbox[2] < layer.bbox[0]
                || layer.bbox[3] < layer.bbox[1]
            {
                return Err(invalid());
            }
        }
        let mut variants = BTreeSet::new();
        for variant in &self.variants {
            let pixels = u64::from(self.canvas.width) * u64::from(self.canvas.height);
            if variant.id.is_empty()
                || !variants.insert(&variant.id)
                || variant.visibility.keys().collect::<BTreeSet<_>>() != layers.keys().collect()
                || !variant.validation.qualified
                || variant.validation.max_abs_channel_diff > self.pixel_tolerance
                || variant.validation.mismatched_pixels > pixels
                || (variant.validation.max_abs_channel_diff == 0)
                    != (variant.validation.mismatched_pixels == 0)
            {
                return Err(invalid());
            }
        }
        let initial = self
            .variants
            .iter()
            .find(|variant| variant.id == "default")
            .ok_or_else(invalid)?;
        if self
            .layers
            .iter()
            .any(|layer| initial.visibility.get(&layer.id) != Some(&layer.visible))
        {
            return Err(invalid());
        }
        match self.coverage.get("kind").and_then(Value::as_str) {
            Some("explicit_variants") => (),
            Some("legacy_psd_presets") => {
                for (key, prefix) in [
                    ("native_variants", "native:"),
                    ("expressions", "expression:"),
                ] {
                    let expected = self
                        .coverage
                        .get(key)
                        .and_then(Value::as_array)
                        .filter(|items| !items.is_empty())
                        .ok_or_else(invalid)?;
                    for name in expected {
                        let id = format!(
                            "{prefix}{}",
                            name.as_str()
                                .filter(|name| !name.is_empty())
                                .ok_or_else(invalid)?
                        );
                        if !variants.contains(&id) {
                            return Err(invalid());
                        }
                    }
                }
            }
            _ => return Err(invalid()),
        }
        Ok(())
    }
}

/// 登録と本番合成で、manifestの意味と受入済み状態を同じ境界で検査する。
pub fn validate_manifest(bytes: &[u8]) -> Result<()> {
    parse_manifest(bytes).map(|_| ())
}

fn parse_manifest(bytes: &[u8]) -> Result<Manifest> {
    let manifest: Manifest = serde_json::from_slice(bytes).map_err(|error| {
        tracing::error!(cause = ?error.classify(), "立ち絵manifestの形式が不正です");
        invalid()
    })?;
    manifest.validate()?;
    Ok(manifest)
}

impl Store {
    /// 画素検査済みのPNGとmanifestをCASへ保存する。元PSDや書き出し元は変更しない。
    pub fn register_character_layers(
        &mut self,
        channel_id: &ChannelId,
        character_id: &str,
        manifest_path: &Path,
        assets_root: &Path,
    ) -> Result<String> {
        let key = CharacterKey {
            channel_id: channel_id.clone(),
            id: character_id.into(),
        };
        let mut character = self
            .repository(channel_id)?
            .get::<Character>(&key)?
            .ok_or_else(invalid)?;
        let manifest_hash = imports::digest_file(manifest_path)?;
        let bytes = std::fs::read(manifest_path).map_err(filesystem_failure)?;
        let manifest = parse_manifest(&bytes)?;
        let base = std::fs::canonicalize(manifest_path.parent().ok_or_else(invalid)?)
            .map_err(filesystem_failure)?;
        let mut copied = Vec::new();
        for image in manifest
            .layers
            .iter()
            .map(|layer| &layer.image)
            .chain(manifest.variants.iter().map(|variant| &variant.image))
        {
            let path = Path::new(&image.path);
            if !digest_valid(&image.sha256)
                || image.bytes == 0
                || path.is_absolute()
                || path.components().count() != 2
                || path
                    .components()
                    .any(|part| !matches!(part, Component::Normal(_)))
                || !matches!(
                    path.components()
                        .next()
                        .and_then(|part| part.as_os_str().to_str()),
                    Some("layers" | "variants")
                )
                || path.extension().and_then(|extension| extension.to_str()) != Some("png")
            {
                return Err(invalid());
            }
            let canonical = std::fs::canonicalize(base.join(path)).map_err(filesystem_failure)?;
            if !canonical.starts_with(&base)
                || std::fs::symlink_metadata(base.join(path))
                    .map_err(filesystem_failure)?
                    .file_type()
                    .is_symlink()
            {
                return Err(invalid());
            }
            check_png_header(&canonical, &manifest.canvas)?;
            let asset = fsutil::import_content_addressed(&canonical, assets_root)?;
            if asset.sha256 != image.sha256 || asset.bytes != image.bytes {
                return Err(invalid());
            }
            copied.push((asset, image.path.clone()));
        }
        let asset = fsutil::import_content_addressed(manifest_path, assets_root)?;
        if asset.sha256 != manifest_hash || imports::digest_file(manifest_path)? != manifest_hash {
            return Err(invalid());
        }
        let audit_identity = serde_json::to_vec(&(channel_id, character_id, &manifest_hash))
            .map_err(|_| invalid())?;
        let audit_id = format!(
            "character-layers:{}",
            imports::digest_bytes(&audit_identity)
        );
        let previous = repository::get::<AuditEntry>(
            &self.connection,
            &AuditEntryKey {
                id: audit_id.clone(),
            },
            None,
        )?;
        let at = match previous {
            Some(record) => record.at,
            None => Timestamp::parse(&clock::now_utc_iso())?,
        };
        let tx = self.connection.transaction().map_err(db_failure)?;
        let channel = repository::get::<Channel>(
            &tx,
            &ChannelKey {
                channel_id: channel_id.clone(),
            },
            None,
        )?
        .ok_or_else(invalid)?;
        if channel.archived_at.is_some() {
            return Err(invalid());
        }
        let current = repository::get::<Character>(&tx, &key, None)?.ok_or_else(invalid)?;
        if current != character {
            return Err(invalid());
        }
        for (image, role) in &copied {
            save_asset(&tx, image, &at, "character_layer_png")?;
            imports::put_checked(
                &tx,
                &AssetRef {
                    channel_id: channel_id.clone(),
                    owner_kind: "character".into(),
                    owner_id: character_id.into(),
                    sha256: image.sha256.clone(),
                    role: format!("psd:{role}"),
                },
            )?;
        }
        save_asset(&tx, &asset, &at, "character_layer_manifest")?;
        imports::put_checked(
            &tx,
            &AssetRef {
                channel_id: channel_id.clone(),
                owner_kind: "character".into(),
                owner_id: character_id.into(),
                sha256: manifest_hash.clone(),
                role: "psd:manifest".into(),
            },
        )?;
        character.layer_manifest_sha256 = Some(manifest_hash.clone());
        repository::save(&tx, &character)?;
        imports::put_checked(
            &tx,
            &AuditEntry {
                id: audit_id,
                at,
                actor: "import".into(),
                action: "register_character_layers".into(),
                target: format!("{}:{character_id}", channel_id.as_str()),
                detail_json: json!({"manifest_sha256":manifest_hash,
                "source_sha256":manifest.source.sha256, "layers":manifest.layers.len(), "variants":manifest.variants.len(), "pixel_tolerance":manifest.pixel_tolerance}),
            },
        )?;
        tx.commit().map_err(db_failure)?;
        Ok(manifest_hash)
    }
}

fn save_asset(
    tx: &Connection,
    asset: &fsutil::ContentAsset,
    at: &Timestamp,
    kind: &str,
) -> Result<()> {
    let bytes = i64::try_from(asset.bytes).map_err(|_| invalid())?;
    imports::put_asset_checked(
        tx,
        &Asset {
            sha256: asset.sha256.clone(),
            bytes,
            ext: asset.ext.clone(),
            kind: kind.into(),
            created_at: at.clone(),
            provenance_json: json!({"source":"psd-layer-export"}),
        },
    )
}

fn digest_valid(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn check_png_header(path: &Path, canvas: &Canvas) -> Result<()> {
    let mut header = [0u8; 33];
    std::fs::File::open(path)
        .and_then(|mut file| file.read_exact(&mut header))
        .map_err(filesystem_failure)?;
    if header[..16] != [137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82]
        || header[16..20] != canvas.width.to_be_bytes()
        || header[20..24] != canvas.height.to_be_bytes()
        || header[24..29] != [8, 6, 0, 0, 0]
    {
        return Err(invalid());
    }
    Ok(())
}

fn invalid() -> AppError {
    failure(
        "E-PSD-REGISTER",
        "立ち絵レイヤーを登録できません。",
        "書き出し結果の画素検査・manifestとPNGのハッシュ・対象チャンネルとキャラクターを確認してください。元PSDと既存データは削除しないでください。",
    )
}

fn filesystem_failure(error: std::io::Error) -> AppError {
    tracing::error!(code = "E-PSD-REGISTER", cause = ?error.kind(), os_code = ?error.raw_os_error(), "立ち絵書き出し結果のファイル検査に失敗しました");
    invalid()
}

#[cfg(test)]
#[path = "character_layers_tests.rs"]
mod tests;
