//! UTC 日単位の費用・トークン予算を、永続的な予約と実績で一元管理する。

use crate::{
    db_failure, failure,
    repository::{self, Channel, ChannelKey, CostLedger, CostLedgerKey},
    Store,
};
use picocast_core::{clock::Timestamp, AppError, ChannelId, Result};
use rusqlite::{Connection, TransactionBehavior};
use serde::{Deserialize, Serialize};

const METADATA_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct UtcDay(String);

impl UtcDay {
    pub fn parse(value: &str) -> Result<Self> {
        let bytes = value.as_bytes();
        if bytes.len() != 10
            || bytes[4] != b'-'
            || bytes[7] != b'-'
            || bytes
                .iter()
                .enumerate()
                .any(|(index, byte)| !matches!(index, 4 | 7) && !byte.is_ascii_digit())
        {
            return Err(budget(
                "費用の対象日は UTC の YYYY-MM-DD で指定してください。",
            ));
        }
        Timestamp::parse(&format!("{value}T00:00:00Z"))
            .map_err(|_| budget("費用の対象日が実在しません。"))?;
        Ok(Self(value.to_owned()))
    }

    pub fn from_timestamp(at: &Timestamp) -> Self {
        let mut day = at.to_utc_iso();
        day.truncate(10);
        Self(day)
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for UtcDay {
    type Error = AppError;
    fn try_from(value: String) -> Result<Self> {
        Self::parse(&value)
    }
}

impl From<UtcDay> for String {
    fn from(value: UtcDay) -> Self {
        value.0
    }
}

/// 金額はマイクロ米ドル。上限が不明な呼び出しをゼロ扱いしない。
#[derive(Debug, Clone)]
pub struct AiCostReservation {
    pub channel_id: ChannelId,
    pub request_id: String,
    pub day: UtcDay,
    pub daily_budget_micros: u64,
    pub max_cost_micros: Option<u64>,
    pub daily_token_budget: u64,
    pub max_input_tokens: u64,
    pub max_output_tokens: u64,
    pub provider: String,
    pub model: String,
    pub at: Timestamp,
    pub project_id: Option<String>,
    pub job_id: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AiCostState {
    Reserved,
    Succeeded,
    Failed,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AiCostSettlement {
    ImagesSucceeded {
        actual_cost_micros: u64,
        images: u64,
    },
    Succeeded {
        actual_cost_micros: u64,
        input_tokens: u64,
        output_tokens: u64,
    },
    /// 送信先が要求を受理せず、費用もトークンもゼロと確認できた失敗だけを解放する。
    Failed {
        actual_cost_micros: u64,
        error_code: String,
    },
    /// 接続断・キャンセル・usage 欠損など。送信済みか不明なら予約を維持する。
    Unknown { error_code: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AiCostRecord {
    pub max_images: Option<u64>,
    pub images: Option<u64>,
    pub channel_id: ChannelId,
    pub request_id: String,
    pub day: UtcDay,
    pub state: AiCostState,
    pub max_cost_micros: u64,
    pub actual_cost_micros: Option<u64>,
    pub max_input_tokens: u64,
    pub max_output_tokens: u64,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub error_code: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AiCostTotals {
    pub images: u64,
    pub held_images: u64,
    pub charged_micros: u64,
    pub held_micros: u64,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub held_tokens: u64,
    pub unpriced_entries: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Metadata {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    max_images: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    images: Option<u64>,
    version: u32,
    day: UtcDay,
    state: AiCostState,
    max_cost_micros: u64,
    max_input_tokens: u64,
    max_output_tokens: u64,
    actual_cost_micros: Option<u64>,
    input_tokens: Option<u64>,
    output_tokens: Option<u64>,
    error_code: Option<String>,
}

impl Metadata {
    fn from_row(row: &CostLedger) -> Result<Self> {
        let value = row
            .units_json
            .get("ai_cost")
            .ok_or_else(|| reservation("指定の記録は AI 費用予約ではありません。"))?;
        let metadata: Self = serde_json::from_value(value.clone())
            .map_err(|_| usage("AI 費用台帳の形式が不正です。"))?;
        if metadata.version != METADATA_VERSION || metadata.day != UtcDay::from_timestamp(&row.at) {
            return Err(usage("AI 費用台帳の版または UTC 日が不正です。"));
        }
        money(metadata.max_cost_micros)?;
        add(metadata.max_input_tokens, metadata.max_output_tokens)?;
        let column_cost = row
            .cost_micros
            .map(u64::try_from)
            .transpose()
            .map_err(|_| usage("AI 費用台帳に負の金額があります。"))?;
        if column_cost != metadata.actual_cost_micros {
            return Err(usage("AI 費用台帳の実績が一致しません。"));
        }
        let pending = matches!(metadata.state, AiCostState::Reserved | AiCostState::Unknown);
        match metadata.max_images {
            Some(maximum)
                if maximum > 0
                    && metadata.max_input_tokens == 0
                    && metadata.max_output_tokens == 0 =>
            {
                if (pending && metadata.images.is_some()) || (!pending && metadata.images.is_none())
                {
                    return Err(usage("画像費用の個数と状態が一致しません。"));
                }
            }
            None if metadata.images.is_none() => {}
            _ => return Err(usage("費用の計量単位が不正です。")),
        }
        if pending {
            if metadata.actual_cost_micros.is_some()
                || metadata.input_tokens.is_some()
                || metadata.output_tokens.is_some()
            {
                return Err(usage("未確定の AI 予約に確定実績があります。"));
            }
        } else if metadata.actual_cost_micros.is_none()
            || metadata.input_tokens.is_none()
            || metadata.output_tokens.is_none()
        {
            return Err(usage("AI 費用の確定実績が欠けています。"));
        }
        match metadata.state {
            AiCostState::Reserved | AiCostState::Succeeded if metadata.error_code.is_some() => {
                return Err(usage("AI 費用の状態とエラー分類が一致しません。"))
            }
            AiCostState::Failed | AiCostState::Unknown => {
                validate_error_code(
                    metadata
                        .error_code
                        .as_deref()
                        .ok_or_else(|| usage("AI 費用のエラー分類がありません。"))?,
                )?;
            }
            _ => {}
        }
        if metadata.state == AiCostState::Failed
            && (metadata.actual_cost_micros != Some(0)
                || metadata.input_tokens != Some(0)
                || metadata.output_tokens != Some(0))
        {
            return Err(usage("確定無課金の失敗に非ゼロ実績があります。"));
        }
        Ok(metadata)
    }

    fn record(&self, row: &CostLedger) -> AiCostRecord {
        AiCostRecord {
            max_images: self.max_images,
            images: self.images,
            channel_id: row.channel_id.clone(),
            request_id: row.id.clone(),
            day: self.day.clone(),
            state: self.state,
            max_cost_micros: self.max_cost_micros,
            actual_cost_micros: self.actual_cost_micros,
            max_input_tokens: self.max_input_tokens,
            max_output_tokens: self.max_output_tokens,
            input_tokens: self.input_tokens,
            output_tokens: self.output_tokens,
            error_code: self.error_code.clone(),
        }
    }

    fn is_overrun(&self) -> bool {
        self.images
            .zip(self.max_images)
            .is_some_and(|(actual, max)| actual > max)
            || self
                .actual_cost_micros
                .is_some_and(|actual| actual > self.max_cost_micros)
            || self
                .input_tokens
                .is_some_and(|actual| actual > self.max_input_tokens)
            || self
                .output_tokens
                .is_some_and(|actual| actual > self.max_output_tokens)
    }
}

impl Store {
    /// 画像料金も同じ台帳へ予約する。トークンを架空の枚数として流用しない。
    pub fn reserve_ai_image_cost(
        &mut self,
        request: &AiCostReservation,
        max_images: u64,
    ) -> Result<AiCostRecord> {
        if max_images == 0 || request.max_input_tokens != 0 || request.max_output_tokens != 0 {
            return Err(budget("画像予約の枚数または計量単位が不正です。"));
        }
        self.reserve_ai_cost_inner(request, Some(max_images))
    }
    pub fn ai_cost_totals(&self, channel_id: &ChannelId, day: &UtcDay) -> Result<AiCostTotals> {
        channel_record(&self.connection, channel_id)?;
        totals(&self.connection, channel_id, day)
    }

    pub fn reserve_ai_cost(&mut self, request: &AiCostReservation) -> Result<AiCostRecord> {
        self.reserve_ai_cost_inner(request, None)
    }
    fn reserve_ai_cost_inner(
        &mut self,
        request: &AiCostReservation,
        max_images: Option<u64>,
    ) -> Result<AiCostRecord> {
        validate_identity(&request.request_id)?;
        validate_identity(&request.provider)?;
        validate_identity(&request.model)?;
        if request.day != UtcDay::from_timestamp(&request.at) {
            return Err(budget("費用予約の対象日と UTC 時刻が一致しません。"));
        }
        let maximum = request
            .max_cost_micros
            .ok_or_else(|| budget("呼び出し費用の上限が不明なため送信できません。"))?;
        money(maximum)?;
        money(request.daily_budget_micros)?;
        let maximum_tokens = add(request.max_input_tokens, request.max_output_tokens)?;
        if maximum_tokens == 0 && max_images.is_none() {
            return Err(budget("呼び出しトークン数の上限がありません。"));
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        require_active(&transaction, &request.channel_id)?;
        let key = CostLedgerKey {
            channel_id: request.channel_id.clone(),
            id: request.request_id.clone(),
        };
        if repository::get::<CostLedger>(&transaction, &key, Some(&request.channel_id))?.is_some() {
            return Err(reservation(
                "同じ送信識別子は既に予約済みです。再送は許可しません。",
            ));
        }
        let current = totals(&transaction, &request.channel_id, &request.day)?;
        if current.unpriced_entries != 0 {
            return Err(budget(
                "価格が未確定の既存台帳があるため予算を判定できません。",
            ));
        }
        if add(add(current.charged_micros, current.held_micros)?, maximum)?
            > request.daily_budget_micros
            || (max_images.is_none()
                && add(
                    add(
                        add(current.input_tokens, current.output_tokens)?,
                        current.held_tokens,
                    )?,
                    maximum_tokens,
                )? > request.daily_token_budget)
        {
            return Err(budget(
                "日次の費用またはトークン予算を超えるため送信できません。",
            ));
        }
        let metadata = Metadata {
            max_images,
            images: None,
            version: METADATA_VERSION,
            day: request.day.clone(),
            state: AiCostState::Reserved,
            max_cost_micros: maximum,
            max_input_tokens: request.max_input_tokens,
            max_output_tokens: request.max_output_tokens,
            actual_cost_micros: None,
            input_tokens: None,
            output_tokens: None,
            error_code: None,
        };
        let row = CostLedger {
            channel_id: request.channel_id.clone(),
            id: request.request_id.clone(),
            project_id: request.project_id.clone(),
            job_id: request.job_id.clone(),
            provider: request.provider.clone(),
            model: request.model.clone(),
            units_json: serde_json::json!({"ai_cost":metadata}),
            cost_micros: None,
            at: request.at.clone(),
        };
        repository::save(&transaction, &row)?;
        transaction.commit().map_err(db_failure)?;
        Ok(metadata.record(&row))
    }

    pub fn settle_ai_cost(
        &mut self,
        channel_id: &ChannelId,
        request_id: &str,
        settlement: &AiCostSettlement,
    ) -> Result<AiCostRecord> {
        validate_identity(request_id)?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        // 送信後にチャンネルがアーカイブされても、既存予約の請求実績は失わない。
        channel_record(&transaction, channel_id)?;
        let key = CostLedgerKey {
            channel_id: channel_id.clone(),
            id: request_id.to_owned(),
        };
        let mut row = repository::get::<CostLedger>(&transaction, &key, Some(channel_id))?
            .ok_or_else(|| reservation("同じチャンネルの費用予約が見つかりません。"))?;
        let previous = Metadata::from_row(&row)?;
        let mut next = previous.clone();
        match settlement {
            AiCostSettlement::ImagesSucceeded {
                actual_cost_micros,
                images,
            } => {
                if previous.max_images.is_none() {
                    return Err(usage("トークン予約を画像実績として精算できません。"));
                }
                money(*actual_cost_micros)?;
                next.state = AiCostState::Succeeded;
                next.actual_cost_micros = Some(*actual_cost_micros);
                next.images = Some(*images);
                next.input_tokens = Some(0);
                next.output_tokens = Some(0);
                next.error_code = None;
            }
            AiCostSettlement::Succeeded {
                actual_cost_micros,
                input_tokens,
                output_tokens,
            } => {
                if previous.max_images.is_some() {
                    return Err(usage("画像予約をトークン実績として精算できません。"));
                }
                money(*actual_cost_micros)?;
                add(*input_tokens, *output_tokens)?;
                next.state = AiCostState::Succeeded;
                next.actual_cost_micros = Some(*actual_cost_micros);
                next.input_tokens = Some(*input_tokens);
                next.output_tokens = Some(*output_tokens);
                next.error_code = None;
            }
            AiCostSettlement::Failed {
                actual_cost_micros,
                error_code,
            } => {
                validate_error_code(error_code)?;
                if *actual_cost_micros != 0 {
                    return Err(usage(
                        "課金を伴う失敗の usage が不明です。予約を維持して請求を確認してください。",
                    ));
                }
                next.state = AiCostState::Failed;
                next.actual_cost_micros = Some(0);
                next.input_tokens = Some(0);
                next.output_tokens = Some(0);
                next.error_code = Some(error_code.clone());
                if next.max_images.is_some() {
                    next.images = Some(0);
                }
            }
            AiCostSettlement::Unknown { error_code } => {
                validate_error_code(error_code)?;
                next.state = AiCostState::Unknown;
                next.error_code = Some(error_code.clone());
            }
        }
        if previous == next {
            transaction.commit().map_err(db_failure)?;
            return completed_record(&next, &row);
        }
        if !matches!(previous.state, AiCostState::Reserved | AiCostState::Unknown)
            || (previous.state == AiCostState::Unknown && next.state == AiCostState::Unknown)
        {
            return Err(reservation(
                "確定済みの費用または不明な送信の記録を異なる結果で上書きできません。",
            ));
        }
        let object = row
            .units_json
            .as_object_mut()
            .ok_or_else(|| usage("AI 費用台帳がオブジェクトではありません。"))?;
        object.insert(
            "ai_cost".into(),
            serde_json::to_value(&next)
                .map_err(|_| usage("AI 費用の実績を保存形式へ変換できません。"))?,
        );
        row.cost_micros = next.actual_cost_micros.map(money).transpose()?;
        repository::save(&transaction, &row)?;
        transaction.commit().map_err(db_failure)?;
        // 実請求の過少計上を避けるため、超過実績を保存してから失敗を返す。
        completed_record(&next, &row)
    }
}

fn completed_record(metadata: &Metadata, row: &CostLedger) -> Result<AiCostRecord> {
    if metadata.is_overrun() {
        return Err(usage(
            "確定した費用またはトークン数が予約上限を超えました。実績は保存済みです。",
        ));
    }
    Ok(metadata.record(row))
}

fn require_active(connection: &Connection, channel: &ChannelId) -> Result<()> {
    if channel_record(connection, channel)?.archived_at.is_some() {
        return Err(failure(
            "E-STORE-CHANNEL",
            "指定チャンネルはアーカイブされています。",
            "新規送信には登録済みでアーカイブされていないチャンネルを指定してください。",
        ));
    }
    Ok(())
}

fn channel_record(connection: &Connection, channel: &ChannelId) -> Result<Channel> {
    let key = ChannelKey {
        channel_id: channel.clone(),
    };
    repository::get::<Channel>(connection, &key, Some(channel))?.ok_or_else(|| {
        failure(
            "E-STORE-CHANNEL",
            "指定チャンネルが登録されていません。",
            "元の予約と同じ登録済みチャンネルを指定してください。",
        )
    })
}

fn totals(connection: &Connection, channel: &ChannelId, day: &UtcDay) -> Result<AiCostTotals> {
    let mut statement = connection.prepare("SELECT id,units_json,cost_micros,at FROM cost_ledger WHERE channel_id=?1 AND substr(at,1,10)=?2 ORDER BY id").map_err(db_failure)?;
    let rows = statement
        .query_map([channel.as_str(), day.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<i64>>(2)?,
                row.get::<_, String>(3)?,
            ))
        })
        .map_err(db_failure)?;
    let mut total = AiCostTotals::default();
    for row in rows {
        let (id, json, cost, at) = row.map_err(db_failure)?;
        let units = serde_json::from_str::<serde_json::Value>(&json)
            .map_err(|_| usage("費用台帳の JSON が壊れています。"))?;
        if units.get("ai_cost").is_some() {
            let row = CostLedger {
                id,
                channel_id: channel.clone(),
                project_id: None,
                job_id: None,
                provider: String::new(),
                model: String::new(),
                units_json: units,
                cost_micros: cost,
                at: Timestamp::parse(&at)?,
            };
            let metadata = Metadata::from_row(&row)?;
            match metadata.state {
                AiCostState::Reserved | AiCostState::Unknown => {
                    if let Some(images) = metadata.max_images {
                        total.held_images = add(total.held_images, images)?;
                    }
                    total.held_micros = add(total.held_micros, metadata.max_cost_micros)?;
                    total.held_tokens = add(
                        total.held_tokens,
                        add(metadata.max_input_tokens, metadata.max_output_tokens)?,
                    )?;
                }
                AiCostState::Succeeded | AiCostState::Failed => {
                    if let Some(images) = metadata.images {
                        total.images = add(total.images, images)?;
                    }
                    total.charged_micros = add(
                        total.charged_micros,
                        metadata
                            .actual_cost_micros
                            .ok_or_else(|| usage("費用の確定値がありません。"))?,
                    )?;
                    total.input_tokens = add(
                        total.input_tokens,
                        metadata
                            .input_tokens
                            .ok_or_else(|| usage("入力トークンの確定値がありません。"))?,
                    )?;
                    total.output_tokens = add(
                        total.output_tokens,
                        metadata
                            .output_tokens
                            .ok_or_else(|| usage("出力トークンの確定値がありません。"))?,
                    )?;
                }
            }
        } else if let Some(cost) = cost {
            let cost = u64::try_from(cost).map_err(|_| usage("費用台帳に負の金額があります。"))?;
            total.charged_micros = add(total.charged_micros, cost)?;
        } else {
            total.unpriced_entries = add(total.unpriced_entries, 1)?;
        }
    }
    Ok(total)
}

fn validate_identity(value: &str) -> Result<()> {
    if value.is_empty() || value.trim() != value || value.chars().any(char::is_control) {
        return Err(reservation(
            "費用予約の識別子・プロバイダ・モデルが不正です。",
        ));
    }
    Ok(())
}

fn validate_error_code(code: &str) -> Result<()> {
    if !code.starts_with("E-")
        || code.len() <= 2
        || !code
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'-')
    {
        return Err(usage(
            "失敗の分類には安定した E- エラーコードを指定してください。",
        ));
    }
    Ok(())
}

fn add(left: u64, right: u64) -> Result<u64> {
    left.checked_add(right)
        .ok_or_else(|| budget("費用またはトークン数が集計可能な上限を超えました。"))
}
fn money(value: u64) -> Result<i64> {
    i64::try_from(value).map_err(|_| budget("金額が DB に保存できる上限を超えています。"))
}
fn budget(message: &str) -> AppError {
    failure("E-AI-BUDGET", message, "チャンネルの日次予算・トークン上限・保留中の費用記録を確認してください。上限が不明なまま再送しないでください。")
}
fn usage(message: &str) -> AppError {
    failure("E-AI-USAGE", message, "送信先の利用実績を照合してください。送信成功が不明な要求を再送したり予約を解放したりしないでください。")
}
fn reservation(message: &str) -> AppError {
    failure("E-AI-RESERVATION", message, "元のチャンネルと送信識別子を照合してください。新しい識別子で不明な送信をやり直さないでください。")
}

#[cfg(test)]
#[path = "ai_cost_tests.rs"]
mod tests;
