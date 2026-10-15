use anyhow::{bail, Context, Result};
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::Path;
use std::process::Command;

pub fn check(root: &Path) -> Result<()> {
    run(root, None)
}

pub fn run(root: &Path, action: Option<&str>) -> Result<()> {
    validate_contract(root)?;
    #[cfg(windows)]
    let python = root.join(".venv/Scripts/python.exe");
    #[cfg(not(windows))]
    let python = root.join(".venv/bin/python");
    if !python.is_file() {
        bail!("旧版オラクル用の.venvがありません。READMEのuv環境を用意してください");
    }
    let mut command = Command::new(python);
    command.arg(root.join("tools/oracle.py"));
    match action {
        None | Some("check") => {}
        Some("record") => {
            command.arg("--emit-json");
        }
        Some(_) => bail!("使い方: cargo xtask oracle [check|record]"),
    }
    let status = command
        .env("PYTHONIOENCODING", "utf-8")
        .current_dir(root)
        .status()
        .context("旧版オラクルの起動に失敗しました")?;
    if !status.success() {
        bail!("旧版オラクルが失敗しました: {status}");
    }
    Ok(())
}

fn validate_contract(root: &Path) -> Result<()> {
    let mut case_sets = Vec::new();
    for directory in ["inputs", "expected"] {
        let path = root.join(format!("tests/oracle/{directory}/v1.json"));
        let document: Value = serde_json::from_str(&std::fs::read_to_string(&path)?)?;
        if document["contract_version"] != 1 {
            bail!("オラクル契約の版が不正です: {}", path.display());
        }
        let cases = document["cases"]
            .as_array()
            .context("casesが配列ではありません")?;
        let mut ids = BTreeSet::new();
        let mut identifiers = BTreeSet::new();
        let mut kinds = BTreeSet::new();
        for case in cases {
            let id = case["id"].as_str().context("ケースのidがありません")?;
            let kind = case["kind"].as_str().context("ケースのkindがありません")?;
            if id.is_empty() || !identifiers.insert(id) {
                bail!("オラクルの空識別子または重複があります: {id}");
            }
            ids.insert((id.to_owned(), kind.to_owned()));
            let payload = if directory == "inputs" {
                "input"
            } else {
                "output"
            };
            if case.get(payload).is_none() {
                bail!("オラクルの{payload}がありません: {id}");
            }
            kinds.insert(kind);
        }
        if kinds
            != BTreeSet::from([
                "reading",
                "script",
                "metadata",
                "schedule",
                "score",
                "expansion",
            ])
        {
            bail!("オラクルの対象分野に不足・未知の種別があります: {kinds:?}");
        }
        case_sets.push(ids);
    }
    if case_sets[0] != case_sets[1] {
        bail!("オラクル入力と期待値のケース識別子が一致しません");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn oracle_contract_has_all_six_domains() -> Result<()> {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .context("親がありません")?;
        validate_contract(root)
    }
}
