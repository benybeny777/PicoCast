#![allow(clippy::disallowed_methods)]

use crate::{AppError, Result};
use std::{
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};

/// ログの内部I/O。失敗は呼出側のhealthへ返し、同じログへ再入しない。
pub(crate) fn append_log(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_data()
}

/// 同じ役割のログ初期化を排他し、異常終了時はOSがロックを解放する。
pub(crate) fn lock_log_session(path: &Path) -> std::io::Result<std::fs::File> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(0);
    }
    let file = options.open(path)?;
    #[cfg(unix)]
    {
        use std::os::fd::AsRawFd;
        // ファイル記述子を所有したまま保持し、プロセス終了で排他を解除する。
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(file)
}

pub(crate) fn read_log_session(file: &mut std::fs::File) -> std::io::Result<Vec<u8>> {
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    Ok(bytes)
}

pub(crate) fn write_log_session(file: &mut std::fs::File, bytes: &[u8]) -> std::io::Result<()> {
    file.seek(SeekFrom::Start(0))?;
    file.set_len(0)?;
    file.write_all(bytes)?;
    file.sync_all()
}

/// 元ログを残したまま一時領域へ圧縮し、同期と排他的確定の成功後だけ削除する。
pub(crate) fn compress_log(source: &Path, destination: &Path) -> std::io::Result<()> {
    let parent = destination
        .parent()
        .ok_or_else(|| std::io::Error::other("圧縮先の親がありません"))?;
    let mut input = std::fs::File::open(source)?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    {
        let mut encoder =
            flate2::write::GzEncoder::new(temporary.as_file_mut(), flate2::Compression::default());
        std::io::copy(&mut input, &mut encoder)?;
        encoder.finish()?;
    }
    temporary.as_file().sync_all()?;
    temporary
        .persist_noclobber(destination)
        .map_err(|error| error.error)?;
    drop(input);
    std::fs::remove_file(source)
}

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
