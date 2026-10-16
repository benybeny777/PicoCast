#[cfg(test)]
mod fixture {
    #![allow(clippy::unwrap_used)]
    use crate::repository::{Character, CharacterKey};
    use crate::{imports, DataMode, Store, StoreOptions, StorePaths};
    use picocast_core::{fsutil, ChannelId};
    use serde_json::{json, Value};
    use std::{path::PathBuf, time::Duration};

    const PNG: &[u8] = &[
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 6,
        0, 0, 0, 31, 21, 196, 137, 0, 0, 0, 13, 73, 68, 65, 84, 120, 156, 99, 96, 100, 98, 254, 15,
        0, 1, 20, 1, 6, 214, 185, 166, 69, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
    ];

    struct Fixture {
        _directory: tempfile::TempDir,
        store: Store,
        channel: ChannelId,
        manifest_path: PathBuf,
        assets: PathBuf,
        manifest: Value,
    }
    impl Fixture {
        fn new() -> Self {
            let directory = tempfile::tempdir().unwrap();
            let export = directory.path().join("export");
            std::fs::create_dir_all(export.join("layers")).unwrap();
            std::fs::create_dir_all(export.join("variants")).unwrap();
            fsutil::atomic_write(&export.join("layers/000000.png"), PNG).unwrap();
            fsutil::atomic_write(&export.join("variants/000000.png"), PNG).unwrap();
            let hash = imports::digest_bytes(PNG);
            let image = |path: &str| json!({"path":path,"sha256":hash,"bytes":PNG.len()});
            let manifest = json!({"schema_version":1,"source":{"sha256":"a".repeat(64),"bytes":16,"psd_tools_version":"1.17.2","depth":8,"color_mode":"RGB"},
                "canvas":{"width":1,"height":1},"pixel_tolerance":0,
                "layers":[{"id":"0","parent_id":null,"order":0,"name":"レイヤー","kind":"pixel","visible":true,"opacity":255,"blend_mode":"norm","clipping":false,"bbox":[0,0,1,1],"is_group":false,"image":image("layers/000000.png")}],
                "variants":[{"id":"default","visibility":{"0":true},"image":image("variants/000000.png"),"validation":{"max_abs_channel_diff":0,"mismatched_pixels":0,"qualified":true}}],
                "unsupported_composition":[],"expression_overlay_policy":"disable_mouth_and_blink_on_expression_png","coverage":{"kind":"explicit_variants","legacy_presets_verified":false},"qualified":true});
            let manifest_path = export.join("manifest.json");
            fsutil::atomic_write(&manifest_path, &serde_json::to_vec(&manifest).unwrap()).unwrap();
            let paths =
                StorePaths::new(&directory.path().join("data"), DataMode::Development).unwrap();
            let store = Store::open(
                &paths,
                StoreOptions {
                    busy_timeout: Duration::from_secs(1),
                    backup_pages_per_step: 8,
                    backup_pause: Duration::from_millis(1),
                },
            )
            .unwrap();
            let channel = ChannelId::new("channel").unwrap();
            store.create_channel(&channel, "テスト").unwrap();
            store
                .repository(&channel)
                .unwrap()
                .save(&Character {
                    channel_id: channel.clone(),
                    id: "character".into(),
                    name: "キャラ".into(),
                    voice_provider: "voicevox".into(),
                    speaker_id: "0".into(),
                    style_map_json: json!({}),
                    credit_text: "クレジット".into(),
                    usage_rules_json: json!({}),
                    layer_manifest_sha256: None,
                })
                .unwrap();
            Self {
                _directory: directory,
                store,
                channel,
                manifest_path,
                assets: paths.assets_directory(),
                manifest,
            }
        }
        fn save(&self) {
            fsutil::atomic_write(
                &self.manifest_path,
                &serde_json::to_vec(&self.manifest).unwrap(),
            )
            .unwrap();
        }
        fn register(&mut self) -> picocast_core::Result<String> {
            self.store.register_character_layers(
                &self.channel,
                "character",
                &self.manifest_path,
                &self.assets,
            )
        }
        fn character_hash(&self) -> Option<String> {
            self.store
                .repository(&self.channel)
                .unwrap()
                .get::<Character>(&CharacterKey {
                    channel_id: self.channel.clone(),
                    id: "character".into(),
                })
                .unwrap()
                .unwrap()
                .layer_manifest_sha256
        }
        fn count(&self, table: &str) -> i64 {
            self.store
                .connection
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .unwrap()
        }
    }

    #[test]
    fn registers_qualified_pngs_and_manifest_without_changing_source_and_is_idempotent() {
        let mut fixture = Fixture::new();
        let before = imports::digest_file(&fixture.manifest_path).unwrap();
        assert_eq!(fixture.register().unwrap(), before);
        assert_eq!(fixture.register().unwrap(), before);
        assert_eq!(fixture.character_hash(), Some(before.clone()));
        assert_eq!(
            imports::digest_file(&fixture.manifest_path).unwrap(),
            before
        );
        assert_eq!(fixture.count("assets"), 2);
        assert_eq!(fixture.count("asset_refs"), 3);
        assert_eq!(fixture.count("audit_log"), 1);
    }

    #[test]
    fn unqualified_or_incomplete_manifest_cannot_replace_character_data() {
        for mutator in [
            |value: &mut Value| {
                value["qualified"] = json!(false);
            },
            |value: &mut Value| {
                value["variants"][0]["visibility"] = json!({});
            },
            |value: &mut Value| {
                value["layers"][0]["blend_mode"] = json!("mul");
            },
            |value: &mut Value| {
                value["coverage"] = json!({"kind":"legacy_psd_presets","native_variants":["base"],"expressions":["驚き"]});
            },
        ] {
            let mut fixture = Fixture::new();
            mutator(&mut fixture.manifest);
            fixture.save();
            assert!(fixture.register().is_err());
            assert!(fixture.character_hash().is_none());
            assert_eq!(fixture.count("assets"), 0);
            assert_eq!(fixture.count("audit_log"), 0);
        }
    }

    #[test]
    fn tampered_png_and_traversal_leave_existing_registration_intact() {
        let mut fixture = Fixture::new();
        let previous = fixture.register().unwrap();
        let path = fixture
            .manifest_path
            .parent()
            .unwrap()
            .join("layers/000000.png");
        let mut changed = PNG.to_vec();
        changed[50] ^= 1;
        fsutil::atomic_write(&path, &changed).unwrap();
        assert!(fixture.register().is_err());
        assert_eq!(fixture.character_hash(), Some(previous.clone()));
        fixture.manifest["layers"][0]["image"]["path"] = json!("../private.png");
        fixture.save();
        assert!(fixture.register().is_err());
        assert_eq!(fixture.character_hash(), Some(previous));
        assert_eq!(fixture.count("audit_log"), 1);
    }

    #[test]
    fn character_in_another_channel_cannot_be_registered() {
        let mut fixture = Fixture::new();
        let other = ChannelId::new("other").unwrap();
        fixture
            .store
            .create_channel(&other, "別チャンネル")
            .unwrap();
        assert!(fixture
            .store
            .register_character_layers(&other, "character", &fixture.manifest_path, &fixture.assets)
            .is_err());
        assert!(fixture.character_hash().is_none());
        assert_eq!(fixture.count("assets"), 0);
    }
}
