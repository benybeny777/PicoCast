//! 構造化台本の生成・保存と、旧版記法の取り込み・書き出し。

pub mod compatibility;
pub mod document;
pub mod generation;
pub mod legacy;
pub mod prompt;
#[cfg(test)]
mod tests;

/// 台本組立と後続QAで共有する説明密度・話者役割の正本。
pub const DIALOGUE_RULES: &str = include_str!("dialogue_rules.txt");

use picocast_core::AppError;

pub(crate) fn invalid() -> AppError {
    tracing::error!(
        code = "E-SCRIPT-FORMAT",
        "台本の型・関連・旧版記法を検証できません"
    );
    AppError::new(
        "E-SCRIPT-FORMAT",
        "台本の形式または参照先が不正です。",
        "話者・シーン・必須項目・テンプレートの版を確認して、台本を修正してください。",
    )
}
