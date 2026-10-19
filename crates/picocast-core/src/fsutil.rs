#![allow(clippy::disallowed_methods)]

use crate::{AppError, Result};
use std::{
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};

/// 保存先そのものに一時ファイルを作って閉じ、利用可能容量も確認する。
/// 保存領域の同期/共有ドライブ許可は呼出元のStoragePolicyで別途照合する。
pub fn check_output_capacity(directory: &Path, minimum_free_bytes: u64) -> Result<bool> {
    let operation = || -> std::io::Result<bool> {
        if !directory.is_absolute() || minimum_free_bytes == 0 {
            return Err(std::io::Error::other("保存先と必要容量が不正"));
        }
        regular_directory(directory)?;
        let probe = tempfile::NamedTempFile::new_in(directory)?;
        probe.close()?;
        Ok(available_space(directory)? >= minimum_free_bytes)
    };
    operation().map_err(|error| {
        tracing::error!(cause = ?error.kind(), "生成先の書込み・容量点検に失敗");
        AppError::new(
            "E-PREFLIGHT-DISK",
            "保存先を利用できません",
            "保存先の実体・権限・必要空き容量を確認してください",
        )
    })
}

#[cfg(windows)]
fn available_space(directory: &Path) -> std::io::Result<u64> {
    use std::os::windows::ffi::OsStrExt;
    let path: Vec<u16> = directory.as_os_str().encode_wide().chain(Some(0)).collect();
    if path[..path.len() - 1].contains(&0) {
        return Err(std::io::Error::other("パスが不正"));
    }
    let mut available = 0;
    let success = unsafe {
        windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW(
            path.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if success == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(available)
    }
}

#[cfg(unix)]
fn available_space(directory: &Path) -> std::io::Result<u64> {
    use std::os::unix::ffi::OsStrExt;
    let path = std::ffi::CString::new(directory.as_os_str().as_bytes())?;
    let mut stat = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    if unsafe { libc::statvfs(path.as_ptr(), stat.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error());
    }
    let stat = unsafe { stat.assume_init() };
    let available = u128::from(stat.f_bavail) * u128::from(stat.f_frsize);
    u64::try_from(available).map_err(|_| std::io::Error::other("容量計算の上限超過"))
}

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

/// 内容アドレスの配置形式はこの入口だけが定義する。外部入力をそのまま join しない。
pub fn content_asset_path(
    assets_root: &Path,
    sha256: &str,
    ext: &str,
) -> Result<std::path::PathBuf> {
    crate::paths::require_absolute(assets_root)?;
    if sha256.len() != 64
        || !sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || ext.is_empty()
        || !ext
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
    {
        tracing::error!(code = "E-FILE-IMPORT", "内容アドレスの構成要素が不正です");
        return Err(AppError::new(
            "E-FILE-IMPORT",
            "内容アドレスのパスを解決できません。",
            "絶対パスの素材ルート・小文字64桁のSHA-256・小文字英数字の拡張子を指定してください。",
        ));
    }
    Ok(assets_root
        .join(&sha256[..2])
        .join(&sha256[2..4])
        .join(format!("{sha256}.{ext}")))
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
        let path = content_asset_path(assets_root, &hash, &ext)
            .map_err(|_| std::io::Error::other("内容アドレスの構成要素が不正です"))?;
        let parent = path
            .parent()
            .ok_or_else(|| std::io::Error::other("素材の親がありません"))?;
        let first = parent
            .parent()
            .ok_or_else(|| std::io::Error::other("素材の上位ディレクトリがありません"))?;
        for directory in [first, parent] {
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
        for entry in std::fs::read_dir(parent)? {
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

/// 大きい暗号化データを書き出すための専用所有者。実ファイルを外へ渡さない。
pub struct NewFileWriter {
    file: std::fs::File,
}

impl Write for NewFileWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.file.write(bytes).inspect_err(|error| {
            tracing::error!(code="E-FILE-WRITE", cause=?error.kind(), os_code=?error.raw_os_error(), "新規ファイルへのストリーム書込みに失敗しました");
        })
    }

    fn flush(&mut self) -> std::io::Result<()> {
        self.file.flush().inspect_err(|error| {
            tracing::error!(code="E-FILE-WRITE", cause=?error.kind(), os_code=?error.raw_os_error(), "新規ファイルの flush に失敗しました");
        })
    }
}

impl NewFileWriter {
    /// 完了を明示し、同期してからハンドルを解放する。途中失敗を成功と扱わない。
    pub fn finish(self) -> Result<()> {
        self.file.sync_all().map_err(|error| {
            tracing::error!(code="E-FILE-WRITE", cause=?error.kind(), os_code=?error.raw_os_error(), "新規ファイルの同期に失敗しました");
            AppError::new("E-FILE-WRITE", "新規ファイルを同期できませんでした。", "保存先の容量とアクセス権限を確認し、処理が未完了のファイルを完成品として使用しないでください。")
        })
    }
}

/// 親を準備し、新規パスを排他的に予約する。既存先は変更しない。
pub fn new_file_writer(path: &Path) -> Result<NewFileWriter> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .ok_or_else(|| {
            tracing::error!(code = "E-FILE-WRITE", "新規ファイルの親がありません");
            AppError::new(
                "E-FILE-WRITE",
                "新規ファイルの保存先が不正です。",
                "親ディレクトリを持つ保存先を指定してください。",
            )
        })?;
    std::fs::create_dir_all(parent).map_err(|error| {
        tracing::error!(code="E-FILE-WRITE", cause=?error.kind(), os_code=?error.raw_os_error(), "新規ファイルの親を作成できませんでした");
        AppError::new("E-FILE-WRITE", "新規ファイルの保存先を準備できませんでした。", "保存先の容量とアクセス権限を確認してください。")
    })?;
    Ok(NewFileWriter {
        file: reserve_new_file(path)?,
    })
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
    atomic_write_with(path, bytes, |temporary, target| {
        temporary
            .persist(target)
            .map(|_| ())
            .map_err(|error| error.error)
    })
}

/// 新規ファイルだけを原子的に確定する。既存ファイルは競合時も置換しない。
pub fn atomic_write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    atomic_write_with(path, bytes, |temporary, target| {
        temporary
            .persist_noclobber(target)
            .map(|_| ())
            .map_err(|error| error.error)
    })
}

fn atomic_write_with(
    path: &Path,
    bytes: &[u8],
    persist: impl FnOnce(tempfile::NamedTempFile, &Path) -> std::io::Result<()>,
) -> Result<()> {
    let parent = path
        .parent()
        .filter(|v| !v.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let operation = || -> std::io::Result<()> {
        let mut temp = tempfile::NamedTempFile::new_in(parent)?;
        temp.write_all(bytes)?;
        temp.as_file().sync_all()?;
        persist(temp, path)?;
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

/// 同じ実体の親に置いた復元ステージを、既存先を置換せず原子的に公開する。
pub fn publish_new_directory(stage: &Path, target: &Path) -> Result<()> {
    let operation = || -> std::io::Result<()> {
        if !stage.is_absolute() || !target.is_absolute() {
            return Err(std::io::Error::other("公開元と公開先は絶対パスが必要です"));
        }
        let stage_parent = stage
            .parent()
            .ok_or_else(|| std::io::Error::other("ステージの親がありません"))?;
        let target_parent = target
            .parent()
            .ok_or_else(|| std::io::Error::other("公開先の親がありません"))?;
        regular_directory(stage_parent)?;
        regular_directory(target_parent)?;
        let parent = std::fs::canonicalize(stage_parent)?;
        if parent != std::fs::canonicalize(target_parent)? {
            return Err(std::io::Error::other(
                "公開元と公開先は同じ実体の親が必要です",
            ));
        }
        let stage_name = stage
            .file_name()
            .ok_or_else(|| std::io::Error::other("ステージ名が不正です"))?;
        let target_name = target
            .file_name()
            .ok_or_else(|| std::io::Error::other("公開先名が不正です"))?;
        let resolved_stage = parent.join(stage_name);
        let resolved_target = parent.join(target_name);
        regular_directory(&resolved_stage)?;
        // 事前検査後の競合も OS の排他的 rename が拒否する。
        match std::fs::symlink_metadata(&resolved_target) {
            Ok(_) => {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::AlreadyExists,
                    "公開先は既に存在します",
                ))
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
        rename_directory_noreplace(&resolved_stage, &resolved_target)
    };
    operation().map_err(|error| {
        tracing::error!(code="E-FILE-WRITE", cause=?error.kind(), os_code=?error.raw_os_error(), "復元ディレクトリの排他的公開に失敗しました");
        AppError::new("E-FILE-WRITE", "復元ディレクトリを公開できませんでした。", "既存の公開先は削除せず、同じ親の新しい名前・ステージの実体・アクセス権限を確認してください。")
    })
}

fn regular_directory(path: &Path) -> std::io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    let linked = metadata.file_type().is_symlink();
    #[cfg(windows)]
    let linked = {
        use std::os::windows::fs::MetadataExt;
        linked
            || metadata.file_attributes()
                & windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT
                != 0
    };
    if !metadata.is_dir() || linked {
        return Err(std::io::Error::other(
            "通常のディレクトリだけを指定してください",
        ));
    }
    Ok(())
}

#[cfg(windows)]
fn rename_directory_noreplace(stage: &Path, target: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    let encode = |path: &Path| -> std::io::Result<Vec<u16>> {
        let encoded: Vec<u16> = path.as_os_str().encode_wide().collect();
        if encoded.contains(&0) {
            return Err(std::io::Error::other("パスに不正な文字があります"));
        }
        Ok(encoded.into_iter().chain(Some(0)).collect())
    };
    let stage = encode(stage)?;
    let target = encode(target)?;
    // flags=0 は置換とドライブ間コピーを許可しない Win32 の固定契約。
    let succeeded = unsafe {
        windows_sys::Win32::Storage::FileSystem::MoveFileExW(stage.as_ptr(), target.as_ptr(), 0)
    };
    if succeeded == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
fn rename_directory_noreplace(stage: &Path, target: &Path) -> std::io::Result<()> {
    use std::{ffi::CString, os::unix::ffi::OsStrExt};
    let stage = CString::new(stage.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::other("パスに不正な文字があります"))?;
    let target = CString::new(target.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::other("パスに不正な文字があります"))?;
    #[cfg(target_os = "linux")]
    let result = unsafe {
        libc::renameat2(
            libc::AT_FDCWD,
            stage.as_ptr(),
            libc::AT_FDCWD,
            target.as_ptr(),
            libc::RENAME_NOREPLACE,
        )
    };
    #[cfg(target_os = "macos")]
    let result = unsafe { libc::renamex_np(stage.as_ptr(), target.as_ptr(), libc::RENAME_EXCL) };
    if result != 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
fn rename_directory_noreplace(_stage: &Path, _target: &Path) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "この OS は排他的なディレクトリ公開に未対応です",
    ))
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    #[test]
    fn new_file_writer_streams_multiple_chunks_and_never_replaces_existing_file() {
        let directory = tempfile::tempdir().unwrap();
        let target = directory.path().join("nested").join("bundle");
        let mut writer = new_file_writer(&target).unwrap();
        writer.write_all(b"first-").unwrap();
        std::io::copy(&mut std::io::Cursor::new(b"second"), &mut writer).unwrap();
        writer.finish().unwrap();
        assert_eq!(std::fs::read(&target).unwrap(), b"first-second");
        assert_eq!(
            new_file_writer(&target).err().unwrap().code,
            "E-FILE-RESERVE"
        );
        assert_eq!(std::fs::read(&target).unwrap(), b"first-second");
    }
    #[test]
    fn content_paths_reject_noncanonical_hash_ext_and_relative_root() {
        let directory = tempfile::tempdir().unwrap();
        let hash = "a".repeat(64);
        let path = content_asset_path(directory.path(), &hash, "png").unwrap();
        assert_eq!(
            path,
            directory
                .path()
                .join("aa")
                .join("aa")
                .join(format!("{hash}.png"))
        );
        for (candidate, ext) in [
            ("a".repeat(63), "png"),
            ("A".repeat(64), "png"),
            ("g".repeat(64), "png"),
            (hash.clone(), "PNG"),
            (hash.clone(), "../png"),
            (hash.clone(), ""),
        ] {
            assert!(content_asset_path(directory.path(), &candidate, ext).is_err());
        }
        assert!(content_asset_path(Path::new("relative"), &hash, "png").is_err());
    }

    #[test]
    fn exclusive_file_write_preserves_existing_bytes() {
        let directory = tempfile::tempdir().unwrap();
        let target = directory.path().join("bundle");
        atomic_write_new(&target, b"original").unwrap();
        assert_eq!(
            atomic_write_new(&target, b"replacement").unwrap_err().code,
            "E-FILE-WRITE"
        );
        assert_eq!(std::fs::read(target).unwrap(), b"original");
    }

    #[test]
    fn publish_directory_preserves_all_existing_targets() {
        let directory = tempfile::tempdir().unwrap();
        let stage = directory.path().join("stage");
        let target = directory.path().join("target");
        std::fs::create_dir(&stage).unwrap();
        atomic_write_new(&stage.join("retained"), b"stage").unwrap();
        std::fs::create_dir(&target).unwrap();
        assert!(publish_new_directory(&stage, &target).is_err());
        assert!(target.is_dir());
        assert!(std::fs::read_dir(&target).unwrap().next().is_none());
        // 事前の exists 検査を経ない OS primitive 自体も、空の既存先を置換しない。
        assert!(rename_directory_noreplace(&stage, &target).is_err());
        atomic_write_new(&target.join("retained"), b"target").unwrap();
        assert!(publish_new_directory(&stage, &target).is_err());
        assert_eq!(std::fs::read(target.join("retained")).unwrap(), b"target");
        assert_eq!(std::fs::read(stage.join("retained")).unwrap(), b"stage");
    }

    #[test]
    fn publishes_new_sibling_directory_but_refuses_different_parent() {
        let directory = tempfile::tempdir().unwrap();
        let stage = directory.path().join("stage");
        let target = directory.path().join("published");
        let other = directory.path().join("other");
        std::fs::create_dir(&stage).unwrap();
        std::fs::create_dir(&other).unwrap();
        atomic_write_new(&stage.join("value"), b"retained").unwrap();
        assert!(publish_new_directory(&stage, &other.join("target")).is_err());
        assert!(stage.is_dir());
        publish_new_directory(&stage, &target).unwrap();
        assert!(!stage.exists());
        assert_eq!(std::fs::read(target.join("value")).unwrap(), b"retained");
    }
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
