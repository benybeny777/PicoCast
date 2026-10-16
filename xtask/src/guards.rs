use anyhow::{bail, Context, Result};
use quote::ToTokens;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use syn::visit::{self, Visit};
use syn::{Attribute, Item, UseTree};

pub fn files_under(root: &Path) -> Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    if !root.exists() {
        return Ok(files);
    }
    let mut pending = vec![root.to_path_buf()];
    while let Some(dir) = pending.pop() {
        for entry in std::fs::read_dir(&dir)
            .with_context(|| format!("{} を列挙できません", dir.display()))?
        {
            let entry = entry?;
            let ty = entry.file_type()?;
            if ty.is_symlink() {
                bail!(
                    "走査対象にシンボリックリンクがあります: {}",
                    entry.path().display()
                );
            }
            if ty.is_dir() {
                if entry.file_name() != "target" && entry.file_name() != "node_modules" {
                    pending.push(entry.path());
                }
            } else if ty.is_file() {
                files.push(entry.path());
            }
        }
    }
    files.sort();
    Ok(files)
}

pub fn check(root: &Path) -> Result<()> {
    let mut violations = Vec::new();
    // 新 Rust 版だけを対象とし、Python と legacy は探索しない。
    for base in ["crates", "src-tauri", "ui"] {
        for file in files_under(&root.join(base))? {
            let relative = file
                .strip_prefix(root)?
                .to_string_lossy()
                .replace('\\', "/");
            let extension = file
                .extension()
                .and_then(|s| s.to_str())
                .unwrap_or_default();
            if extension != "rs" && extension != "js" && extension != "mjs" && extension != "cjs" {
                continue;
            }
            let source = std::fs::read_to_string(&file)
                .with_context(|| format!("{relative} を読めません"))?;
            if extension == "rs" {
                match scan_rust(&relative, &source) {
                    Ok(found) => {
                        violations.extend(found.into_iter().map(|v| format!("{relative}: {v}")))
                    }
                    Err(error) => violations.push(format!("{relative}: 構文解析失敗: {error}")),
                }
            } else {
                violations.extend(
                    scan_js(&relative, &source)
                        .into_iter()
                        .map(|v| format!("{relative}: {v}")),
                );
            }
        }
    }
    if !violations.is_empty() {
        bail!("共通基盤ガード違反:\n{}", violations.join("\n"));
    }
    Ok(())
}

fn owner(path: &str, module: &str) -> bool {
    let prefix = format!("crates/picocast-core/src/{module}");
    path == format!("{prefix}.rs") || path.starts_with(&format!("{prefix}/"))
}

fn test_attrs(attrs: &[Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path().is_ident("test") || matches!(&attr.meta, syn::Meta::List(list) if list.path.is_ident("cfg") && list.tokens.to_string() == "test")
    })
}

pub(crate) struct ProductionSteps {
    pub source: String,
    pub versions: BTreeMap<String, (String, String)>,
}

/// Step検査も禁止API検査と同じimport解決・テスト境界を使用する。
pub(crate) fn production_step_sources(path: &str, source: &str) -> Result<ProductionSteps> {
    fn retain_production(items: &mut Vec<Item>) {
        items.retain(|item| !test_attrs(item_attrs(item)));
        for item in items {
            match item {
                Item::Mod(module) => {
                    if let Some((_, items)) = &mut module.content {
                        retain_production(items);
                    }
                }
                Item::Impl(implementation) => implementation.items.retain(|item| {
                    let attrs = match item {
                        syn::ImplItem::Const(item) => &item.attrs,
                        syn::ImplItem::Fn(item) => &item.attrs,
                        syn::ImplItem::Type(item) => &item.attrs,
                        syn::ImplItem::Macro(item) => &item.attrs,
                        _ => return true,
                    };
                    !test_attrs(attrs)
                }),
                _ => {}
            }
        }
    }
    fn collect(
        items: &[Item],
        scope: &str,
        resolver: &mut Scanner<'_>,
        versions: &mut BTreeMap<String, (String, String)>,
    ) -> Result<String> {
        let saved = resolver.aliases.clone();
        resolver.imports(items);
        let mut context = String::new();
        for item in items {
            match item {
                Item::Mod(module) => {
                    if let Some((_, items)) = &module.content {
                        let mut shell = module.clone();
                        shell.content = Some((syn::token::Brace::default(), Vec::new()));
                        context.push_str(&shell.to_token_stream().to_string());
                        context.push_str(&collect(
                            items,
                            &format!("{scope}{}::", module.ident),
                            resolver,
                            versions,
                        )?);
                    } else {
                        context.push_str(&module.to_token_stream().to_string());
                    }
                }
                Item::Impl(implementation) => {
                    let Some((_, trait_path, _)) = &implementation.trait_ else {
                        context.push_str(&implementation.to_token_stream().to_string());
                        continue;
                    };
                    if !matches!(
                        resolver.resolve(trait_path).as_str(),
                        "picocast_pipeline::Step"
                            | "picocast_pipeline::step::Step"
                            | "crate::Step"
                            | "crate::step::Step"
                    ) {
                        context.push_str(&implementation.to_token_stream().to_string());
                        continue;
                    }
                    let mut name = None;
                    let mut version = None;
                    for item in &implementation.items {
                        if let syn::ImplItem::Const(value) = item {
                            if value.ident == "NAME" {
                                name = Some(value.expr.to_token_stream().to_string());
                            }
                            if value.ident == "VERSION" {
                                version = Some(value.expr.to_token_stream().to_string());
                            }
                        }
                    }
                    if let (Some(name), Some(version)) = (name, version) {
                        let identity = format!(
                            "{scope}{}::{name}",
                            implementation.self_ty.to_token_stream()
                        );
                        if versions
                            .insert(
                                identity,
                                (version, implementation.to_token_stream().to_string()),
                            )
                            .is_some()
                        {
                            bail!("Step識別子が重複しています");
                        }
                    }
                }
                _ => context.push_str(&item.to_token_stream().to_string()),
            }
        }
        resolver.aliases = saved;
        Ok(context)
    }
    let mut syntax = syn::parse_file(source)?;
    if path.split('/').any(|part| part == "tests") || test_attrs(&syntax.attrs) {
        return Ok(ProductionSteps {
            source: String::new(),
            versions: BTreeMap::new(),
        });
    }
    retain_production(&mut syntax.items);
    let mut versions = BTreeMap::new();
    let mut resolver = Scanner {
        path,
        aliases: BTreeMap::new(),
        violations: Vec::new(),
        tests: false,
    };
    let context = collect(&syntax.items, "", &mut resolver, &mut versions)?;
    Ok(ProductionSteps {
        source: context,
        versions,
    })
}

fn item_attrs(item: &Item) -> &[Attribute] {
    match item {
        Item::Const(item) => &item.attrs,
        Item::Enum(item) => &item.attrs,
        Item::ExternCrate(item) => &item.attrs,
        Item::Fn(item) => &item.attrs,
        Item::ForeignMod(item) => &item.attrs,
        Item::Impl(item) => &item.attrs,
        Item::Macro(item) => &item.attrs,
        Item::Mod(item) => &item.attrs,
        Item::Static(item) => &item.attrs,
        Item::Struct(item) => &item.attrs,
        Item::Trait(item) => &item.attrs,
        Item::TraitAlias(item) => &item.attrs,
        Item::Type(item) => &item.attrs,
        Item::Union(item) => &item.attrs,
        Item::Use(item) => &item.attrs,
        _ => &[],
    }
}

/// テスト専用の項目を除外し、マクロ内も含めた本番の文字列リテラルを収集する。
pub fn production_string_literals(source: &str) -> Result<BTreeSet<String>> {
    struct Literals {
        values: BTreeSet<String>,
        error: Option<syn::Error>,
    }
    impl<'ast> Visit<'ast> for Literals {
        fn visit_item(&mut self, node: &'ast syn::Item) {
            let attributes = item_attrs(node);
            if !test_attrs(attributes) {
                visit::visit_item(self, node);
            }
        }
        fn visit_item_mod(&mut self, node: &'ast syn::ItemMod) {
            if !test_attrs(&node.attrs) {
                visit::visit_item_mod(self, node);
            }
        }
        fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
            if !test_attrs(&node.attrs) {
                visit::visit_item_fn(self, node);
            }
        }
        fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
            if !test_attrs(&node.attrs) {
                visit::visit_impl_item_fn(self, node);
            }
        }
        fn visit_item_const(&mut self, node: &'ast syn::ItemConst) {
            if !test_attrs(&node.attrs) {
                visit::visit_item_const(self, node);
            }
        }
        fn visit_item_static(&mut self, node: &'ast syn::ItemStatic) {
            if !test_attrs(&node.attrs) {
                visit::visit_item_static(self, node);
            }
        }
        fn visit_lit_str(&mut self, literal: &'ast syn::LitStr) {
            self.values.insert(literal.value());
        }
        fn visit_macro(&mut self, node: &'ast syn::Macro) {
            // マクロの独自構文を式と解釈せず、括弧をたどって文字列だけ取り出す。
            match syn::parse2::<MacroStrings>(node.tokens.clone()) {
                Ok(strings) => self.values.extend(strings.0),
                Err(error) => self.error = Some(error),
            }
        }
    }
    struct MacroStrings(BTreeSet<String>);
    impl syn::parse::Parse for MacroStrings {
        fn parse(input: syn::parse::ParseStream<'_>) -> syn::Result<Self> {
            let mut values = BTreeSet::new();
            while !input.is_empty() {
                if input.peek(syn::LitStr) {
                    values.insert(input.parse::<syn::LitStr>()?.value());
                } else if input.peek(syn::token::Paren) {
                    let group;
                    syn::parenthesized!(group in input);
                    values.extend(group.parse::<Self>()?.0);
                } else if input.peek(syn::token::Brace) {
                    let group;
                    syn::braced!(group in input);
                    values.extend(group.parse::<Self>()?.0);
                } else if input.peek(syn::token::Bracket) {
                    let group;
                    syn::bracketed!(group in input);
                    values.extend(group.parse::<Self>()?.0);
                } else {
                    input.step(|cursor| {
                        cursor
                            .token_tree()
                            .map(|(_, next)| ((), next))
                            .ok_or_else(|| cursor.error("マクロのトークンを読み取れません"))
                    })?;
                }
            }
            Ok(Self(values))
        }
    }
    let syntax = syn::parse_file(source)?;
    if test_attrs(&syntax.attrs) {
        return Ok(BTreeSet::new());
    }
    if test_attrs(&syntax.attrs) {
        return Ok(BTreeSet::new());
    }
    let mut collector = Literals {
        values: BTreeSet::new(),
        error: None,
    };
    collector.visit_file(&syntax);
    if let Some(error) = collector.error {
        return Err(error.into());
    }
    Ok(collector.values)
}

fn scan_rust(path: &str, source: &str) -> Result<Vec<String>> {
    let ast = syn::parse_file(source)?;
    // integration tests は Cargo により本番バイナリから分離される。
    let tests = path.split('/').any(|p| p == "tests") || test_attrs(&ast.attrs);
    let mut scanner = Scanner {
        path,
        aliases: BTreeMap::new(),
        violations: Vec::new(),
        tests,
    };
    scanner.imports(&ast.items);
    scanner.visit_file(&ast);
    scanner.violations.sort();
    scanner.violations.dedup();
    Ok(scanner.violations)
}

struct Scanner<'a> {
    path: &'a str,
    aliases: BTreeMap<String, String>,
    violations: Vec<String>,
    tests: bool,
}

impl Scanner<'_> {
    fn imports(&mut self, items: &[Item]) {
        for item in items {
            if let Item::Use(item) = item {
                self.use_tree(&item.tree, "");
            }
            if let Item::Type(item) = item {
                if let syn::Type::Path(target) = item.ty.as_ref() {
                    self.aliases
                        .insert(item.ident.to_string(), self.resolve(&target.path));
                }
            }
        }
    }

    fn use_tree(&mut self, tree: &UseTree, prefix: &str) {
        match tree {
            UseTree::Path(path) => self.use_tree(&path.tree, &format!("{prefix}{}::", path.ident)),
            UseTree::Name(name) => {
                let target = if name.ident == "self" {
                    prefix.trim_end_matches("::").to_owned()
                } else {
                    format!("{prefix}{}", name.ident)
                };
                let alias = if name.ident == "self" {
                    target.rsplit("::").next().unwrap_or_default().to_owned()
                } else {
                    name.ident.to_string()
                };
                self.aliases.insert(alias, target);
            }
            UseTree::Rename(rename) => {
                let target = if rename.ident == "self" {
                    prefix.trim_end_matches("::").to_owned()
                } else {
                    format!("{prefix}{}", rename.ident)
                };
                self.aliases.insert(rename.rename.to_string(), target);
            }
            UseTree::Group(group) => {
                for item in &group.items {
                    self.use_tree(item, prefix);
                }
            }
            UseTree::Glob(_) if !self.tests => self.violations.push(format!(
                "ワイルドカード import は所有ルールの追跡を妨げます: {prefix}*"
            )),
            UseTree::Glob(_) => {}
        }
    }

    fn resolve(&self, path: &syn::Path) -> String {
        let raw = path
            .segments
            .iter()
            .map(|s| s.ident.to_string())
            .collect::<Vec<_>>()
            .join("::");
        if path.leading_colon.is_some() {
            return raw;
        }
        let mut resolved = raw;
        for _ in 0..self.aliases.len() {
            let (head, tail) = resolved.split_once("::").unwrap_or((&resolved, ""));
            let Some(target) = self.aliases.get(head) else {
                break;
            };
            let next = if tail.is_empty() {
                target.clone()
            } else {
                format!("{target}::{tail}")
            };
            if next == resolved {
                break;
            }
            resolved = next;
        }
        resolved
    }

    fn reject(&mut self, rule: &str, value: &str) {
        self.violations.push(format!("{rule}: {value}"));
    }

    fn check_path(&mut self, value: &str) {
        if !self.tests
            && (value.ends_with("::unwrap")
                || value.ends_with("::expect")
                || value.ends_with("::unwrap_unchecked")
                || value == "std::panic::panic_any")
        {
            self.reject("本番での強制停止は禁止", value);
        }
        let module = if matches!(
            value,
            "chrono::Utc::now" | "chrono::Local::now" | "std::time::SystemTime::now"
        ) || value.starts_with("chrono_tz::")
        {
            Some("clock")
        } else if value == "std::process::Command"
            || value.starts_with("std::process::Command::")
            || value == "tokio::process::Command"
            || value.starts_with("tokio::process::Command::")
        {
            Some("proc")
        } else if value == "reqwest::Client"
            || value == "reqwest::blocking::Client"
            || value.starts_with("reqwest::Client::")
            || value.starts_with("reqwest::blocking::Client::")
            || value == "reqwest::get"
            || value == "reqwest::blocking::get"
        {
            Some("http")
        } else if matches!(
            value,
            "std::fs::write"
                | "std::fs::File::create"
                | "std::fs::File::create_new"
                | "tokio::fs::write"
                | "tokio::fs::File::create"
                | "tokio::fs::File::create_new"
        ) || value.starts_with("std::fs::OpenOptions::")
            || value.starts_with("tokio::fs::OpenOptions::")
        {
            Some("fsutil")
        } else if matches!(
            value,
            "std::env::var"
                | "std::env::var_os"
                | "std::env::vars"
                | "std::env::vars_os"
                | "std::env::set_var"
                | "std::env::remove_var"
        ) {
            Some("settings")
        } else {
            None
        };
        if let Some(module) = module {
            if !owner(self.path, module) {
                self.reject(&format!("持ち主 {module} 以外の直接使用"), value);
            }
        }
        if (value == "rusqlite::Connection" || value.starts_with("rusqlite::Connection::open"))
            && !self.path.starts_with("crates/picocast-store/src/")
        {
            self.reject("DB は picocast-store に集約", value);
        }
        if (value == "chrono::NaiveDateTime" || value.starts_with("chrono::NaiveDateTime::"))
            && !owner(self.path, "clock")
        {
            self.reject("日時は UTC 型で保持", value);
        }
    }
}

impl<'ast> Visit<'ast> for Scanner<'_> {
    fn visit_item_mod(&mut self, node: &'ast syn::ItemMod) {
        let saved_tests = self.tests;
        self.tests |= test_attrs(&node.attrs);
        let saved = self.aliases.clone();
        if let Some((_, items)) = &node.content {
            self.imports(items);
        }
        visit::visit_item_mod(self, node);
        self.aliases = saved;
        self.tests = saved_tests;
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        let saved = self.tests;
        self.tests |= test_attrs(&node.attrs);
        visit::visit_item_fn(self, node);
        self.tests = saved;
    }

    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        let saved = self.tests;
        self.tests |= test_attrs(&node.attrs);
        visit::visit_impl_item_fn(self, node);
        self.tests = saved;
    }

    fn visit_block(&mut self, node: &'ast syn::Block) {
        let saved = self.aliases.clone();
        for stmt in &node.stmts {
            if let syn::Stmt::Item(Item::Use(item)) = stmt {
                self.use_tree(&item.tree, "");
            }
        }
        visit::visit_block(self, node);
        self.aliases = saved;
    }

    fn visit_expr_path(&mut self, node: &'ast syn::ExprPath) {
        self.check_path(&self.resolve(&node.path));
        if let Some(qself) = &node.qself {
            if let syn::Type::Path(target) = qself.ty.as_ref() {
                let value = format!(
                    "{}::{}",
                    self.resolve(&target.path),
                    self.resolve(&node.path)
                );
                self.check_path(&value);
            }
        }
        visit::visit_expr_path(self, node);
    }

    fn visit_type_path(&mut self, node: &'ast syn::TypePath) {
        self.check_path(&self.resolve(&node.path));
        visit::visit_type_path(self, node);
    }

    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        if !self.tests
            && (node.method == "unwrap"
                || node.method == "expect"
                || node.method == "unwrap_unchecked")
        {
            self.reject("本番での強制停止は禁止", &node.method.to_string());
        }
        visit::visit_expr_method_call(self, node);
    }

    fn visit_macro(&mut self, node: &'ast syn::Macro) {
        let resolved = self.resolve(&node.path);
        let name = resolved.rsplit("::").next().unwrap_or_default();
        if matches!(name, "println" | "eprintln" | "dbg") {
            self.reject("出力は tracing を使う", &resolved);
        }
        if matches!(name, "env" | "option_env") && !owner(self.path, "settings") {
            self.reject("環境変数は settings に集約", &resolved);
        }
        if !self.tests && matches!(name, "panic" | "todo" | "unimplemented") {
            self.reject("本番での強制停止は禁止", &resolved);
        }
        visit::visit_macro(self, node);
    }

    fn visit_lit_str(&mut self, node: &'ast syn::LitStr) {
        let value = node.value();
        let ai = [
            "generativelanguage.googleapis.com",
            "api.openai.com",
            "api.anthropic.com",
        ]
        .iter()
        .any(|host| value.contains(host));
        let youtube = value.contains("youtube.googleapis.com")
            || value.contains("www.googleapis.com/youtube")
            || value.contains("youtubeanalytics.googleapis.com");
        if ai && !self.path.starts_with("crates/picocast-ai/src/") {
            self.reject("AI URL はプロバイダに集約", &value);
        }
        if youtube && !self.path.starts_with("crates/picocast-youtube/src/") {
            self.reject("YouTube URL はプロバイダに集約", &value);
        }
    }
}

fn scan_js(path: &str, source: &str) -> Vec<String> {
    let mut violations = Vec::new();
    let mut code = String::new();
    let mut japanese_copy = false;
    let mut chars = source.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '/' && chars.peek() == Some(&'/') {
            chars.next();
            for next in chars.by_ref() {
                if next == '\n' {
                    break;
                }
            }
        } else if c == '/' && chars.peek() == Some(&'*') {
            chars.next();
            while let Some(next) = chars.next() {
                if next == '*' && chars.peek() == Some(&'/') {
                    chars.next();
                    break;
                }
            }
        } else if c == '\'' || c == '"' || c == '`' {
            while let Some(next) = chars.next() {
                if next == '\\' {
                    chars.next();
                    continue;
                }
                if next == c {
                    break;
                }
                japanese_copy |= ('\u{3040}'..='\u{30ff}').contains(&next)
                    || ('\u{4e00}'..='\u{9fff}').contains(&next);
                // テンプレート式も日時検査の対象にする。
                if c == '`' && !next.is_whitespace() {
                    code.push(next);
                }
            }
        } else if !c.is_whitespace() {
            code.push(c);
        }
    }
    if path != "ui/app/time.js"
        && ["newDate", "Date.now", ".toLocale"]
            .iter()
            .any(|s| code.contains(s))
    {
        violations.push("JS 時刻は ui/app/time.js に集約する".to_owned());
    }
    if japanese_copy {
        violations.push("画面文言は ui/i18n/*.json に集約する".to_owned());
    }
    violations
}

#[cfg(test)]
mod tests {
    use super::*;

    fn violations(path: &str, source: &str) -> Vec<String> {
        scan_rust(path, source).expect("検査用 Rust は正しい構文")
    }

    #[test]
    fn detects_direct_and_aliased_owner_bypasses() {
        for source in [
            "fn f() { chrono::Utc::now(); }",
            "use chrono::Utc as Clock; fn f() { Clock::now(); }",
            "use std::{process::Command as C, fs::write as w}; fn f() { C::new(\"x\"); w(\"x\", \"y\"); }",
            "use reqwest as h; fn f() { h::Client::new(); }",
            "use rusqlite::Connection as Db; fn f() { Db::open(\"x\"); }",
            "use std::env::var as setting; fn f() { setting(\"x\"); }",
            "fn f() { std::time::SystemTime::now(); }",
            "fn f() { std::fs::File::create(\"x\"); }",
            "use std::println as output; fn f() { output!(\"x\"); }",
            "use chrono::Utc; type Clock = Utc; fn f() { Clock::now(); }",
            "fn f() { Option::unwrap(Some(1)); }",
            "use chrono::Utc; fn f() { <Utc>::now(); }",
        ] {
            assert!(
                !violations("crates/picocast-media/src/lib.rs", source).is_empty(),
                "未検出: {source}"
            );
        }
    }

    #[test]
    fn allows_only_the_correct_owner() {
        assert!(violations(
            "crates/picocast-core/src/clock.rs",
            "use chrono::Utc; fn f() { Utc::now(); }"
        )
        .is_empty());
        assert!(!violations(
            "crates/picocast-core/src/clock_other.rs",
            "fn f() { chrono::Utc::now(); }"
        )
        .is_empty());
        assert!(violations(
            "crates/picocast-store/src/db.rs",
            "fn f() { rusqlite::Connection::open(\"x\"); }"
        )
        .is_empty());
    }

    #[test]
    fn panic_is_allowed_only_in_real_test_boundaries() {
        assert!(violations(
            "crates/picocast-store/src/external_tests.rs",
            "#![cfg(test)] fn fixture() { Some(1).unwrap(); }"
        )
        .is_empty());
        assert!(!violations(
            "crates/picocast-store/src/external_tests.rs",
            "fn fixture() { Some(1).unwrap(); }"
        )
        .is_empty());
        assert!(!violations(
            "crates/picocast-core/src/feature.rs",
            "fn f() { chrono::NaiveDateTime::parse_from_str(\"x\", \"y\"); }"
        )
        .is_empty());
        assert!(violations(
            "crates/picocast-core/src/clock.rs",
            "fn f() { chrono::NaiveDateTime::parse_from_str(\"x\", \"y\"); }"
        )
        .is_empty());
        assert!(!violations(
            "crates/picocast-core/src/lib.rs",
            "fn f() { Some(1).unwrap(); }"
        )
        .is_empty());
        assert!(!violations(
            "crates/picocast-core/src/lib.rs",
            "fn f() { panic!(\"x\"); }"
        )
        .is_empty());
        assert!(violations(
            "crates/picocast-core/src/lib.rs",
            "#[cfg(test)] mod tests { #[test] fn f() { Some(1).expect(\"x\"); panic!(\"x\"); } }"
        )
        .is_empty());
        assert!(!violations(
            "crates/picocast-core/src/lib.rs",
            "#[cfg(any(test, windows))] fn f() { Some(1).unwrap(); }"
        )
        .is_empty());
        assert!(violations(
            "crates/picocast-core/tests/contracts.rs",
            "fn f() { Some(1).unwrap(); }"
        )
        .is_empty());
    }

    #[test]
    fn block_aliases_do_not_leak_into_the_next_scope() {
        let source = "use chrono::Utc; fn f() { { use other::Utc; } Utc::now(); }";
        assert!(!violations("crates/picocast-media/src/lib.rs", source).is_empty());
    }

    #[test]
    fn javascript_time_and_copy_have_one_owner() {
        assert!(scan_js("ui/app/time.js", "export const now = () => Date.now();").is_empty());
        assert!(!scan_js("ui/app/home.js", "const now = Date.now();").is_empty());
        assert!(!scan_js("ui/app/home.js", "const label = '設定';").is_empty());
        assert!(scan_js("ui/app/home.js", "// 日本語コメント\nconst a = 1;").is_empty());
    }
}
