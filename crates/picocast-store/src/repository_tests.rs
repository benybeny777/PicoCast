#![cfg(test)]
#![allow(clippy::unwrap_used)]

use super::*;
use std::{collections::BTreeSet, fmt::Debug};

pub(super) trait Sample {
    fn sample() -> Self;
}
pub(super) trait Fixture {
    fn fixture(name: &str) -> Self;
}
pub(super) fn fixture<T: Fixture>(name: &str) -> T {
    T::fixture(name)
}

impl Fixture for String {
    fn fixture(name: &str) -> Self {
        match name {
            "sha256" | "inputs_hash" | "layer_manifest_sha256" | "background_sha256" => {
                "a".repeat(64)
            }
            "operator" => "legacy".into(),
            "format" => "shorts".into(),
            "kind" => "script".into(),
            "source" => "manual".into(),
            "author" => "user".into(),
            "result" => "pass".into(),
            "owner_kind" => "project".into(),
            "local_time" => "12:00".into(),
            "date" | "day_pt" | "fetched_on" => "2026-10-16".into(),
            "video_id" => "video".into(),
            "id" | "topic_id" | "project_id" | "scene_id" | "speaker_id" | "template_id"
            | "job_id" | "owner_id" | "insight_id" | "experiment_id" => "row".into(),
            _ => format!("日本語-{name}"),
        }
    }
}
impl Fixture for i64 {
    fn fixture(name: &str) -> Self {
        if matches!(name, "ord" | "weekday" | "loop_start_ms") {
            0
        } else if name == "duration_ms" {
            2
        } else {
            1
        }
    }
}
impl Fixture for f64 {
    fn fixture(_name: &str) -> Self {
        0.25
    }
}
impl Fixture for bool {
    fn fixture(_name: &str) -> Self {
        true
    }
}
impl Fixture for Timestamp {
    fn fixture(_name: &str) -> Self {
        Timestamp::parse("2026-10-16T00:00:00Z").unwrap()
    }
}
impl Fixture for ChannelId {
    fn fixture(_name: &str) -> Self {
        ChannelId::new("one").unwrap()
    }
}
impl Fixture for Value {
    fn fixture(_name: &str) -> Self {
        serde_json::json!({"保持":"値", "list":[1,true,null]})
    }
}
impl<T: Fixture> Fixture for Option<T> {
    fn fixture(name: &str) -> Self {
        if name == "archived_at" {
            None
        } else {
            Some(T::fixture(name))
        }
    }
}

fn roundtrip<R: Record + Sample + PartialEq + Debug>(
    connection: &Connection,
    checked: &mut BTreeSet<String>,
) {
    let record = R::sample();
    let result = save(connection, &record);
    assert!(result.is_ok(), "{}: {result:?}", R::TABLE);
    assert_eq!(
        get::<R>(connection, &record.key(), None).unwrap(),
        Some(record)
    );
    assert_eq!(list::<R>(connection, None).unwrap().len(), 1);
    checked.insert(R::TABLE.into());
}

#[test]
fn every_domain_table_roundtrips_typed_values() {
    let (_temporary, _paths, store) = crate::tests::fixture();
    let mut checked = BTreeSet::new();
    macro_rules! exercise { ($($record:ty),+ $(,)?) => { $(roundtrip::<$record>(&store.connection, &mut checked);)+ }; }
    exercise!(
        Channel,
        Asset,
        AppSetting,
        ChannelSetting,
        AuditEntry,
        CrashReport,
        Character,
        PromptTemplate,
        PromptTemplateVersion,
        Topic,
        Project,
        ProjectRevision,
        Scene,
        Line,
        AssetRef,
        AssetLicense,
        MusicTags,
        Job,
        JobStep,
        StepCache,
        QaResult,
        Upload,
        YoutubeVideo,
        QuotaLedger,
        AnalyticsDaily,
        RetentionCurve,
        Insight,
        InsightUsage,
        Experiment,
        ExperimentAssignment,
        AutopilotPolicy,
        ScheduleSlot,
        CostLedger,
        Notification,
        ReadingEntry,
        ReadingCandidate
    );
    // 旧版の CTR は百分率。不明な分析値や未計測費用をゼロに変えない。
    let mut analytics = AnalyticsDaily::sample();
    analytics.ctr = Some(8.5);
    analytics.impressions = None;
    analytics.revenue_micros = None;
    save(&store.connection, &analytics).unwrap();
    assert_eq!(
        get::<AnalyticsDaily>(&store.connection, &analytics.key(), None).unwrap(),
        Some(analytics)
    );
    let mut cost = CostLedger::sample();
    cost.cost_micros = None;
    save(&store.connection, &cost).unwrap();
    assert_eq!(
        get::<CostLedger>(&store.connection, &cost.key(), None).unwrap(),
        Some(cost)
    );
    let channel = ChannelId::new("one").unwrap();
    let key = crate::MasterKey::generate().unwrap();
    store
        .save_secret(&channel, "test", b"sensitive", &key)
        .unwrap();
    assert_eq!(
        store
            .load_secret(&channel, "test", &key)
            .unwrap()
            .unwrap()
            .as_slice(),
        b"sensitive"
    );
    checked.insert("secrets".into());
    assert_eq!(store.migration_history().unwrap().len(), 2);
    checked.insert("schema_migrations".into());
    let mut statement = store
        .connection
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        .unwrap();
    let tables = statement
        .query_map([], |row| row.get::<_, String>(0))
        .unwrap()
        .collect::<std::result::Result<BTreeSet<_>, _>>()
        .unwrap();
    assert_eq!(tables, checked, "新しい表にも型付き往復検証が必要です");
}

#[test]
fn public_repositories_enforce_channel_keys_and_parent_references() {
    let (_temporary, _paths, store) = crate::tests::fixture();
    let one = ChannelId::new("one").unwrap();
    let two = ChannelId::new("two").unwrap();
    store.create_channel(&one, "一").unwrap();
    store.create_channel(&two, "二").unwrap();
    let first = store.repository(&one).unwrap();
    let second = store.repository(&two).unwrap();
    let project = Project::sample();
    first.save(&Topic::sample()).unwrap();
    first.save(&project).unwrap();
    assert_eq!(second.save(&project).unwrap_err().code, "E-STORE-CHANNEL");
    assert_eq!(second.get::<Project>(&project.key()).unwrap(), None);
    assert!(!second.delete::<Project>(&project.key()).unwrap());
    assert!(second.list::<Project>().unwrap().is_empty());
    let mut scene = Scene::sample();
    scene.background_sha256 = None;
    scene.channel_id = two;
    assert!(
        second.save(&scene).is_err(),
        "別チャンネルの親を参照できてはいけません"
    );
    assert_eq!(first.get::<Project>(&project.key()).unwrap(), Some(project));
    store.global_repository().save(&Asset::sample()).unwrap();
    let asset_ref = AssetRef::sample();
    first.save(&asset_ref).unwrap();
    let mut library_ref = asset_ref.clone();
    library_ref.owner_kind = "channel".into();
    library_ref.owner_id = one.as_str().into();
    library_ref.role = "bgm:fixture".into();
    first.save(&library_ref).unwrap();
    library_ref.owner_id = "two".into();
    assert!(first.save(&library_ref).is_err());
    assert!(first.delete::<Project>(&Project::sample().key()).is_err());
    assert!(store
        .global_repository()
        .delete::<Asset>(&Asset::sample().key())
        .is_err());
    assert!(store
        .global_repository()
        .list::<AppSetting>()
        .unwrap()
        .is_empty());
    assert!(store.delete_channel(&one).unwrap());
    assert_eq!(store.channel_name(&one).unwrap(), None);
    assert!(store.repository(&one).is_err());
    assert!(store
        .channels()
        .unwrap()
        .iter()
        .any(|channel| channel.channel_id == one && channel.archived_at.is_some()));
    assert!(first.save(&Project::sample()).is_err());
    assert_eq!(
        store
            .connection
            .query_row(
                "SELECT count(*) FROM projects WHERE channel_id='one'",
                [],
                |row| row.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
}

#[test]
fn revisions_are_append_only_and_default_template_is_unique() {
    let (_temporary, _paths, store) = crate::tests::fixture();
    let one = ChannelId::new("one").unwrap();
    store.create_channel(&one, "一").unwrap();
    let repository = store.repository(&one).unwrap();
    repository.save(&Topic::sample()).unwrap();
    repository.save(&Project::sample()).unwrap();
    let revision = ProjectRevision::sample();
    repository.save(&revision).unwrap();
    assert!(repository.save(&revision).is_err());
    assert!(repository
        .delete::<ProjectRevision>(&revision.key())
        .is_err());
    let mut template = PromptTemplate::sample();
    repository.save(&template).unwrap();
    template.id = "second".into();
    assert!(repository.save(&template).is_err());
}

#[test]
fn schedule_slots_keep_shorts_and_long_at_the_same_time() {
    let (_temporary, _paths, store) = crate::tests::fixture();
    let channel = ChannelId::new("one").unwrap();
    store.create_channel(&channel, "一").unwrap();
    let repository = store.repository(&channel).unwrap();
    let shorts = ScheduleSlot::sample();
    let mut long = shorts.clone();
    long.format = "long".into();
    repository.save(&shorts).unwrap();
    repository.save(&long).unwrap();
    assert_eq!(repository.list::<ScheduleSlot>().unwrap().len(), 2);
    assert_eq!(
        repository.get::<ScheduleSlot>(&shorts.key()).unwrap(),
        Some(shorts)
    );
    assert_eq!(
        repository.get::<ScheduleSlot>(&long.key()).unwrap(),
        Some(long)
    );
    let mut invalid = ScheduleSlot::sample();
    invalid.format = "unknown".into();
    assert!(repository.save(&invalid).is_err());
}
