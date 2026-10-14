#![allow(clippy::disallowed_methods)]

use crate::{AppError, Result};
use std::{io::Write, path::Path};

/// 新規ファイルを排他的に予約する。既存ファイルは変更しない。
pub fn reserve_new_file(path: &Path) -> Result<std::fs::File> {
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|err| {
            tracing::error!(error = %err, "新規ファイルの排他的予約に失敗");
            AppError::new(
                "E-FILE-RESERVE",
                "新規ファイルを予約できませんでした",
                "同名ファイルの使用状況と保存先の権限を確認してください",
            )
        })
}

/// 同じディレクトリの一時ファイルを同期してから原子的に置換する。
/// tempfile::persist は Windows でも既存ファイルを置換する。
pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .filter(|v| !v.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let operation = || -> std::io::Result<()> {
        let mut temp = tempfile::NamedTempFile::new_in(parent)?;
        temp.write_all(bytes)?;
        temp.as_file().sync_all()?;
        temp.persist(path).map_err(|err| err.error)?;
        #[cfg(unix)]
        std::fs::File::open(parent)?.sync_all()?;
        Ok(())
    };
    operation().map_err(|err| {
        tracing::error!(error = %err, "原子的ファイル保存に失敗");
        AppError::new(
            "E-FILE-WRITE",
            "ファイルを保存できませんでした",
            "保存先の権限と空き容量を確認してください",
        )
    })
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    #[test]
    fn reservation_never_overwrites_existing_contents() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("reserved");
        let mut file = reserve_new_file(&path).unwrap();
        file.write_all(b"keep").unwrap();
        file.sync_all().unwrap();
        assert_eq!(reserve_new_file(&path).unwrap_err().code, "E-FILE-RESERVE");
        drop(file);
        assert_eq!(std::fs::read(path).unwrap(), b"keep");
    }
    #[test]
    fn replaces_existing_file_and_keeps_it_on_failure() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("data");
        atomic_write(&path, b"old").unwrap();
        atomic_write(&path, b"new").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"new");
        assert!(atomic_write(&dir.path().join("missing/data"), b"bad").is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"new");
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 1);
    }
}
