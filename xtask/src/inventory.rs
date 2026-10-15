use anyhow::{bail, Context, Result};
use std::collections::BTreeSet;
use std::path::Path;

pub fn check(root: &Path) -> Result<()> {
    let source = std::fs::read_to_string(root.join("docs/migration-inventory.md"))
        .context("移行棚卸し表を読めません")?;
    let expected = collect(root)?;
    validate(&source, &expected)?;
    println!("移行棚卸し: {} 件一致", expected.len());
    Ok(())
}

fn validate(source: &str, expected: &BTreeSet<String>) -> Result<()> {
    let mut documented = BTreeSet::new();
    for line in source.lines().filter(|line| line.starts_with("| `")) {
        let columns: Vec<_> = line.split('|').map(str::trim).collect();
        if columns.len() != 7 {
            bail!("棚卸し表の列数が不正です: {line}");
        }
        let id = columns[1].trim_matches('`').to_owned();
        if !documented.insert(id.clone()) {
            bail!("棚卸し表の識別子が重複しています: {id}");
        }
        if !matches!(columns[3], "移す" | "作り直す" | "やめる")
            || !columns[4].contains("WP-R")
            || columns[5].is_empty()
        {
            bail!("棚卸し表の判断・移行先が不正です: {id}");
        }
    }
    let missing: Vec<_> = expected.difference(&documented).collect();
    let stale: Vec<_> = documented.difference(expected).collect();
    if !missing.is_empty() || !stale.is_empty() {
        bail!("移行棚卸しの不一致。未記載: {missing:?}、削除済み: {stale:?}");
    }
    Ok(())
}

fn collect(root: &Path) -> Result<BTreeSet<String>> {
    let mut ids = BTreeSet::new();
    for path in crate::guards::files_under(&root.join("web_app/routes"))? {
        if path.extension().is_some_and(|extension| extension == "py") {
            let text = std::fs::read_to_string(&path)?;
            let relative = path
                .strip_prefix(root)?
                .to_string_lossy()
                .replace('\\', "/");
            for name in function_names(&text) {
                ids.insert(format!("route:{relative}#{name}"));
            }
        }
    }
    let config = std::fs::read_to_string(root.join("config/config.py"))?;
    for name in constant_names(&config) {
        ids.insert(format!("config:{name}"));
    }
    let spec = std::fs::read_to_string(root.join("SPEC.md"))?;
    let mut fence = false;
    let mut section = 0;
    for line in spec.lines() {
        if line.trim_start().starts_with("```") || line.trim_start().starts_with("~~~") {
            fence = !fence;
        }
        if !fence && line.starts_with('#') && line.trim_start_matches('#').starts_with(' ') {
            section += 1;
            ids.insert(format!("spec:{section:03}"));
        }
    }
    for path in crate::guards::files_under(&root.join("web_app/templates"))? {
        if path
            .extension()
            .is_some_and(|extension| extension == "html")
        {
            let relative = path
                .strip_prefix(root)?
                .to_string_lossy()
                .replace('\\', "/");
            ids.insert(format!("screen:{relative}"));
        }
    }
    // 実 DB は開かず、旧版のテーブル宣言だけをソースから読む。
    for path in crate::guards::files_under(&root.join("core"))? {
        if path.extension().is_some_and(|extension| extension == "py") {
            let source = std::fs::read_to_string(&path)?;
            let relative = path
                .strip_prefix(root)?
                .to_string_lossy()
                .replace('\\', "/");
            for line in source
                .lines()
                .filter(|line| !line.trim_start().starts_with('#'))
            {
                let words: Vec<_> = line.split_whitespace().collect();
                if let Some(position) = words.windows(2).position(|pair| {
                    pair[0].eq_ignore_ascii_case("CREATE") && pair[1].eq_ignore_ascii_case("TABLE")
                }) {
                    let mut index = position + 2;
                    if words
                        .get(index)
                        .is_some_and(|word| word.eq_ignore_ascii_case("IF"))
                    {
                        index += 3;
                    }
                    if let Some(name) = words.get(index) {
                        let name = name.trim_matches(['`', '"', '\'', '(']);
                        ids.insert(format!("db:{relative}#{name}"));
                    }
                }
            }
        }
    }
    Ok(ids)
}

fn function_names(source: &str) -> Vec<&str> {
    source
        .lines()
        .filter_map(|line| {
            let declaration = line
                .strip_prefix("def ")
                .or_else(|| line.strip_prefix("async def "))?;
            declaration.split('(').next()
        })
        .collect()
}

fn constant_names(source: &str) -> Vec<&str> {
    source
        .lines()
        .filter_map(|line| {
            let (left, _) = line.split_once('=')?;
            let name = left.split(':').next()?.trim_end();
            if !name.is_empty()
                && (name.as_bytes()[0].is_ascii_uppercase() || name.starts_with('_'))
                && name.bytes().any(|byte| byte.is_ascii_uppercase())
                && name
                    .bytes()
                    .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
            {
                Some(name)
            } else {
                None
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn declarations_exclude_nested_functions_and_expressions() {
        assert_eq!(
            function_names("def first():\n    def nested():\nasync def second():"),
            ["first", "second"]
        );
        assert_eq!(
            constant_names("VALUE = 1\nTYPED: int = 2\n    LOCAL = 3\n_lower = 4\nif VALUE == 1:"),
            ["VALUE", "TYPED"]
        );
    }

    #[test]
    fn inventory_rejects_omissions_stale_rows_and_duplicates() {
        let expected = BTreeSet::from(["config:VALUE".to_owned()]);
        let row = "| `config:VALUE` | 調整値 | 移す | WP-R1-3 | app_settings |\n";
        assert!(validate(row, &expected).is_ok());
        assert!(validate("", &expected).is_err());
        assert!(validate(&row.replace("VALUE", "OLD"), &expected).is_err());
        assert!(validate(&row.repeat(2), &expected).is_err());
        assert!(validate(&row.replace("移す", "未定"), &expected).is_err());
        assert!(validate(&row.replace("WP-R1-3", ""), &expected).is_err());
    }

    #[test]
    fn repository_inventory_matches_sources() -> Result<()> {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .context("親がありません")?;
        check(root)
    }
}
