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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContentAsset {
    pub sha256: String,
    pub bytes: u64,
    pub path: std::path::PathBuf,
    pub ext: String,
}

/// メディアを全量メモリへ載せず、同じ内容の実体は拡張子が違っても再利用する。
pub fn import_content_addressed(source: &Path, assets_root: &Path) -> Result<ContentAsset> {
    let operation = || -> std::io::Result<ContentAsset> {
        if !source.is_absolute() || !assets_root.is_absolute() {
            return Err(std::io::Error::other("素材のパスは絶対パスが必要です"));
        }
        let source_metadata = std::fs::symlink_metadata(source)?;
        if !source_metadata.is_file() || source_metadata.file_type().is_symlink() {
            return Err(std::io::Error::other(
                "素材の実体が通常ファイルではありません",
            ));
        }
        let ext = source
            .extension()
            .and_then(|value| value.to_str())
            .filter(|value| !value.is_empty() && value.bytes().all(|b| b.is_ascii_alphanumeric()))
            .ok_or_else(|| std::io::Error::other("素材の拡張子が不正です"))?
            .to_ascii_lowercase();
        std::fs::create_dir_all(assets_root)?;
        if std::fs::symlink_metadata(assets_root)?
            .file_type()
            .is_symlink()
        {
            return Err(std::io::Error::other("素材保存先にリンクは指定できません"));
        }
        let _lock = lock_log_session(&assets_root.join(".import.lock"))?;
        let mut input = std::fs::File::open(source)?;
        let mut temporary = tempfile::NamedTempFile::new_in(assets_root)?;
        let (hash, bytes) = hash_stream(&mut input, Some(temporary.as_file_mut()))?;
        temporary.as_file().sync_all()?;
        let after = std::fs::metadata(source)?;
        if source_metadata.len() != after.len()
            || source_metadata.modified()? != after.modified()?
        {
            return Err(std::io::Error::other("取り込み中に素材が変更されました"));
        }
        temporary.as_file_mut().seek(SeekFrom::Start(0))?;
        if hash_stream(temporary.as_file_mut(), None)? != (hash.clone(), bytes) {
            return Err(std::io::Error::other(
                "コピー後の素材ハッシュが一致しません",
            ));
        }
        // 2桁ずつのディレクトリは内容アドレスの固定形式。
        let first = assets_root.join(&hash[..2]);
        let parent = first.join(&hash[2..4]);
        for directory in [&first, &parent] {
            match std::fs::create_dir(directory) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error),
            }
            let metadata = std::fs::symlink_metadata(directory)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() {
                return Err(std::io::Error::other("素材保存先の実体が不正です"));
            }
        }
        let mut existing = None;
        for entry in std::fs::read_dir(&parent)? {
            let entry = entry?;
            let path = entry.path();
            if path.file_stem().and_then(|value| value.to_str()) != Some(hash.as_str()) {
                continue;
            }
            let metadata = std::fs::symlink_metadata(&path)?;
            if !metadata.is_file() || metadata.file_type().is_symlink() || existing.is_some() {
                return Err(std::io::Error::other(
                    "同じ素材ハッシュの実体が不正または重複しています",
                ));
            }
            let canonical_ext = path
                .extension()
                .and_then(|value| value.to_str())
                .filter(|value| {
                    !value.is_empty() && value.bytes().all(|b| b.is_ascii_alphanumeric())
                })
                .ok_or_else(|| std::io::Error::other("既存素材の拡張子が不正です"))?
                .to_owned();
            if hash_stream(&mut std::fs::File::open(&path)?, None)? != (hash.clone(), bytes) {
                return Err(std::io::Error::other(
                    "既存素材の内容がハッシュと一致しません",
                ));
            }
            existing = Some(ContentAsset {
                sha256: hash.clone(),
                bytes,
                path,
                ext: canonical_ext,
            });
        }
        if let Some(asset) = existing {
            return Ok(asset);
        }
        let path = parent.join(format!("{hash}.{ext}"));
        temporary
            .persist_noclobber(&path)
            .map_err(|error| error.error)?;
        Ok(ContentAsset {
            sha256: hash,
            bytes,
            path,
            ext,
        })
    };
    operation().map_err(|error| {
        tracing::error!(code="E-FILE-IMPORT", cause=?error.kind(), "内容アドレス素材の取り込みに失敗");
        AppError::new("E-FILE-IMPORT", "素材を取り込めませんでした", "元素材の変更・保存先の権限と容量・既存ハッシュの整合性を確認してください")
    })
}

fn hash_stream(
    reader: &mut impl Read,
    mut copy_to: Option<&mut std::fs::File>,
) -> std::io::Result<(String, u64)> {
    use sha2::{Digest, Sha256};
    let mut hash = Sha256::new();
    let mut bytes = 0u64;
    // 固定I/Oバッファで、動画のサイズに比例してメモリを増やさない。
    let mut buffer = [0u8; 65536];
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
        if let Some(writer) = &mut copy_to {
            writer.write_all(&buffer[..read])?;
        }
        bytes = bytes
            .checked_add(read as u64)
            .ok_or_else(|| std::io::Error::other("素材サイズの上限を超えました"))?;
    }
    let digest = hash.finalize();
    Ok((
        digest.iter().map(|value| format!("{value:02x}")).collect(),
        bytes,
    ))
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
    fn streaming_import_reuses_identical_bytes_and_rejects_corruption() {
        let dir = tempfile::tempdir().unwrap();
        let source = dir.path().join("sample.wav");
        let other = dir.path().join("different.mp3");
        let assets = dir.path().join("assets");
        atomic_write(&source, &vec![42; 200_000]).unwrap();
        atomic_write(&other, &vec![42; 200_000]).unwrap();
        let first = import_content_addressed(&source, &assets).unwrap();
        let second = import_content_addressed(&other, &assets).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.bytes, 200_000);
        assert_eq!(first.ext, "wav");
        atomic_write(&first.path, b"broken").unwrap();
        assert_eq!(
            import_content_addressed(&source, &assets).unwrap_err().code,
            "E-FILE-IMPORT"
        );
        assert_eq!(std::fs::read(&source).unwrap().len(), 200_000);
        assert_eq!(std::fs::read(&first.path).unwrap(), b"broken");
    }
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
