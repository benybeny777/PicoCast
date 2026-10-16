use crate::{content_hash, failure, valid_hash};
use picocast_core::{clock::Timestamp, ChannelId, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetrySafety {
    Repeatable,
    Reconcile,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CachePolicy {
    ContentAddressed,
    Never,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Node {
    pub id: String,
    pub step: String,
    pub version: u32,
    pub source_sha256: String,
    pub input: Value,
    pub asset_hashes: BTreeSet<String>,
    pub model_id: Option<String>,
    pub settings: Value,
    pub dependencies: Vec<String>,
    pub uses_gpu: bool,
    pub retry_safety: RetrySafety,
    pub cache_policy: CachePolicy,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dag {
    pub nodes: Vec<Node>,
}
impl Dag {
    pub fn ordered(&self) -> Result<Vec<&Node>> {
        if self.nodes.is_empty() {
            return Err(failure("E-PIPELINE-DAG"));
        }
        let mut ids = BTreeSet::new();
        for node in &self.nodes {
            if node.id.is_empty()
                || node.id.trim() != node.id
                || node.id.chars().any(char::is_control)
                || node.id.starts_with('$')
                || node.step.is_empty()
                || node.step.trim() != node.step
                || node.step.chars().any(char::is_control)
                || node.version == 0
                || !valid_hash(&node.source_sha256)
                || node.asset_hashes.iter().any(|hash| !valid_hash(hash))
                || !ids.insert(&node.id)
            {
                return Err(failure("E-PIPELINE-DAG"));
            }
        }
        for node in &self.nodes {
            let deps = node.dependencies.iter().collect::<BTreeSet<_>>();
            if deps.len() != node.dependencies.len()
                || deps
                    .iter()
                    .any(|id| !ids.contains(id) || id.as_str() == node.id)
            {
                return Err(failure("E-PIPELINE-DAG"));
            }
        }
        let mut result = Vec::new();
        let mut visited = BTreeSet::new();
        while result.len() < self.nodes.len() {
            let previous = result.len();
            for node in &self.nodes {
                if !visited.contains(&node.id)
                    && node.dependencies.iter().all(|id| visited.contains(id))
                {
                    visited.insert(node.id.clone());
                    result.push(node);
                }
            }
            if result.len() == previous {
                return Err(failure("E-PIPELINE-DAG"));
            }
        }
        Ok(result)
    }
    pub fn invalidated(&self, changed: &BTreeSet<String>) -> Result<BTreeSet<String>> {
        let mut result = changed.clone();
        let ordered = self.ordered()?;
        if changed
            .iter()
            .any(|id| !ordered.iter().any(|node| &node.id == id))
        {
            return Err(failure("E-PIPELINE-DAG"));
        }
        for node in ordered {
            if node.dependencies.iter().any(|id| result.contains(id)) {
                result.insert(node.id.clone());
            }
        }
        Ok(result)
    }
}
impl Node {
    pub fn cache_key(
        &self,
        channel: &ChannelId,
        dependencies: &BTreeMap<String, CacheEnvelope>,
    ) -> Result<String> {
        let mut inputs = BTreeMap::new();
        for id in &self.dependencies {
            let output = dependencies
                .get(id)
                .ok_or_else(|| failure("E-PIPELINE-DAG"))?;
            output.validate(channel)?;
            inputs.insert(id, (&output.provenance.inputs_hash, &output.output_sha256));
        }
        content_hash(
            &serde_json::json!({"channel":channel.as_str(),"name":self.step,"version":self.version,"source":self.source_sha256,"input":self.input,"assets":self.asset_hashes,"model":self.model_id,"settings":self.settings,"dependencies":inputs}),
        )
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Provenance {
    pub step: String,
    pub version: u32,
    pub source_sha256: String,
    pub inputs_hash: String,
    pub model_id: Option<String>,
    pub settings_sha256: String,
    pub dependency_hashes: BTreeMap<String, String>,
    pub asset_hashes: BTreeSet<String>,
    pub at: Timestamp,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CacheEnvelope {
    pub channel_id: ChannelId,
    pub output_sha256: String,
    pub output: Value,
    pub provenance: Provenance,
}
impl CacheEnvelope {
    pub fn validate(&self, channel: &ChannelId) -> Result<()> {
        if &self.channel_id != channel
            || !valid_hash(&self.provenance.inputs_hash)
            || self.output_sha256 != content_hash(&self.output)?
        {
            return Err(failure("E-PIPELINE-CACHE"));
        }
        Ok(())
    }
}
