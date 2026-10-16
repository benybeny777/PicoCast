use anyhow::{bail, Context, Result};
use std::{path::Path, process::Command};

/// HEADからのステージ済み・未ステージ変更をまとめて確認する。警告は終了コードに影響しない。
pub fn check(root: &Path) -> Result<()> {
    let output = Command::new("git")
        .args([
            "diff",
            "--name-status",
            "--no-renames",
            "-z",
            "HEAD",
            "--",
            "*.rs",
        ])
        .current_dir(root)
        .output()
        .context("工程版のGit差分を取得できません")?;
    if !output.status.success() {
        bail!("工程版のGit差分取得に失敗しました");
    }
    let entries = std::str::from_utf8(&output.stdout)
        .context("工程版のGitパスがUTF-8ではありません")?
        .split('\0')
        .filter(|entry| !entry.is_empty())
        .collect::<Vec<_>>();
    if entries.len() % 2 != 0 {
        bail!("工程版のGit差分形式が不正です");
    }
    let mut count = 0;
    for pair in entries.chunks_exact(2) {
        let [status, path] = [pair[0], pair[1]];
        // 追加・削除には比較可能な実装の組がない。renameは上記指定で追加・削除に分かれる。
        if status != "M" {
            continue;
        }
        let old = Command::new("git")
            .args(["show", &format!("HEAD:{path}")])
            .current_dir(root)
            .output()
            .context("変更前の工程ソースを取得できません")?;
        if !old.status.success() {
            bail!("変更前の工程ソース取得に失敗しました: {path}");
        }
        let before =
            std::str::from_utf8(&old.stdout).context("変更前の工程ソースがUTF-8ではありません")?;
        let after = std::fs::read_to_string(root.join(path))
            .with_context(|| format!("工程ソースを読めません: {path}"))?;
        for warning in unchanged_versions(path, Some(before), &after)? {
            eprintln!("警告: {path}: {warning} の本番ソースが変わりましたがVERSIONは同じです。変更内容に応じて版を確認してください。");
            count += 1;
        }
    }
    println!("工程版の差分検査: {count}件の警告");
    Ok(())
}

fn unchanged_versions(path: &str, before: Option<&str>, after: &str) -> Result<Vec<String>> {
    let Some(before) = before else {
        return Ok(Vec::new());
    };
    let old = crate::guards::production_step_sources(path, before)?;
    let new = crate::guards::production_step_sources(path, after)?;
    Ok(new
        .versions
        .into_iter()
        .filter_map(|(identity, (version, implementation))| {
            old.versions
                .get(&identity)
                .and_then(|(old_version, old_implementation)| {
                    (old_version == &version
                        && (old.source != new.source || old_implementation != &implementation))
                        .then(|| format!("{identity} (VERSION={version})"))
                })
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::unchanged_versions;

    const SOURCE: &str = r#"
        use picocast_pipeline as pipeline;
        use pipeline::Step as Workflow;
        struct Render;
        impl Workflow for Render {
            const NAME: &'static str = "render";
            const VERSION: u32 = 1;
            fn run(&self) { work(1); }
        }
        #[cfg(test)] mod tests { #[test] fn fixture() { assert!(true); } }
    "#;

    #[test]
    fn warns_for_changed_implementation_with_same_version_and_alias_import() {
        let changed = SOURCE.replace("work(1)", "work(2)");
        assert_eq!(
            unchanged_versions("src/render.rs", Some(SOURCE), &changed)
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn accepts_changed_version_and_new_implementation_without_old_blob() {
        let changed = SOURCE
            .replace("work(1)", "work(2)")
            .replace("u32 = 1", "u32 = 2");
        assert!(unchanged_versions("src/render.rs", Some(SOURCE), &changed)
            .unwrap()
            .is_empty());
        assert!(unchanged_versions("src/new.rs", None, SOURCE)
            .unwrap()
            .is_empty());
        assert!(unchanged_versions("src/new.rs", Some(""), SOURCE)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn ignores_test_only_changes_and_test_files() {
        let changed = SOURCE.replace("assert!(true)", "assert_eq!(1, 2)");
        assert!(unchanged_versions("src/render.rs", Some(SOURCE), &changed)
            .unwrap()
            .is_empty());
        let changed = SOURCE.replace("work(1)", "work(2)");
        assert!(
            unchanged_versions("tests/render.rs", Some(SOURCE), &changed)
                .unwrap()
                .is_empty()
        );
        assert!(unchanged_versions(
            "src/tests.rs",
            Some(&format!("#![cfg(test)]{SOURCE}")),
            &format!("#![cfg(test)]{changed}")
        )
        .unwrap()
        .is_empty());
    }

    #[test]
    fn tracks_nested_module_alias_scope_and_ignores_test_impl() {
        let source = format!("mod child {{ {SOURCE} }} #[cfg(test)] impl picocast_pipeline::Step for TestOnly {{ const NAME: &str = \"test\"; const VERSION: u32 = 1; }}");
        assert_eq!(
            unchanged_versions(
                "src/render.rs",
                Some(&source),
                &source.replace("work(1)", "work(2)")
            )
            .unwrap()
            .len(),
            1
        );
        assert!(unchanged_versions(
            "src/render.rs",
            Some(&source),
            &source.replace("VERSION: u32 = 1; }", "VERSION: u32 = 2; }")
        )
        .unwrap()
        .is_empty());
    }

    #[test]
    fn other_step_version_or_new_impl_does_not_warn_unchanged_impl() {
        let additional = r#"impl picocast_pipeline::Step for Other {
            const NAME: &'static str = "other"; const VERSION: u32 = 7;
            fn run(&self) { work(3); }
        }"#;
        let before = format!("{SOURCE}{additional}");
        let after = before
            .replace("u32 = 7", "u32 = 8")
            .replace("work(3)", "work(4)");
        assert!(unchanged_versions("src/render.rs", Some(&before), &after)
            .unwrap()
            .is_empty());
        assert!(unchanged_versions("src/render.rs", Some(SOURCE), &before)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn shared_helper_change_warns_and_test_method_change_does_not() {
        let before = format!("{SOURCE} fn work(value:u32) {{ let _ = value + 1; }}");
        assert_eq!(
            unchanged_versions(
                "src/render.rs",
                Some(&before),
                &before.replace("value + 1", "value + 2")
            )
            .unwrap()
            .len(),
            1
        );
        let before = SOURCE.replace(
            "fn run(&self)",
            "#[cfg(test)] fn fixture() { work(10); } fn run(&self)",
        );
        assert!(unchanged_versions(
            "src/render.rs",
            Some(&before),
            &before.replace("work(10)", "work(20)")
        )
        .unwrap()
        .is_empty());
    }
}
