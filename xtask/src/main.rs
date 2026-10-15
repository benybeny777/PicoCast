// 製品の本番コードとは別に、開発用検証ランナーだけが検証コマンドと結果表示を所有する。
#![allow(clippy::disallowed_types, clippy::disallowed_macros)]

mod catalog;
mod docs;
mod guards;
mod inventory;

use anyhow::{bail, Context, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() -> Result<()> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .context("ワークスペースの親がありません")?
        .to_path_buf();
    match std::env::args().nth(1).as_deref() {
        Some("verify") => verify(&root),
        Some("guard") => guards::check(&root),
        Some("inventory") => inventory::check(&root),
        Some("catalog-check") => catalog::check(&root),
        Some("docs-check") => docs::check(&root),
        _ => bail!("使い方: cargo xtask verify | guard | inventory | catalog-check | docs-check"),
    }
}

fn verify(root: &Path) -> Result<()> {
    let mut results = Vec::new();
    // 個別の失敗でも残りを続け、最後に全結果と終了コードを返す。
    for (label, args) in [
        ("整形", vec!["fmt", "--all", "--check"]),
        (
            "clippy",
            vec![
                "clippy",
                "--locked",
                "--workspace",
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ],
        ),
        (
            "単体テスト",
            vec!["test", "--locked", "--workspace", "--all-targets"],
        ),
    ] {
        results.push((label, run(root, "cargo", &args)));
    }
    results.push(("走査ガード", guards::check(root)));
    results.push(("移行棚卸し", inventory::check(root)));
    results.push(("エラーカタログ", catalog::check(root)));
    results.push(("文書リンク", docs::check(root)));
    let js = guards::files_under(&root.join("ui")).map(|files| {
        files
            .into_iter()
            .filter(|p| {
                p.extension()
                    .is_some_and(|e| e == "js" || e == "mjs" || e == "cjs")
            })
            .collect::<Vec<_>>()
    });
    match js {
        Err(error) => results.push(("JS テスト探索", Err(error))),
        Ok(files) if files.is_empty() => println!("JS テスト: スキップ（ui に JS がありません）"),
        Ok(files) => {
            let tests: Vec<_> = files
                .iter()
                .filter(|p| {
                    let name = p.file_name().and_then(|n| n.to_str()).unwrap_or_default();
                    name.contains(".test.")
                        || name.contains(".spec.")
                        || p.components().any(|c| c.as_os_str() == "tests")
                })
                .collect();
            if tests.is_empty() {
                results.push((
                    "JS テスト",
                    Err(anyhow::anyhow!(
                        "ui に JS が存在しますが Node テストがありません"
                    )),
                ));
            } else {
                let paths: Vec<_> = tests
                    .iter()
                    .map(|p| p.to_string_lossy().into_owned())
                    .collect();
                let mut args = vec!["--test"];
                args.extend(paths.iter().map(String::as_str));
                results.push(("JS テスト", run(root, "node", &args)));
            }
        }
    }
    let mut failed = false;
    for (label, result) in results {
        match result {
            Ok(()) => println!("[成功] {label}"),
            Err(error) => {
                failed = true;
                eprintln!("[失敗] {label}: {error:#}");
            }
        }
    }
    if failed {
        bail!("検証に失敗しました。上の一覧を確認してください");
    }
    Ok(())
}

fn run(root: &Path, program: &str, args: &[&str]) -> Result<()> {
    let status = Command::new(program)
        .args(args)
        .current_dir(root)
        .status()
        .with_context(|| format!("{program} の起動に失敗しました"))?;
    if !status.success() {
        bail!("{program} {}: 終了コード {status}", args.join(" "));
    }
    Ok(())
}
