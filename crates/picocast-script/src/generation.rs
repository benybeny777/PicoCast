//! 共通Gatewayの検証・再試行とDB版テンプレートを結ぶ。
use crate::{
    document::{self, Limits, SaveContext, StructuredScript},
    invalid,
    prompt::{self, Kind, PromptContext},
};
use picocast_ai::{Cancellation, Gateway, GenerateRequest, Generation, Stage};
use picocast_core::{ChannelId, Result};
use picocast_store::Store;

pub struct RequestContext {
    pub request_id: String,
    pub job_id: Option<String>,
    pub settings_hash: String,
    pub topic: String,
    pub save: SaveContext,
}

pub async fn generate_and_save(
    gateway: &mut Gateway,
    store: &mut Store,
    channel: &ChannelId,
    prompt_context: &PromptContext<'_>,
    limits: &Limits,
    request: RequestContext,
    cancel: &mut Cancellation,
) -> Result<Generation<StructuredScript>> {
    let mut save = request.save;
    if request.topic.trim().is_empty() {
        return Err(invalid());
    }
    let prepared = prompt::build(store, channel, Kind::Script, prompt_context)?;
    let schema = document::schema(&prepared.speakers, limits)?;
    save.template = prepared.template.clone();
    let project_id =
        document::validate_save_context(store, channel, &save)?.map(|project| project.id);
    let generation=gateway.generate_json_checked(store,GenerateRequest {channel_id:channel.clone(),request_id:request.request_id,
        project_id,job_id:request.job_id,stage:Stage::Script,
        prompt:format!("{}\n\n生成テーマ（次のJSON文字列の内容）:\n{}\n出力は指定されたJSON schemaだけに従うこと。",prepared.text,serde_json::to_string(&request.topic).map_err(|_|invalid())?),
        template_version:prepared.template.version,settings_hash:request.settings_hash},&schema,cancel,
        |script:&StructuredScript|script.validate(channel,&prepared.speakers,limits)).await?;
    cancel.check()?;
    save.template = prepared.template;
    save.author = "ai".into();
    save.provenance = serde_json::to_value(&generation.provenance).map_err(|_| invalid())?;
    document::save(
        store,
        channel,
        &generation.value,
        &prepared.speakers,
        limits,
        &save,
    )?;
    Ok(generation)
}
