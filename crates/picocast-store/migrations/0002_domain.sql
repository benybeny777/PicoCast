-- R0の識別子を維持し、設計上のidは同一値を指す別名にする。
ALTER TABLE channels ADD COLUMN id TEXT GENERATED ALWAYS AS (channel_id) VIRTUAL;
CREATE UNIQUE INDEX channels_id ON channels(id);
ALTER TABLE channels ADD COLUMN handle TEXT;
ALTER TABLE channels ADD COLUMN language TEXT;
ALTER TABLE channels ADD COLUMN timezone TEXT;
ALTER TABLE channels ADD COLUMN genre_pack_id TEXT;
ALTER TABLE channels ADD COLUMN character_set_id TEXT;
ALTER TABLE channels ADD COLUMN youtube_channel_id TEXT;
ALTER TABLE channels ADD COLUMN operator TEXT NOT NULL DEFAULT 'legacy' CHECK(operator IN ('legacy','rust'));
ALTER TABLE channels ADD COLUMN archived_at TEXT;
ALTER TABLE channels ADD COLUMN updated_at TEXT;
UPDATE channels SET updated_at=created_at;

CREATE TABLE app_settings(
    key TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    updated_at TEXT NOT NULL
);
CREATE TABLE channel_settings(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,key)
);
INSERT INTO channel_settings SELECT * FROM settings;
DROP TABLE settings;
CREATE TABLE secrets(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    secret_type TEXT NOT NULL,
    nonce BLOB NOT NULL CHECK(length(nonce)=12),
    encrypted_value BLOB NOT NULL,
    key_version INTEGER NOT NULL CHECK(key_version=2),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,secret_type)
);
INSERT INTO secrets SELECT * FROM encrypted_secrets;
DROP TABLE encrypted_secrets;

CREATE TABLE audit_log(
    id TEXT PRIMARY KEY NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail_json TEXT NOT NULL CHECK(json_valid(detail_json))
);
CREATE TABLE crash_reports(
    id TEXT PRIMARY KEY NOT NULL,
    at TEXT NOT NULL,
    version TEXT NOT NULL,
    step TEXT NOT NULL,
    summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
    acknowledged_at TEXT
);
CREATE TABLE assets(
    sha256 TEXT PRIMARY KEY NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    kind TEXT NOT NULL,
    ext TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes>=0),
    created_at TEXT NOT NULL,
    provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json))
);
CREATE TABLE asset_licenses(
    sha256 TEXT PRIMARY KEY NOT NULL REFERENCES assets(sha256) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    terms_url TEXT NOT NULL,
    credit_text TEXT NOT NULL,
    commercial_ok INTEGER NOT NULL CHECK(commercial_ok IN (0,1)),
    checked_at TEXT NOT NULL
);
CREATE TABLE music_tags(
    sha256 TEXT PRIMARY KEY NOT NULL REFERENCES assets(sha256) ON DELETE RESTRICT,
    mood TEXT NOT NULL,
    tempo_bpm REAL CHECK(tempo_bpm>0),
    duration_ms INTEGER NOT NULL CHECK(duration_ms>=0),
    loop_start_ms INTEGER CHECK(loop_start_ms>=0),
    loop_end_ms INTEGER CHECK(loop_end_ms>=0),
    manual INTEGER NOT NULL CHECK(manual IN (0,1)),
    CHECK(loop_start_ms IS NULL OR loop_end_ms IS NULL OR loop_start_ms<loop_end_ms),
    CHECK(loop_end_ms IS NULL OR loop_end_ms<=duration_ms)
);
CREATE TABLE characters(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    voice_provider TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    style_map_json TEXT NOT NULL CHECK(json_valid(style_map_json)),
    credit_text TEXT NOT NULL,
    usage_rules_json TEXT NOT NULL CHECK(json_valid(usage_rules_json)),
    layer_manifest_sha256 TEXT REFERENCES assets(sha256) ON DELETE RESTRICT,
    PRIMARY KEY(channel_id,id)
);
CREATE TABLE prompt_templates(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK(kind IN ('script','title','meeting')),
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL CHECK(is_default IN (0,1)),
    PRIMARY KEY(channel_id,id)
);
CREATE UNIQUE INDEX prompt_default ON prompt_templates(channel_id,kind) WHERE is_default=1;
CREATE TABLE prompt_template_versions(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    template_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>0),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(channel_id,template_id,version),
    FOREIGN KEY(channel_id,template_id) REFERENCES prompt_templates(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE topics(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('suggest','trend','comment','series','calendar','manual','legacy')),
    source_ref TEXT,
    priority INTEGER NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,id)
);
CREATE TABLE projects(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    format TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    topic_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_json TEXT NOT NULL CHECK(json_valid(tags_json)),
    publish_at TEXT,
    synthetic_media INTEGER NOT NULL CHECK(synthetic_media IN (0,1)),
    youtube_video_id TEXT,
    current_revision INTEGER NOT NULL CHECK(current_revision>0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,id),
    FOREIGN KEY(channel_id,topic_id) REFERENCES topics(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE project_revisions(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    author TEXT NOT NULL CHECK(author IN ('user','ai','import')),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,project_id,revision),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE scenes(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    ord INTEGER NOT NULL CHECK(ord>=0),
    background_sha256 TEXT REFERENCES assets(sha256) ON DELETE RESTRICT,
    background_prompt TEXT,
    camera_json TEXT NOT NULL CHECK(json_valid(camera_json)),
    mood TEXT NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY(channel_id,id),
    UNIQUE(channel_id,project_id,ord),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE lines(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    scene_id TEXT NOT NULL,
    ord INTEGER NOT NULL CHECK(ord>=0),
    speaker_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reading_override TEXT,
    accent_json TEXT NOT NULL CHECK(json_valid(accent_json)),
    expression TEXT,
    style_id TEXT,
    emphasis_json TEXT NOT NULL CHECK(json_valid(emphasis_json)),
    pause_after_ms INTEGER NOT NULL CHECK(pause_after_ms>=0),
    PRIMARY KEY(channel_id,id),
    UNIQUE(channel_id,scene_id,ord),
    FOREIGN KEY(channel_id,scene_id) REFERENCES scenes(channel_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(channel_id,speaker_id) REFERENCES characters(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE asset_refs(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('channel','project','scene','line','character')),
    owner_id TEXT NOT NULL,
    sha256 TEXT NOT NULL REFERENCES assets(sha256) ON DELETE RESTRICT,
    role TEXT NOT NULL,
    PRIMARY KEY(channel_id,owner_kind,owner_id,sha256,role)
);
CREATE TRIGGER asset_refs_owner_insert BEFORE INSERT ON asset_refs BEGIN
 SELECT CASE WHEN NOT (
 (NEW.owner_kind='channel' AND EXISTS(SELECT 1 FROM channels WHERE channel_id=NEW.channel_id AND channel_id=NEW.owner_id)) OR
 (NEW.owner_kind='project' AND EXISTS(SELECT 1 FROM projects WHERE channel_id=NEW.channel_id AND id=NEW.owner_id)) OR
 (NEW.owner_kind='scene' AND EXISTS(SELECT 1 FROM scenes WHERE channel_id=NEW.channel_id AND id=NEW.owner_id)) OR
 (NEW.owner_kind='line' AND EXISTS(SELECT 1 FROM lines WHERE channel_id=NEW.channel_id AND id=NEW.owner_id)) OR
 (NEW.owner_kind='character' AND EXISTS(SELECT 1 FROM characters WHERE channel_id=NEW.channel_id AND id=NEW.owner_id)))
 THEN RAISE(ABORT,'invalid asset owner') END;
END;
CREATE TRIGGER asset_refs_owner_update BEFORE UPDATE ON asset_refs BEGIN
 SELECT CASE WHEN NEW.channel_id!=OLD.channel_id OR NEW.owner_kind!=OLD.owner_kind OR NEW.owner_id!=OLD.owner_id THEN RAISE(ABORT,'immutable asset owner') END;
 SELECT CASE WHEN NEW.owner_kind='channel' AND NOT EXISTS(SELECT 1 FROM channels WHERE channel_id=NEW.channel_id AND channel_id=NEW.owner_id) THEN RAISE(ABORT,'invalid channel asset owner') END;
END;
-- 多相の素材所有者は通常の外部キーにできないため、親の削除も参照がある間は止める。
CREATE TRIGGER projects_asset_refs_delete BEFORE DELETE ON projects WHEN EXISTS(SELECT 1 FROM asset_refs WHERE channel_id=OLD.channel_id AND owner_kind='project' AND owner_id=OLD.id) BEGIN SELECT RAISE(ABORT,'referenced asset owner'); END;
CREATE TRIGGER scenes_asset_refs_delete BEFORE DELETE ON scenes WHEN EXISTS(SELECT 1 FROM asset_refs WHERE channel_id=OLD.channel_id AND owner_kind='scene' AND owner_id=OLD.id) BEGIN SELECT RAISE(ABORT,'referenced asset owner'); END;
CREATE TRIGGER lines_asset_refs_delete BEFORE DELETE ON lines WHEN EXISTS(SELECT 1 FROM asset_refs WHERE channel_id=OLD.channel_id AND owner_kind='line' AND owner_id=OLD.id) BEGIN SELECT RAISE(ABORT,'referenced asset owner'); END;
CREATE TRIGGER characters_asset_refs_delete BEFORE DELETE ON characters WHEN EXISTS(SELECT 1 FROM asset_refs WHERE channel_id=OLD.channel_id AND owner_kind='character' AND owner_id=OLD.id) BEGIN SELECT RAISE(ABORT,'referenced asset owner'); END;
CREATE TABLE jobs(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    not_before TEXT,
    attempts INTEGER NOT NULL CHECK(attempts>=0),
    max_attempts INTEGER NOT NULL CHECK(max_attempts>0),
    lease_owner TEXT,
    lease_until TEXT,
    heartbeat_at TEXT,
    wait_reason TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY(channel_id,id),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT
);
CREATE INDEX jobs_queue ON jobs(status,not_before,priority);
CREATE TABLE job_steps(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    job_id TEXT NOT NULL,
    step TEXT NOT NULL,
    step_version INTEGER NOT NULL CHECK(step_version>0),
    inputs_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    output_json TEXT NOT NULL CHECK(json_valid(output_json)),
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER CHECK(duration_ms>=0),
    cost_micros INTEGER CHECK(cost_micros>=0),
    PRIMARY KEY(channel_id,job_id,step),
    FOREIGN KEY(channel_id,job_id) REFERENCES jobs(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE step_cache(
    step TEXT NOT NULL,
    step_version INTEGER NOT NULL CHECK(step_version>0),
    inputs_hash TEXT NOT NULL,
    outputs_json TEXT NOT NULL CHECK(json_valid(outputs_json)),
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    PRIMARY KEY(step,step_version,inputs_hash)
);
CREATE TABLE qa_results(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    check_id TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('pass','warn','fail')),
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,project_id,revision,check_id),
    FOREIGN KEY(channel_id,project_id,revision) REFERENCES project_revisions(channel_id,project_id,revision) ON DELETE RESTRICT
);
CREATE TABLE uploads(
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    session_uri TEXT,
    bytes_sent INTEGER NOT NULL CHECK(bytes_sent>=0),
    video_id TEXT,
    status TEXT NOT NULL,
    processing_status TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,id),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE youtube_videos(
    video_id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT,
    title TEXT NOT NULL,
    privacy TEXT NOT NULL,
    published_at TEXT,
    synced_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,video_id),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE quota_ledger(
    day_pt TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    endpoint TEXT NOT NULL,
    units INTEGER NOT NULL CHECK(units>=0),
    PRIMARY KEY(channel_id,day_pt,endpoint)
);
CREATE TABLE analytics_daily(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    video_id TEXT NOT NULL,
    date TEXT NOT NULL,
    views INTEGER CHECK(views>=0),
    watch_seconds REAL CHECK(watch_seconds>=0),
    avg_view_pct REAL CHECK(avg_view_pct>=0),
    impressions INTEGER CHECK(impressions>=0),
    ctr REAL CHECK(ctr>=0 AND ctr<=100),
    subs_gained INTEGER,
    revenue_micros INTEGER CHECK(revenue_micros>=0),
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,video_id,date),
    FOREIGN KEY(channel_id,video_id) REFERENCES youtube_videos(channel_id,video_id) ON DELETE RESTRICT
);
CREATE TABLE retention_curves(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    video_id TEXT NOT NULL,
    fetched_on TEXT NOT NULL,
    curve_json TEXT NOT NULL CHECK(json_valid(curve_json)),
    PRIMARY KEY(channel_id,video_id,fetched_on),
    FOREIGN KEY(channel_id,video_id) REFERENCES youtube_videos(channel_id,video_id) ON DELETE RESTRICT
);
CREATE TABLE insights(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    pattern_json TEXT NOT NULL CHECK(json_valid(pattern_json)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    score REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(channel_id,id)
);
CREATE TABLE insight_usage(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    insight_id TEXT NOT NULL,
    PRIMARY KEY(channel_id,project_id,insight_id),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(channel_id,insight_id) REFERENCES insights(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE experiments(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    factor TEXT NOT NULL,
    variants_json TEXT NOT NULL CHECK(json_valid(variants_json)),
    status TEXT NOT NULL,
    PRIMARY KEY(channel_id,id)
);
CREATE TABLE experiment_assignments(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    PRIMARY KEY(channel_id,project_id,experiment_id),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(channel_id,experiment_id) REFERENCES experiments(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE autopilot_policies(
    channel_id TEXT PRIMARY KEY NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    daily_count INTEGER NOT NULL CHECK(daily_count>=0),
    quality_threshold REAL NOT NULL,
    budget_micros INTEGER NOT NULL CHECK(budget_micros>=0),
    window_json TEXT NOT NULL CHECK(json_valid(window_json)),
    paused_reason TEXT,
    paused_at TEXT
);
CREATE TABLE schedule_slots(
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    format TEXT NOT NULL CHECK(format IN ('shorts','long')),
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
    local_time TEXT NOT NULL CHECK(length(local_time)=5 AND local_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(local_time,1,2)<='23'),
    PRIMARY KEY(channel_id,format,weekday,local_time)
);
CREATE TABLE cost_ledger(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    project_id TEXT,
    job_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    units_json TEXT NOT NULL CHECK(json_valid(units_json)),
    cost_micros INTEGER CHECK(cost_micros>=0),
    at TEXT NOT NULL,
    PRIMARY KEY(channel_id,id),
    FOREIGN KEY(channel_id,project_id) REFERENCES projects(channel_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(channel_id,job_id) REFERENCES jobs(channel_id,id) ON DELETE RESTRICT
);
CREATE TABLE notifications(
    id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    message_key TEXT NOT NULL,
    args_json TEXT NOT NULL CHECK(json_valid(args_json)),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY(channel_id,id)
);
CREATE UNIQUE INDEX notifications_active_dedupe ON notifications(channel_id,dedupe_key) WHERE resolved_at IS NULL;
CREATE TABLE reading_entries(
    surface TEXT NOT NULL,
    source TEXT NOT NULL,
    reading TEXT NOT NULL,
    accent_json TEXT NOT NULL CHECK(json_valid(accent_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(surface,source)
);
CREATE TABLE reading_candidates(
    surface TEXT PRIMARY KEY NOT NULL,
    reading TEXT NOT NULL,
    reason TEXT NOT NULL,
    source TEXT NOT NULL,
    auto_applied INTEGER NOT NULL CHECK(auto_applied IN (0,1)),
    review_required INTEGER NOT NULL CHECK(review_required IN (0,1)),
    updated_at TEXT NOT NULL
);
