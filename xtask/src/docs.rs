use anyhow::{bail, Context, Result};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

pub fn check(root: &Path) -> Result<()> {
    let plan = std::fs::read_to_string(root.join("DESIGN_implementation_plan.md"))?;
    check_plan_references(root, &plan)?;
    let known: BTreeSet<String> = plan
        .lines()
        .filter_map(|line| {
            let cell = line.strip_prefix('|')?.split('|').next()?.trim();
            (cell.starts_with("WP-R") || cell.starts_with('N')).then(|| cell.to_owned())
        })
        .collect();
    let mut documents = std::fs::read_dir(root)?
        .map(|entry| entry.map(|entry| entry.path()))
        .collect::<std::io::Result<Vec<_>>>()?;
    documents.retain(|path| {
        path.file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| {
                (name.starts_with("DESIGN_") && name.ends_with(".md")) || name == "HANDOFF.md"
            })
    });
    for path in &documents {
        let source = std::fs::read_to_string(path)?;
        check_links(path, &source)?;
        for id in identifiers(&source)
            .into_iter()
            .filter(|id| id.starts_with("WP-R") || id.starts_with('N'))
        {
            if !known.contains(&id) {
                bail!("実装計画に無いID参照です: {} / {id}", path.display());
            }
        }
    }
    let handoff = std::fs::read_to_string(root.join("HANDOFF.md"))?;
    for line in handoff.lines().filter(|line| line.starts_with('|')) {
        let cells: Vec<_> = line.split('|').map(str::trim).collect();
        if cells.get(1).is_some_and(|cell| cell.starts_with("WP-R"))
            && cells
                .iter()
                .skip(2)
                .any(|cell| matches!(*cell, "完了" | "完了済み" | "実装済み"))
        {
            bail!("HANDOFFに完了済みのWP行が残っています: {line}");
        }
    }
    println!(
        "文書点検: {}冊のローカルリンク・WP/N参照・引き継ぎ完了行を確認",
        documents.len()
    );
    Ok(())
}

fn check_plan_references(root: &Path, plan: &str) -> Result<()> {
    let sources = [
        ("DESIGN_product_v2.md", vec!["T"]),
        ("DESIGN_foundations.md", vec!["G"]),
        ("DESIGN_quality.md", vec!["Q", "QR", "C"]),
        (
            "DESIGN_backlog.md",
            vec!["S", "V", "P", "Y", "D", "O", "U", "E", "K"],
        ),
    ];
    for (file, prefixes) in sources {
        let source = std::fs::read_to_string(root.join(file))?;
        let known = identifiers(&source);
        for id in identifiers(plan) {
            let prefix = id.trim_end_matches(|character: char| character.is_ascii_digit());
            if prefixes.contains(&prefix) {
                let source_id = id
                    .strip_prefix("QR")
                    .map_or_else(|| id.clone(), |number| format!("R{number}"));
                if !known.contains(&source_id) {
                    bail!("実装計画のIDに正本の参照先がありません: {id} / {file}");
                }
            }
        }
    }
    Ok(())
}

fn identifiers(source: &str) -> BTreeSet<String> {
    source
        .split(|character: char| !character.is_ascii_alphanumeric() && character != '-')
        .filter(|token| {
            let number = token
                .strip_prefix("WP-R")
                .filter(|number| number.contains('-'))
                .or_else(|| {
                    let prefix =
                        token.trim_end_matches(|character: char| character.is_ascii_digit());
                    [
                        "N", "T", "G", "Q", "QR", "R", "C", "S", "V", "P", "Y", "D", "O", "U", "E",
                        "K",
                    ]
                    .contains(&prefix)
                    .then(|| &token[prefix.len()..])
                });
            number.is_some_and(|number| {
                !number.is_empty()
                    && number
                        .chars()
                        .all(|character| character.is_ascii_digit() || character == '-')
                    && number.chars().any(|character| character.is_ascii_digit())
            })
        })
        .map(str::to_owned)
        .collect()
}

fn check_links(document: &Path, source: &str) -> Result<()> {
    let mut in_fence = false;
    for line in source.lines() {
        if line.trim_start().starts_with("```") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        let mut rest = line;
        while let Some((_, after)) = rest.split_once("](") {
            let (target, remaining) = after
                .split_once(')')
                .context("Markdownリンクの終端がありません")?;
            rest = remaining;
            let target = target
                .split_whitespace()
                .next()
                .unwrap_or_default()
                .trim_matches(['<', '>']);
            if target.is_empty() || target.contains("://") || target.starts_with("mailto:") {
                continue;
            }
            let (file, anchor) = target
                .split_once('#')
                .map_or((target, None), |(file, anchor)| (file, Some(anchor)));
            let parent = document.parent().context("文書の親がありません")?;
            let resolved: PathBuf = if file.is_empty() {
                document.to_owned()
            } else {
                parent.join(file)
            };
            if !resolved.exists() {
                bail!("リンク切れ: {} -> {target}", document.display());
            }
            if let Some(anchor) = anchor.filter(|anchor| !anchor.is_empty()) {
                if resolved
                    .extension()
                    .is_some_and(|extension| extension == "md")
                {
                    let destination = std::fs::read_to_string(&resolved)?;
                    if !heading_anchors(&destination).contains(anchor) {
                        bail!("見出しのリンク切れ: {} -> {target}", document.display());
                    }
                }
            }
        }
    }
    Ok(())
}

fn heading_anchors(source: &str) -> BTreeSet<String> {
    let mut anchors = BTreeSet::new();
    let mut in_fence = false;
    for line in source.lines() {
        if line.trim_start().starts_with("```") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence || !line.starts_with('#') {
            continue;
        }
        let heading = line.trim_start_matches('#').trim();
        let slug: String = heading
            .to_lowercase()
            .chars()
            .filter_map(|character| {
                if character.is_whitespace() {
                    Some('-')
                } else if character.is_alphanumeric() || character == '-' || character == '_' {
                    Some(character)
                } else {
                    None
                }
            })
            .collect();
        let mut unique = slug.clone();
        let mut count = 0;
        while anchors.contains(&unique) {
            count += 1;
            unique = format!("{slug}-{count}");
        }
        anchors.insert(unique);
    }
    anchors
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identifiers_ignore_words_and_preserve_wp_ids() {
        assert_eq!(
            identifiers("`WP-R0-5`、N4、Nano、Node、N"),
            BTreeSet::from(["N4".to_owned(), "WP-R0-5".to_owned()])
        );
    }

    #[test]
    fn broken_local_link_is_rejected() {
        assert!(check_links(Path::new("example.md"), "[参照](missing-doc-987654.md)").is_err());
        assert!(check_links(Path::new("example.md"), "[参照](https://example.com/)").is_ok());
    }

    #[test]
    fn heading_anchors_handle_japanese_and_duplicate_headings() {
        assert_eq!(
            heading_anchors("## 5. 作業パッケージ（WP）\n## 5. 作業パッケージ（WP）"),
            BTreeSet::from([
                "5-作業パッケージwp".to_owned(),
                "5-作業パッケージwp-1".to_owned()
            ])
        );
    }
}
