//! データ保存先と、DB を開く前の危険検出を一元管理する。

use crate::{AppError, Result};
use std::path::{Path, PathBuf};

/// ツールや入力素材の末尾が通常ファイルであることを、追従せず確認する。
pub fn require_regular_file(path: &Path) -> Result<()> {
    let invalid = |cause: &'static str| {
        tracing::error!(
            code = "E-FILE-INVALID",
            cause,
            "通常ファイルの検査に失敗しました"
        );
        AppError::new("E-FILE-INVALID", "指定したファイルを使用できません",
            "存在する通常ファイルの絶対パスを指定し、リンク・ディレクトリ・アクセス権限を確認してください")
    };
    if !path.is_absolute() {
        return Err(invalid("relative_path"));
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|error| {
        tracing::error!(kind = ?error.kind(), "ファイルの属性を取得できませんでした");
        invalid("metadata")
    })?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(invalid("file_type"));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(invalid("reparse_point"));
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DataMode {
    Production,
    Development,
}

#[derive(Debug, Clone)]
pub struct StorePaths {
    pub root: PathBuf,
    pub database: PathBuf,
    pub backups: PathBuf,
    pub master_key: PathBuf,
}

impl StorePaths {
    /// OS のデータ親ディレクトリを呼び出し側から受け取る。他の保存先は探さない。
    pub fn new(data_parent: &Path, mode: DataMode) -> Result<Self> {
        require_absolute(data_parent)?;
        let root = data_parent.join(match mode {
            DataMode::Production => "PicoCast",
            DataMode::Development => "PicoCast-Dev",
        });
        Ok(Self {
            database: root.join("picocast.db"),
            backups: root.join("backups"),
            master_key: root.join("secret_master.key"),
            root,
        })
    }

    /// 内容アドレス素材の保存先。呼び出し側でパス名を重複定義しない。
    pub fn assets_directory(&self) -> PathBuf {
        self.root.join("assets")
    }

    /// 保存構成を変えずに復元用ステージへ向ける。実ファイルは移動・作成しない。
    pub fn relocated(&self, new_root: &Path) -> Result<Self> {
        require_absolute(&self.root)?;
        require_absolute(new_root)?;
        let rebase = |path: &Path| -> Result<PathBuf> {
            let relative = path
                .strip_prefix(&self.root)
                .map_err(|_| path_failure("保存構成が元の管理ルート外を指しています。"))?;
            if relative.as_os_str().is_empty()
                || relative
                    .components()
                    .any(|component| !matches!(component, std::path::Component::Normal(_)))
            {
                return Err(path_failure("保存構成の相対パスが不正です。"));
            }
            Ok(new_root.join(relative))
        };
        Ok(Self {
            root: new_root.to_path_buf(),
            database: rebase(&self.database)?,
            backups: rebase(&self.backups)?,
            master_key: rebase(&self.master_key)?,
        })
    }

    pub fn validate_storage(&self, policy: &StoragePolicy) -> Result<()> {
        let assets = self.assets_directory();
        for path in [
            &self.root,
            &self.database,
            &self.backups,
            &self.master_key,
            &assets,
        ] {
            validate_storage(path, policy)?;
        }
        Ok(())
    }
}

/// OS や設定正本から注入する。危険の許可は種類ごとの明示操作だけで有効にする。
#[derive(Debug, Clone, Default)]
pub struct StoragePolicy {
    pub sync_roots: Vec<PathBuf>,
    pub allow_cloud_sync: bool,
    pub allow_network: bool,
    pub allow_fat32: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StorageRisk {
    CloudSync,
    Network,
    Fat32,
}

impl StoragePolicy {
    pub fn check(&self, risks: &[StorageRisk]) -> Result<()> {
        for risk in risks {
            let allowed = match risk {
                StorageRisk::CloudSync => self.allow_cloud_sync,
                StorageRisk::Network => self.allow_network,
                StorageRisk::Fat32 => self.allow_fat32,
            };
            if !allowed {
                tracing::warn!(
                    code = "E-STORE-UNSAFE-PATH",
                    ?risk,
                    "危険な保存先の利用を拒否しました"
                );
                return Err(AppError::new(
                    "E-STORE-UNSAFE-PATH",
                    format!("保存先に危険があります（{}）。DB は開いていません。", match risk {
                        StorageRisk::CloudSync => "クラウド同期",
                        StorageRisk::Network => "ネットワークドライブ",
                        StorageRisk::Fat32 => "FAT32",
                    }),
                    "同期されないローカルディスクを選ぶか、危険を確認して該当する種類を明示的に許可してください。",
                ));
            }
        }
        Ok(())
    }
}

/// DB、素材、バックアップの保存先へ共通に適用する。検査ではファイルを作らない。
pub fn validate_storage(path: &Path, policy: &StoragePolicy) -> Result<()> {
    require_absolute(path)?;
    for root in &policy.sync_roots {
        require_absolute(root)?;
    }
    let mut risks = lexical_risks(path, &policy.sync_roots);
    // 文字列だけで分かる危険は、到達できない共有や同期先でも先に拒否する。
    policy.check(&risks)?;
    let resolved = resolve_existing_ancestor(path)?;
    risks.extend(lexical_risks(&resolved, &policy.sync_roots));
    policy.check(&risks)?;
    risks.extend(volume_risks(&resolved)?);
    policy.check(&risks)
}

pub(crate) fn require_absolute(path: &Path) -> Result<()> {
    if !path.is_absolute() || path.as_os_str().as_encoded_bytes().contains(&0) {
        return Err(path_failure("保存先は有効な絶対パスで指定してください。"));
    }
    Ok(())
}

/// Windows の区切り文字と大文字小文字を模擬テストでも同じように解釈する。
fn normalized(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/").to_lowercase()
}

fn lexical_risks(path: &Path, sync_roots: &[PathBuf]) -> Vec<StorageRisk> {
    let normalized = normalized(path);
    let normalized = normalized.strip_prefix("//?/").unwrap_or(&normalized);
    let mut risks = Vec::new();
    if normalized.starts_with("//") || normalized.starts_with("unc/") {
        risks.push(StorageRisk::Network);
    }
    let named_sync = normalized.split('/').any(|part| {
        matches!(
            part,
            "onedrive" | "dropbox" | "google drive" | "googledrive" | "my drive" | "マイドライブ"
        ) || part.starts_with("onedrive - ")
    });
    let configured_sync = sync_roots.iter().any(|root| {
        let root = self::normalized(root);
        let root = root
            .strip_prefix("//?/")
            .unwrap_or(&root)
            .trim_end_matches('/');
        normalized == root || normalized.starts_with(&format!("{root}/"))
    });
    if named_sync || configured_sync {
        risks.push(StorageRisk::CloudSync);
    }
    risks
}

fn resolve_existing_ancestor(path: &Path) -> Result<PathBuf> {
    let mut ancestor = path;
    let mut missing = Vec::new();
    loop {
        match std::fs::canonicalize(ancestor) {
            Ok(mut resolved) => {
                for component in missing.iter().rev() {
                    resolved.push(component);
                }
                return Ok(resolved);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let name = ancestor
                    .file_name()
                    .ok_or_else(|| path_failure("保存先の実体を確認できません。"))?;
                missing.push(name.to_owned());
                ancestor = ancestor
                    .parent()
                    .ok_or_else(|| path_failure("保存先の親がありません。"))?;
            }
            Err(error) => {
                tracing::error!(code = "E-STORE-PATH", cause = ?error.kind(), os_code = ?error.raw_os_error(), "保存先の実体検査に失敗しました");
                return Err(path_failure("保存先の実体を確認できません。"));
            }
        }
    }
}

#[cfg(windows)]
fn volume_risks(path: &Path) -> Result<Vec<StorageRisk>> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        GetDriveTypeW, GetVolumeInformationW, GetVolumePathNameW,
    };
    use windows_sys::Win32::System::WindowsProgramming::{
        DRIVE_NO_ROOT_DIR, DRIVE_REMOTE, DRIVE_UNKNOWN,
    };
    // Windows の拡張長パスの API 上限。利用者が調整する設定値ではない。
    const WINDOWS_PATH_CAPACITY: usize = 32768;
    let mut volume = vec![0u16; WINDOWS_PATH_CAPACITY];
    // 最も近い既存祖先に対して呼ぶため、初回起動の未作成ディレクトリも検査できる。
    let ancestor = path
        .ancestors()
        .find(|candidate| candidate.exists())
        .ok_or_else(|| path_failure("保存先のドライブを確認できません。"))?;
    let ancestor_wide: Vec<u16> = ancestor.as_os_str().encode_wide().chain(Some(0)).collect();
    let ok = unsafe {
        GetVolumePathNameW(
            ancestor_wide.as_ptr(),
            volume.as_mut_ptr(),
            volume.len() as u32,
        )
    };
    if ok == 0 {
        return Err(volume_failure());
    }
    let drive = unsafe { GetDriveTypeW(volume.as_ptr()) };
    if drive == DRIVE_UNKNOWN || drive == DRIVE_NO_ROOT_DIR {
        return Err(path_failure("保存先のドライブ種別を確認できません。"));
    }
    let mut filesystem = vec![0u16; WINDOWS_PATH_CAPACITY];
    let mut label = vec![0u16; WINDOWS_PATH_CAPACITY];
    let ok = unsafe {
        GetVolumeInformationW(
            volume.as_ptr(),
            label.as_mut_ptr(),
            label.len() as u32,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            filesystem.as_mut_ptr(),
            filesystem.len() as u32,
        )
    };
    if ok == 0 {
        return Err(volume_failure());
    }
    let decode = |buffer: &[u16]| {
        String::from_utf16_lossy(
            &buffer[..buffer
                .iter()
                .position(|value| *value == 0)
                .unwrap_or(buffer.len())],
        )
    };
    Ok(classify_volume(
        drive == DRIVE_REMOTE,
        &decode(&filesystem),
        &decode(&label),
    ))
}

fn classify_volume(network: bool, filesystem: &str, label: &str) -> Vec<StorageRisk> {
    let mut risks = Vec::new();
    if network {
        risks.push(StorageRisk::Network);
    }
    if filesystem.eq_ignore_ascii_case("FAT32") {
        risks.push(StorageRisk::Fat32);
    }
    if !lexical_risks(Path::new(label), &[]).is_empty() {
        risks.push(StorageRisk::CloudSync);
    }
    risks
}

#[cfg(windows)]
fn volume_failure() -> AppError {
    let error = std::io::Error::last_os_error();
    tracing::error!(code = "E-STORE-PATH", cause = ?error.kind(), os_code = ?error.raw_os_error(), "ドライブの実体検査に失敗しました");
    path_failure("保存先のファイルシステムを確認できません。")
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
fn volume_risks(path: &Path) -> Result<Vec<StorageRisk>> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let ancestor = path
        .ancestors()
        .find(|candidate| candidate.exists())
        .ok_or_else(|| path_failure("保存先のドライブを確認できません。"))?;
    let encoded = CString::new(ancestor.as_os_str().as_bytes())
        .map_err(|_| path_failure("保存先に不正な文字があります。"))?;
    let mut status = std::mem::MaybeUninit::<libc::statfs>::uninit();
    // statfs の成功時だけ OS が初期化した構造体を読む。
    if unsafe { libc::statfs(encoded.as_ptr(), status.as_mut_ptr()) } != 0 {
        let error = std::io::Error::last_os_error();
        tracing::error!(code = "E-STORE-PATH", cause = ?error.kind(), os_code = ?error.raw_os_error(), "ドライブの実体検査に失敗しました");
        return Err(path_failure("保存先のファイルシステムを確認できません。"));
    }
    let status = unsafe { status.assume_init() };
    #[cfg(target_os = "linux")]
    {
        // Linux のファイルシステム識別子。設定可能な値ではない。
        const CIFS_SUPER_MAGIC: libc::c_long = 0xff534d42;
        const SMB2_SUPER_MAGIC: libc::c_long = 0xfe534d42;
        let network =
            [libc::NFS_SUPER_MAGIC, CIFS_SUPER_MAGIC, SMB2_SUPER_MAGIC].contains(&status.f_type);
        // statfs は FAT のビット幅を返さないため、FAT 系は保守的に同じ危険として扱う。
        let filesystem = if status.f_type == libc::MSDOS_SUPER_MAGIC {
            "FAT32"
        } else {
            "local"
        };
        Ok(classify_volume(network, filesystem, ""))
    }
    #[cfg(target_os = "macos")]
    {
        let filesystem =
            unsafe { std::ffi::CStr::from_ptr(status.f_fstypename.as_ptr()) }.to_string_lossy();
        Ok(classify_volume(
            status.f_flags & libc::MNT_LOCAL as u32 == 0,
            if filesystem == "msdos" {
                "FAT32"
            } else {
                &filesystem
            },
            "",
        ))
    }
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
fn volume_risks(_path: &Path) -> Result<Vec<StorageRisk>> {
    Err(path_failure("この OS の保存先ドライブ検査は未対応です。"))
}

fn path_failure(message: &str) -> AppError {
    tracing::error!(
        code = "E-STORE-PATH",
        cause = message,
        "保存先の検査が失敗しました"
    );
    AppError::new(
        "E-STORE-PATH",
        message,
        "利用可能なローカルディスクの絶対パスとアクセス権限を確認してください。",
    )
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn relocating_preserves_layout_without_creating_files_and_rejects_external_fields() {
        let temporary = tempfile::tempdir().unwrap();
        let mut original = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        original.database = original.root.join("nested").join("custom.db");
        let stage = temporary.path().join("stage");
        let relocated = original.relocated(&stage).unwrap();
        assert_eq!(relocated.database, stage.join("nested").join("custom.db"));
        assert_eq!(
            relocated.backups,
            stage.join(original.backups.strip_prefix(&original.root).unwrap())
        );
        assert_eq!(
            relocated.master_key,
            stage.join(original.master_key.strip_prefix(&original.root).unwrap())
        );
        assert_eq!(relocated.assets_directory(), stage.join("assets"));
        assert!(!stage.exists());
        assert!(original.relocated(Path::new("relative")).is_err());
        original.database = temporary.path().join("external.db");
        assert!(original.relocated(&stage).is_err());
        original.database = original.root.join("..").join("external.db");
        assert!(original.relocated(&stage).is_err());
    }

    #[test]
    fn simulated_sync_and_network_paths_require_specific_permission() {
        for path in [
            r"C:\Users\a\OneDrive - Work\data",
            r"C:\Dropbox\data",
            r"G:\My Drive\data",
            r"G:\Google Drive\data",
            r"\\server\share\data",
            r"\\?\UNC\server\share\data",
        ] {
            let risks = lexical_risks(Path::new(path), &[]);
            assert!(!risks.is_empty(), "{path}");
            assert_eq!(
                StoragePolicy::default().check(&risks).unwrap_err().code,
                "E-STORE-UNSAFE-PATH"
            );
        }
        let risks = lexical_risks(
            Path::new(r"C:\custom\sync\data"),
            &[PathBuf::from(r"c:\CUSTOM\sync")],
        );
        assert_eq!(risks, vec![StorageRisk::CloudSync]);
        assert!(lexical_risks(
            Path::new(r"C:\custom\synchronous"),
            &[PathBuf::from(r"C:\custom\sync")]
        )
        .is_empty());
        let policy = StoragePolicy {
            allow_cloud_sync: true,
            ..Default::default()
        };
        assert!(policy.check(&[StorageRisk::CloudSync]).is_ok());
        assert!(policy.check(&[StorageRisk::Network]).is_err());
        assert!(policy.check(&[StorageRisk::Fat32]).is_err());
    }

    #[test]
    fn simulated_volume_metadata_rejects_mapped_network_fat32_and_google_drive() {
        for (network, filesystem, label, expected) in [
            (true, "NTFS", "share", StorageRisk::Network),
            (false, "fat32", "USB", StorageRisk::Fat32),
            (false, "FAT32", "Google Drive", StorageRisk::CloudSync),
        ] {
            let risks = classify_volume(network, filesystem, label);
            assert!(risks.contains(&expected));
            assert!(StoragePolicy::default().check(&risks).is_err());
        }
        let policy = StoragePolicy {
            allow_fat32: true,
            ..Default::default()
        };
        assert!(policy
            .check(&classify_volume(false, "FAT32", "USB"))
            .is_ok());
        assert!(classify_volume(false, "NTFS", "Local").is_empty());
    }

    #[cfg(any(windows, target_os = "linux", target_os = "macos"))]
    #[test]
    fn assets_directory_has_one_owner_and_is_guarded_before_database_open() {
        let temporary = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        assert_eq!(paths.assets_directory(), paths.root.join("assets"));
        let production = StorePaths::new(temporary.path(), DataMode::Production).unwrap();
        assert_ne!(production.assets_directory(), paths.assets_directory());
        let policy = StoragePolicy {
            sync_roots: vec![paths.assets_directory()],
            ..Default::default()
        };
        assert_eq!(
            paths.validate_storage(&policy).unwrap_err().code,
            "E-STORE-UNSAFE-PATH"
        );
        assert!(!paths.root.exists());
    }

    #[cfg(windows)]
    #[test]
    fn native_local_volume_is_checked_before_creating_data() {
        let temporary = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        paths.validate_storage(&StoragePolicy::default()).unwrap();
        assert!(!paths.root.exists());
    }
}
