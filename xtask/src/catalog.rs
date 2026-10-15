use anyhow::{bail, Context, Result};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

pub fn check(root: &Path) -> Result<()> {
    let definitions: Vec<Value> = serde_json::from_str(&std::fs::read_to_string(
        root.join("crates/picocast-core/src/error_catalog.json"),
    )?)?;
    let labels: BTreeMap<String, String> =
        serde_json::from_str(&std::fs::read_to_string(root.join("ui/i18n/ja.json"))?)?;
    let legacy = legacy_definitions(&std::fs::read_to_string(root.join("core/error_codes.py"))?)?;
    let mut codes = BTreeSet::new();
    let mut keys = BTreeSet::new();
    let mut rust_codes = BTreeSet::new();
    for path in crate::guards::files_under(&root.join("crates"))? {
        if path.extension().is_some_and(|extension| extension == "rs")
            && !path
                .components()
                .any(|component| component.as_os_str() == "tests")
        {
            rust_codes.extend(
                crate::guards::production_string_literals(&std::fs::read_to_string(&path)?)?
                    .into_iter()
                    .filter(|value| is_error_code(value)),
            );
        }
    }
    for definition in &definitions {
        let code = field(definition, "code")?;
        if !code.starts_with("E-") || !codes.insert(code.to_string()) {
            bail!("エラーコードが不正または重複しています: {code}");
        }
        for suffix in ["message", "fix"] {
            let key = field(definition, &format!("{suffix}_key"))?;
            if key != format!("errors.{code}.{suffix}")
                || labels.get(key).is_none_or(|text| text.trim().is_empty())
            {
                bail!("エラーの文言または対処手順が不正です: {code} / {key}");
            }
            keys.insert(key.to_owned());
        }
        if let Some(previous) = legacy.get(code) {
            if definition["category"] != previous["category"]
                || definition["retry_recommended"] != previous["retry_recommended"]
                || labels[field(definition, "message_key")?] != previous["message"]
                || labels[field(definition, "fix_key")?] != previous["remediation"]
            {
                bail!("旧版のエラーの意味または対処手順が変わっています: {code}");
            }
        } else if !rust_codes.contains(code) {
            bail!("未使用のRustエラーコードです: {code}");
        }
    }
    check_rust_codes(&codes, &rust_codes)?;
    for code in legacy.keys() {
        if !codes.contains(code) {
            bail!("旧版エラーコードの移植が欠けています: {code}");
        }
    }
    for key in labels.keys().filter(|key| key.starts_with("errors.")) {
        if !keys.contains(key) {
            bail!("未使用のエラー文言キーです: {key}");
        }
    }
    println!(
        "エラーカタログ: {}件（旧版互換{}件）のコード・意味・対処・使用元を確認",
        codes.len(),
        legacy.len()
    );
    Ok(())
}

fn is_error_code(value: &str) -> bool {
    value.starts_with("E-")
        && value.len() > 2
        && value
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'-')
}

fn check_rust_codes(definitions: &BTreeSet<String>, used: &BTreeSet<String>) -> Result<()> {
    if let Some(code) = used.difference(definitions).next() {
        bail!("本番Rustのエラーコードがカタログにありません: {code}");
    }
    Ok(())
}

fn field<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    value[name]
        .as_str()
        .with_context(|| format!("カタログに文字列の {name} がありません"))
}

// 旧版を実行せず、カタログ内の文字列・真偽値だけを読む。構文が変われば停止する。
fn legacy_definitions(source: &str) -> Result<BTreeMap<String, Value>> {
    let body = source
        .split_once("ERROR_CATALOG: dict[str, ErrorDef] = {")
        .context("旧版カタログの定義がありません")?
        .1
        .split_once("\n}")
        .context("旧版カタログの終端がありません")?
        .0;
    let mut output = BTreeMap::new();
    let mut rest = body;
    while let Some((prefix, arguments)) = rest.split_once("ErrorDef(") {
        let dictionary_key = prefix
            .rsplit_once(':')
            .context("旧版カタログのキーがありません")?
            .0
            .lines()
            .last()
            .context("旧版カタログのキー行がありません")?
            .trim();
        let dictionary_key = syn::parse_str::<syn::LitStr>(dictionary_key)?.value();
        let mut quoted = false;
        let mut escaped = false;
        let end = arguments
            .char_indices()
            .find_map(|(index, character)| {
                if escaped {
                    escaped = false;
                    return None;
                }
                if quoted && character == '\\' {
                    escaped = true;
                    return None;
                }
                if character == '"' {
                    quoted = !quoted;
                }
                (!quoted && character == ')').then_some(index)
            })
            .context("旧版エラー定義を解析できません")?;
        let call: syn::ExprCall = syn::parse_str(&format!("ErrorDef({})", &arguments[..end]))?;
        let values = call
            .args
            .iter()
            .map(|argument| match argument {
                syn::Expr::Lit(literal) => match &literal.lit {
                    syn::Lit::Str(value) => Ok(Value::String(value.value())),
                    _ => bail!("旧版エラー定義に未対応のリテラルがあります"),
                },
                syn::Expr::Path(path) if path.path.is_ident("True") => Ok(Value::Bool(true)),
                syn::Expr::Path(path) if path.path.is_ident("False") => Ok(Value::Bool(false)),
                _ => bail!("旧版エラー定義に未対応の式があります"),
            })
            .collect::<Result<Vec<_>>>()?;
        if values.len() != 5 {
            bail!("旧版エラー定義の引数が5件ではありません");
        }
        let entry = serde_json::json!({"code":values[0], "message":values[1], "category":values[2], "retry_recommended":values[3], "remediation":values[4]});
        let code = field(&entry, "code")?.to_owned();
        if dictionary_key != code {
            bail!("旧版カタログのキーとコードが一致しません: {dictionary_key} / {code}");
        }
        if output.insert(code.clone(), entry).is_some() {
            bail!("旧版エラーコードが重複しています: {code}");
        }
        rest = &arguments[end + 1..];
    }
    if output.is_empty() {
        bail!("旧版カタログが空です");
    }
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn production_codes_include_macros_but_exclude_test_boundaries() -> Result<()> {
        let source = r#"
fn production() {
    let code = "E-PRODUCTION";
    tracing::error!(code = "E-MACRO", nested(["E-NESTED"]));
    let sentence = "対象は E-SENTENCE です";
}
#[cfg(test)] mod tests { fn fixture() { let code = "E-UNKNOWN-TEST"; } }
#[test] fn unit() { let code = "E-UNIT-ONLY"; }
struct Example;
impl Example { #[cfg(test)] fn fixture() { let code = "E-METHOD-ONLY"; } }
#[cfg(test)] const TEST_CODE: &str = "E-CONST-ONLY";
#[cfg(test)] impl Example { fn test_impl() { let code = "E-IMPL-ONLY"; } }
"#;
        let found = crate::guards::production_string_literals(source)?
            .into_iter()
            .filter(|value| is_error_code(value))
            .collect::<BTreeSet<_>>();
        assert_eq!(
            found,
            BTreeSet::from([
                "E-PRODUCTION".to_owned(),
                "E-MACRO".to_owned(),
                "E-NESTED".to_owned()
            ])
        );
        let mut definitions = found.clone();
        assert!(check_rust_codes(&definitions, &found).is_ok());
        definitions.remove("E-MACRO");
        assert!(check_rust_codes(&definitions, &found).is_err());
        Ok(())
    }

    #[test]
    fn parses_parentheses_and_escaped_quotes_without_running_python() -> Result<()> {
        let source = "ERROR_CATALOG: dict[str, ErrorDef] = {\n\"E-A\": ErrorDef(\"E-A\", \"失敗（対象）)\\\"\", \"config\", False, \"確認してください\"),\n}";
        let entries = legacy_definitions(source)?;
        assert_eq!(entries.len(), 1);
        assert_eq!(entries["E-A"]["retry_recommended"], false);
        assert_eq!(entries["E-A"]["message"], "失敗（対象）)\"");
        Ok(())
    }

    #[test]
    fn mismatched_legacy_key_is_rejected() {
        assert!(legacy_definitions("ERROR_CATALOG: dict[str, ErrorDef] = {\n\"E-A\": ErrorDef(\"E-B\", \"説明\", \"config\", False, \"対処\"),\n}").is_err());
    }
}
