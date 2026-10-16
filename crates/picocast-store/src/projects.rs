//! 台本のグラフと追記専用スナップショットを一つの取引で保存する。
use crate::{
    db_failure, failure,
    repository::{
        self, Line, LineKey, Project, ProjectKey, ProjectRevision, Record, Scene, SceneKey,
    },
    Store,
};
use picocast_core::{ChannelId, Result};
use rusqlite::{params, Connection, TransactionBehavior};
use std::collections::{BTreeMap, BTreeSet};

fn conflict() -> picocast_core::AppError {
    failure(
        "E-STORE-IDENTITY",
        "台本の所属・版・参照先が一致しません。",
        "最新の台本を読み直し、既存素材の参照を確認して保存してください。",
    )
}

fn project_graph<R: Record>(
    connection: &Connection,
    channel: &ChannelId,
    project: &str,
    filter: &str,
) -> Result<Vec<R>> {
    let mut statement = connection
        .prepare(&format!(
            "SELECT {} FROM {} WHERE channel_id=? AND {filter}",
            R::COLUMNS.join(","),
            R::TABLE
        ))
        .map_err(db_failure)?;
    let result = statement
        .query_map(params![channel.as_str(), project], R::read)
        .map_err(db_failure)?
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(db_failure)?;
    Ok(result)
}

fn check_revision(
    connection: &Connection,
    channel: &ChannelId,
    id: &str,
    revision: i64,
) -> Result<Option<Project>> {
    if id.is_empty() || revision <= 0 {
        return Err(conflict());
    }
    let old = repository::get::<Project>(
        connection,
        &ProjectKey {
            channel_id: channel.clone(),
            id: id.into(),
        },
        Some(channel),
    )?;
    let previous = old.as_ref().map_or(0, |old| old.current_revision);
    let maximum:i64=connection.query_row("SELECT COALESCE(MAX(revision),0) FROM project_revisions WHERE channel_id=? AND project_id=?",params![channel.as_str(),id],|row|row.get(0)).map_err(db_failure)?;
    if previous.checked_add(1) != Some(revision) || previous != maximum {
        return Err(conflict());
    }
    Ok(old)
}

impl Store {
    /// 有料生成より前の照合。最終保存の取引内でも同じ検査を行う。
    pub fn check_project_revision(
        &self,
        channel: &ChannelId,
        id: &str,
        revision: i64,
    ) -> Result<Option<Project>> {
        self.require_channel(channel)?;
        check_revision(&self.connection, channel, id, revision)
    }
    pub fn project_graph(
        &self,
        channel: &ChannelId,
        project: &str,
    ) -> Result<(Vec<Scene>, Vec<Line>)> {
        self.require_channel(channel)?;
        Ok((project_graph::<Scene>(&self.connection,channel,project,"project_id=?")?,
            project_graph::<Line>(&self.connection,channel,project,"scene_id IN (SELECT id FROM scenes WHERE channel_id=lines.channel_id AND project_id=?)")?))
    }
    pub fn save_project_revision(
        &mut self,
        channel: &ChannelId,
        project: &Project,
        revision: &ProjectRevision,
        scenes: &[Scene],
        lines: &[Line],
    ) -> Result<()> {
        self.require_channel(channel)?;
        if &project.channel_id != channel
            || &revision.channel_id != channel
            || revision.project_id != project.id
            || revision.revision != project.current_revision
        {
            return Err(conflict());
        }
        let mut scene_ids = BTreeSet::new();
        let mut scene_orders = BTreeSet::new();
        for scene in scenes {
            if &scene.channel_id != channel
                || scene.project_id != project.id
                || scene.ord < 0
                || !scene_ids.insert(scene.id.as_str())
                || !scene_orders.insert(scene.ord)
            {
                return Err(conflict());
            }
        }
        if scene_orders
            .iter()
            .copied()
            .ne(0..i64::try_from(scenes.len()).map_err(|_| conflict())?)
        {
            return Err(conflict());
        }
        let mut line_ids = BTreeSet::new();
        let mut line_orders: BTreeMap<&str, BTreeSet<i64>> = BTreeMap::new();
        for line in lines {
            if &line.channel_id != channel
                || !scene_ids.contains(line.scene_id.as_str())
                || line.ord < 0
                || !line_ids.insert(line.id.as_str())
                || !line_orders
                    .entry(&line.scene_id)
                    .or_default()
                    .insert(line.ord)
            {
                return Err(conflict());
            }
        }
        for orders in line_orders.values() {
            if orders
                .iter()
                .copied()
                .ne(0..i64::try_from(orders.len()).map_err(|_| conflict())?)
            {
                return Err(conflict());
            }
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let active: bool = transaction
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM channels WHERE channel_id=? AND archived_at IS NULL)",
                [channel.as_str()],
                |row| row.get(0),
            )
            .map_err(db_failure)?;
        if !active {
            return Err(conflict());
        }
        let old = check_revision(&transaction, channel, &project.id, project.current_revision)?;
        if old
            .as_ref()
            .is_some_and(|old| old.created_at != project.created_at)
        {
            return Err(conflict());
        }
        let old_scenes =
            project_graph::<Scene>(&transaction, channel, &project.id, "project_id=?")?;
        let old_lines=project_graph::<Line>(&transaction,channel,&project.id,"scene_id IN (SELECT id FROM scenes WHERE channel_id=lines.channel_id AND project_id=?)")?;
        let belonging: BTreeSet<_> = old_scenes
            .iter()
            .filter(|scene| scene.project_id == project.id)
            .map(|scene| scene.id.as_str())
            .collect();
        for scene in scenes {
            if repository::get::<Scene>(
                &transaction,
                &SceneKey {
                    channel_id: channel.clone(),
                    id: scene.id.clone(),
                },
                Some(channel),
            )?
            .is_some_and(|old| old.project_id != project.id)
            {
                return Err(conflict());
            }
        }
        for line in lines {
            if let Some(mut old) = repository::get::<Line>(
                &transaction,
                &LineKey {
                    channel_id: channel.clone(),
                    id: line.id.clone(),
                },
                Some(channel),
            )? {
                if !belonging.contains(old.scene_id.as_str()) {
                    return Err(conflict());
                }
                old.ord = line.ord;
                old.scene_id = line.scene_id.clone();
                if old != *line {
                    // 依存hashの無効化と再生成が原子的に実装されるまで、古い音声等の誤使用を保存境界で止める。
                    let referenced:bool=transaction.query_row("SELECT EXISTS(SELECT 1 FROM asset_refs WHERE channel_id=? AND owner_kind='line' AND owner_id=?)",params![channel.as_str(),line.id],|row|row.get(0)).map_err(db_failure)?;
                    if referenced {
                        return Err(conflict());
                    }
                }
            }
        }
        // 消える行だけを削除する。音声・素材参照が残る場合はFK/triggerで取引全体を戻す。
        for old in old_lines.iter().filter(|line| {
            belonging.contains(line.scene_id.as_str()) && !line_ids.contains(line.id.as_str())
        }) {
            transaction
                .execute(
                    "DELETE FROM lines WHERE channel_id=? AND id=?",
                    params![channel.as_str(), old.id],
                )
                .map_err(db_failure)?;
        }
        // 並び替えの一時領域は既存最大値より上に置き、UNIQUEを常に維持する。
        let scene_offset = old_scenes
            .iter()
            .map(|row| row.ord)
            .max()
            .unwrap_or(0)
            .checked_add(i64::try_from(scenes.len()).map_err(|_| conflict())?)
            .and_then(|value| value.checked_add(1))
            .ok_or_else(conflict)?;
        let line_offset = old_lines
            .iter()
            .map(|row| row.ord)
            .max()
            .unwrap_or(0)
            .checked_add(i64::try_from(lines.len()).map_err(|_| conflict())?)
            .and_then(|value| value.checked_add(1))
            .ok_or_else(conflict)?;
        for old in &old_lines {
            if belonging.contains(old.scene_id.as_str()) {
                let ord = old.ord.checked_add(line_offset).ok_or_else(conflict)?;
                transaction
                    .execute(
                        "UPDATE lines SET ord=? WHERE channel_id=? AND id=?",
                        params![ord, channel.as_str(), old.id],
                    )
                    .map_err(db_failure)?;
            }
        }
        for old in &old_scenes {
            if belonging.contains(old.id.as_str()) {
                let ord = old.ord.checked_add(scene_offset).ok_or_else(conflict)?;
                transaction
                    .execute(
                        "UPDATE scenes SET ord=? WHERE channel_id=? AND id=?",
                        params![ord, channel.as_str(), old.id],
                    )
                    .map_err(db_failure)?;
            }
        }
        repository::save(&transaction, project)?;
        repository::save(&transaction, revision)?;
        for scene in scenes {
            repository::save(&transaction, scene)?;
        }
        for line in lines {
            repository::save(&transaction, line)?;
        }
        for old in old_scenes.iter().filter(|scene| {
            scene.project_id == project.id && !scene_ids.contains(scene.id.as_str())
        }) {
            transaction
                .execute(
                    "DELETE FROM scenes WHERE channel_id=? AND id=?",
                    params![channel.as_str(), old.id],
                )
                .map_err(db_failure)?;
        }
        transaction.commit().map_err(db_failure)
    }
}
