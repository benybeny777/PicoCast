#[cfg(test)]
mod fixture {
    #![allow(clippy::unwrap_used)]

    use crate::channel_import::{ChannelImportOptions, ChannelImportReport};
    use crate::repository::{
        AssetRef, Job, JobStep, Project, ProjectRevision, ProjectRevisionKey, YoutubeVideo,
    };
    use crate::{imports, DataMode, Store, StoreOptions, StorePaths};
    use picocast_core::{clock::Timestamp, fsutil, ChannelId};
    use rusqlite::Connection;
    use serde_json::Value;
    use std::{collections::BTreeMap, time::Duration};

    struct Fixture {
        _directory: tempfile::TempDir,
        store: Store,
        channel: ChannelId,
        options: ChannelImportOptions,
    }

    impl Fixture {
        fn new() -> Self {
            let directory = tempfile::tempdir().unwrap();
            let output = directory.path().join("output-copy");
            let original = directory.path().join("original-output");
            let metadata = directory.path().join("metadata.db");
            std::fs::create_dir_all(output.join("videos/theme/audio")).unwrap();
            fsutil::atomic_write(
                &output.join("videos/theme/movie.mp4"),
                b"synthetic-media-same-contents",
            )
            .unwrap();
            fsutil::atomic_write(
                &output.join("videos/theme/audio/speech.wav"),
                b"synthetic-media-same-contents",
            )
            .unwrap();
            let source = Connection::open(&metadata).unwrap();
            source.execute_batch("CREATE TABLE videos(local_id TEXT PRIMARY KEY, output_dir TEXT, title TEXT, video_type TEXT, script_content TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE video_metadata(local_id TEXT PRIMARY KEY, description TEXT, tags TEXT, fixed_comment TEXT);
                CREATE TABLE youtube_status(local_id TEXT PRIMARY KEY, youtube_video_id TEXT, publish_status TEXT, privacy_status TEXT, publish_at TEXT, published_at TEXT, fixed_comment_posted INTEGER, fixed_comment_id TEXT, playlist_registered INTEGER);
                CREATE TABLE analytics_snapshots(id INTEGER PRIMARY KEY, youtube_video_id TEXT, window_days INTEGER, collected_at TEXT, views INTEGER, score TEXT);
                CREATE TABLE jobs(job_id TEXT PRIMARY KEY, job_type TEXT, profile_id TEXT, status TEXT, runner_pid INTEGER, created_at TEXT, started_at TEXT, logs_json TEXT, params_json TEXT, result_json TEXT);
                CREATE TABLE playlists(id INTEGER PRIMARY KEY, local_id TEXT, youtube_video_id TEXT, status TEXT);
                CREATE TABLE topic_history(local_id TEXT PRIMARY KEY, title TEXT, topic_key TEXT, status TEXT, created_at TEXT);
                CREATE TABLE future_legacy_state(id TEXT PRIMARY KEY, important_value TEXT);") .unwrap();
            source.execute("INSERT INTO videos VALUES ('theme',?1,'題名','shorts','ずんだもん：原文をそのまま保存','2026-10-16T12:00:00','2026-10-16T13:00:00')", [original.join("videos/theme").to_str().unwrap()]).unwrap();
            source.execute_batch("INSERT INTO video_metadata VALUES ('theme','説明','[\"タグ\"]','既に投稿した固定コメント');
                INSERT INTO youtube_status VALUES ('theme','yt-001','published','public',NULL,'2026-10-16T04:00:00Z',1,'comment-001',1);
                INSERT INTO analytics_snapshots VALUES (1,'yt-001',28,'2026-10-16T12:00:00',987,'A');
                INSERT INTO playlists VALUES (1,'theme','yt-001','registered');
                INSERT INTO topic_history VALUES ('theme','テーマ','topic-key','used','2026-10-16T11:00:00');
                INSERT INTO jobs VALUES ('orphan','generate','channel','running',999999,'2026-10-16T10:00:00','2026-10-16T10:01:00','[\"原ログ\"]','{}','{}');
                INSERT INTO jobs VALUES ('live','generate','channel','running',1234,'2026-10-16T10:00:00','2026-10-16T10:01:00','[]','{}',NULL);
                INSERT INTO jobs VALUES ('queue','render','channel','queued',NULL,'2026-10-16T10:00:00',NULL,'[]','{}',NULL);
                INSERT INTO future_legacy_state VALUES ('future','失ってはいけない将来の列');").unwrap();
            source.close().unwrap();
            let paths =
                StorePaths::new(&directory.path().join("destination"), DataMode::Development)
                    .unwrap();
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
            store.create_channel(&channel, "チャンネル").unwrap();
            store.connection.execute("UPDATE channels SET timezone='Asia/Tokyo',language='ja' WHERE channel_id='channel'", []).unwrap();
            let options = ChannelImportOptions {
                metadata_path: metadata,
                output_root: output,
                original_output_root: original,
                assets_root: paths.assets_directory(),
                source_timezone: "Asia/Tokyo".into(),
                imported_at: Timestamp::parse("2026-10-16T05:00:00Z").unwrap(),
                synthetic_media: true,
                verified_running_jobs: BTreeMap::from([("live".into(), 1234)]),
            };
            Self {
                _directory: directory,
                store,
                channel,
                options,
            }
        }

        fn run(&mut self) -> ChannelImportReport {
            self.store
                .import_legacy_channel(&self.channel, &self.options)
                .unwrap()
        }

        fn rows(&self, table: &str) -> i64 {
            self.store
                .connection
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .unwrap()
        }
    }

    #[test]
    fn imports_raw_state_abandoned_jobs_and_cas_without_touching_source() {
        let mut fixture = Fixture::new();
        let hash = imports::digest_file(&fixture.options.metadata_path).unwrap();
        let report = fixture.run();
        assert_eq!(report.projects, 1);
        assert_eq!(report.assets, 2);
        assert_eq!(report.abandoned_jobs, 1);
        assert_eq!(report.held_jobs, 2);
        assert_eq!(report.analytics_preserved, 1);
        assert_eq!(fixture.rows("assets"), 1);
        assert_eq!(fixture.rows("asset_refs"), 2);
        assert_eq!(fixture.rows("analytics_daily"), 0);
        assert_eq!(
            imports::digest_file(&fixture.options.metadata_path).unwrap(),
            hash
        );
        let repo = fixture.store.repository(&fixture.channel).unwrap();
        let revisions = repo.list::<ProjectRevision>().unwrap();
        let snapshot = &revisions[0].snapshot_json;
        assert_eq!(snapshot["script_content"], "ずんだもん：原文をそのまま保存");
        assert_eq!(
            snapshot["tables"]["youtube_status"][0]["fixed_comment_posted"],
            1
        );
        assert_eq!(snapshot["tables"]["playlists"][0]["status"], "registered");
        assert_eq!(
            snapshot["tables"]["analytics_snapshots"][0]["window_days"],
            28
        );
        let projects = repo.list::<Project>().unwrap();
        assert_eq!(projects[0].created_at.to_utc_iso(), "2026-10-16T03:00:00Z");
        assert_eq!(repo.list::<YoutubeVideo>().unwrap()[0].video_id, "yt-001");
        let jobs = repo.list::<Job>().unwrap();
        assert!(jobs
            .iter()
            .any(|job| job.id == "legacy-job:orphan" && job.status == "abandoned"));
        assert!(jobs
            .iter()
            .any(|job| job.id == "legacy-job:live" && job.status == "legacy_running"));
        assert!(jobs
            .iter()
            .any(|job| job.id == "legacy-job:queue" && job.status == "legacy_queued"));
        assert!(jobs.iter().all(|job| job.lease_owner.is_none()));
        assert_eq!(repo.list::<JobStep>().unwrap().len(), 3);
        let detail: String = fixture
            .store
            .connection
            .query_row(
                "SELECT detail_json FROM audit_log WHERE action='legacy_channel_import'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        let detail: Value = serde_json::from_str(&detail).unwrap();
        assert_eq!(
            detail["tables"]["future_legacy_state"][0]["important_value"],
            "失ってはいけない将来の列"
        );
        let raw = Connection::open(&fixture.options.metadata_path).unwrap();
        assert_eq!(
            raw.query_row("SELECT status FROM jobs WHERE job_id='orphan'", [], |row| {
                row.get::<_, String>(0)
            })
            .unwrap(),
            "running"
        );
        raw.close().unwrap();
    }

    #[test]
    fn repeated_import_is_identical_even_when_requested_timestamp_changes() {
        let mut fixture = Fixture::new();
        let first = fixture.run();
        fixture.options.imported_at = Timestamp::parse("2026-11-01T00:00:00Z").unwrap();
        assert_eq!(fixture.run(), first);
        assert_eq!(fixture.rows("projects"), 1);
        assert_eq!(fixture.rows("project_revisions"), 1);
        assert_eq!(fixture.rows("jobs"), 3);
        assert_eq!(fixture.rows("audit_log"), 1);
        let revision = fixture
            .store
            .repository(&fixture.channel)
            .unwrap()
            .get::<ProjectRevision>(&ProjectRevisionKey {
                channel_id: fixture.channel.clone(),
                project_id: "legacy-video:theme".into(),
                revision: 1,
            })
            .unwrap()
            .unwrap();
        assert_eq!(revision.author, "import");
    }

    #[test]
    fn failure_rolls_back_all_domain_rows_and_preserves_existing_target_data() {
        let mut fixture = Fixture::new();
        let connection = Connection::open(&fixture.options.metadata_path).unwrap();
        connection
            .execute(
                "UPDATE jobs SET profile_id='another-channel' WHERE job_id='queue'",
                [],
            )
            .unwrap();
        connection.close().unwrap();
        assert!(fixture
            .store
            .import_legacy_channel(&fixture.channel, &fixture.options)
            .is_err());
        assert_eq!(fixture.rows("projects"), 0);
        assert_eq!(fixture.rows("project_revisions"), 0);
        assert_eq!(fixture.rows("assets"), 0);
        assert_eq!(fixture.rows("jobs"), 0);
        assert_eq!(fixture.rows("audit_log"), 0);
        assert_eq!(fixture.rows("channels"), 1);
    }

    #[test]
    fn conflicting_target_is_not_overwritten() {
        let mut fixture = Fixture::new();
        fixture.run();
        fixture
            .store
            .connection
            .execute("UPDATE projects SET title='利用者が編集した題名'", [])
            .unwrap();
        assert!(fixture
            .store
            .import_legacy_channel(&fixture.channel, &fixture.options)
            .is_err());
        assert_eq!(
            fixture
                .store
                .connection
                .query_row("SELECT title FROM projects", [], |row| row
                    .get::<_, String>(0))
                .unwrap(),
            "利用者が編集した題名"
        );
    }

    #[test]
    fn unrelated_assets_receive_channel_references_and_cross_channel_data_stays_separate() {
        let mut fixture = Fixture::new();
        fsutil::atomic_write(
            &fixture.options.output_root.join("common.png"),
            b"other-common-asset",
        )
        .unwrap();
        fixture.run();
        let repo = fixture.store.repository(&fixture.channel).unwrap();
        assert_eq!(repo.list::<Project>().unwrap().len(), 1);
        let refs = repo.list::<AssetRef>().unwrap();
        assert!(refs
            .iter()
            .any(|asset| asset.owner_kind == "channel" && asset.owner_id == "channel"));
        let other = ChannelId::new("other").unwrap();
        fixture
            .store
            .create_channel(&other, "別チャンネル")
            .unwrap();
        assert!(fixture
            .store
            .repository(&other)
            .unwrap()
            .list::<Project>()
            .unwrap()
            .is_empty());
        assert_eq!(fixture.rows("assets"), 2);
        assert_eq!(fixture.rows("audit_log"), 1);
    }

    #[test]
    fn database_sidecars_and_credentials_are_reported_without_becoming_assets() {
        let mut fixture = Fixture::new();
        for name in [
            "metadata.db",
            "metadata.db-wal",
            "token.json",
            "master.key",
            ".env",
        ] {
            fsutil::atomic_write(
                &fixture.options.output_root.join(name),
                b"synthetic-private-value",
            )
            .unwrap();
        }
        let report = fixture.run();
        assert_eq!(report.assets, 2);
        assert_eq!(report.excluded_protected_files.len(), 5);
        assert_eq!(fixture.rows("assets"), 1);
        assert_eq!(fixture.rows("asset_refs"), 2);
        assert_eq!(
            std::fs::read(fixture.options.output_root.join("master.key")).unwrap(),
            b"synthetic-private-value"
        );
    }

    #[test]
    fn output_file_addition_is_detected_before_commit() {
        let fixture = Fixture::new();
        let (assets, excluded) =
            crate::channel_import::collect_assets(&fixture.options, &BTreeMap::new()).unwrap();
        fsutil::atomic_write(
            &fixture.options.output_root.join("new.png"),
            b"added during import",
        )
        .unwrap();
        assert!(
            crate::channel_import::verify_assets(&fixture.options, &assets, &excluded).is_err()
        );
    }

    #[test]
    fn escaping_original_project_path_and_nested_cas_are_rejected() {
        let mut fixture = Fixture::new();
        fixture.options.assets_root = fixture.options.output_root.join("nested-cas");
        assert!(fixture
            .store
            .import_legacy_channel(&fixture.channel, &fixture.options)
            .is_err());
        assert!(!fixture.options.assets_root.exists());
        fixture.options.assets_root = fixture._directory.path().join("safe-cas");
        let source = Connection::open(&fixture.options.metadata_path).unwrap();
        source
            .execute(
                "UPDATE videos SET output_dir=?1",
                [fixture._directory.path().join("outside").to_str().unwrap()],
            )
            .unwrap();
        source.close().unwrap();
        assert!(fixture
            .store
            .import_legacy_channel(&fixture.channel, &fixture.options)
            .is_err());
        assert_eq!(fixture.rows("projects"), 0);
    }
}
