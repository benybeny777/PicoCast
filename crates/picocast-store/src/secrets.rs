//! AES-256-GCM と利用者単位 DPAPI。秘密値は Debug・ログへ出さない。

use std::path::Path;

use aes_gcm::{
    aead::{Aead, Payload},
    Aes256Gcm, KeyInit, Nonce,
};
use picocast_core::{fsutil, ids::ChannelId, Result};
use zeroize::Zeroizing;

use crate::{failure, io_failure};

pub struct MasterKey(Zeroizing<[u8; 32]>);

impl MasterKey {
    /// メモリ内のキーを生成する。永続化は明示的な create を使う。
    pub fn generate() -> Result<Self> {
        let mut bytes = Zeroizing::new([0u8; 32]);
        getrandom::fill(bytes.as_mut()).map_err(|error| {
            tracing::error!(code = "E-SECRET-RANDOM", cause = %error, "暗号鍵の乱数生成に失敗しました");
            failure("E-SECRET-RANDOM", "暗号鍵を生成できません。", "OS の乱数機能を確認してください。")
        })?;
        Ok(Self(bytes))
    }

    /// 新規 DB の初期化時だけ呼ぶ。既存キーを上書きしない。
    pub fn create(path: &Path) -> Result<Self> {
        let lock_path = path.with_extension("key.lock");
        let lock = fsutil::reserve_new_file(&lock_path)?;
        let result = (|| {
            if path.try_exists().map_err(|error| {
                io_failure(
                    "E-SECRET-KEY",
                    "マスターキーの状態を確認できません。",
                    "保存先の権限を確認してください。",
                    &error,
                )
            })? {
                return Err(failure(
                    "E-SECRET-KEY",
                    "マスターキーは既に存在します。",
                    "既存キーを読み込んでください。",
                ));
            }
            let key = Self::generate()?;
            let protected = protect(key.0.as_slice())?;
            fsutil::atomic_write(path, &protected)?;
            Ok(key)
        })();
        drop(lock);
        std::fs::remove_file(&lock_path).map_err(|error| {
            io_failure(
                "E-SECRET-KEY",
                "初期化ロックを解放できません。",
                "保存先の権限を確認してください。",
                &error,
            )
        })?;
        result
    }

    /// キーの欠損・DPAPI 失敗は停止する。代替キーを生成しない。
    pub fn load(path: &Path) -> Result<Self> {
        let protected = std::fs::read(path).map_err(|error| {
            io_failure(
                "E-SECRET-KEY",
                "マスターキーを読み込めません。",
                "元の Windows 利用者でキーを復元してください。",
                &error,
            )
        })?;
        let bytes = unprotect(&protected)?;
        if bytes.len() != 32 {
            return Err(failure(
                "E-SECRET-KEY",
                "マスターキーの長さが不正です。",
                "元のマスターキーを復元してください。",
            ));
        }
        let mut key = Zeroizing::new([0u8; 32]);
        key.copy_from_slice(&bytes);
        Ok(Self(key))
    }

    pub(crate) fn encrypt(
        &self,
        channel_id: &ChannelId,
        secret_type: &str,
        plaintext: &[u8],
    ) -> Result<([u8; 12], Vec<u8>)> {
        let mut nonce = [0u8; 12];
        getrandom::fill(&mut nonce).map_err(|error| {
            tracing::error!(code = "E-SECRET-RANDOM", cause = %error, "暗号 nonce の生成に失敗しました");
            failure("E-SECRET-RANDOM", "認証情報の暗号化乱数を生成できません。", "OS の乱数機能を確認してください。")
        })?;
        let cipher = Aes256Gcm::new_from_slice(self.0.as_slice()).map_err(|_| {
            failure(
                "E-SECRET-KEY",
                "暗号鍵が不正です。",
                "マスターキーを復元してください。",
            )
        })?;
        let aad = identity_aad(channel_id, secret_type);
        let encrypted = cipher
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: plaintext,
                    aad: &aad,
                },
            )
            .map_err(|_| {
                failure(
                    "E-SECRET-ENCRYPT",
                    "認証情報を暗号化できません。",
                    "マスターキーを確認してください。",
                )
            })?;
        Ok((nonce, encrypted))
    }

    /// 旧PythonのAESGCM(...).decrypt(nonce,ciphertext,None)だけを扱う。
    /// 既存のDPAPI生blobはloadで読み、欠損キーを生成しない。
    pub(crate) fn decrypt_legacy(
        &self,
        nonce: &[u8],
        ciphertext: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>> {
        if nonce.len() != 12 {
            return Err(failure(
                "E-SECRET-DECRYPT",
                "旧認証情報の暗号形式が壊れています。",
                "旧版のDBとマスターキーのバックアップを確認してください。",
            ));
        }
        let cipher = Aes256Gcm::new_from_slice(self.0.as_slice()).map_err(|_| {
            failure(
                "E-SECRET-KEY",
                "旧マスターキーの長さが不正です。",
                "旧版のキーを復元してください。",
            )
        })?;
        cipher
            .decrypt(Nonce::from_slice(nonce), ciphertext)
            .map(Zeroizing::new)
            .map_err(|_| {
                failure(
                    "E-SECRET-DECRYPT",
                    "旧認証情報を復号できません。",
                    "同じ利用者の旧DBと旧マスターキーを指定してください。",
                )
            })
    }

    #[cfg(test)]
    #[allow(clippy::unwrap_used)]
    pub(crate) fn encrypt_legacy_fixture(&self, plaintext: &[u8]) -> (Vec<u8>, Vec<u8>) {
        let nonce = vec![7u8; 12];
        let cipher = Aes256Gcm::new_from_slice(self.0.as_slice()).unwrap();
        (
            nonce.clone(),
            cipher
                .encrypt(Nonce::from_slice(&nonce), plaintext)
                .unwrap(),
        )
    }

    pub(crate) fn decrypt(
        &self,
        channel_id: &ChannelId,
        secret_type: &str,
        nonce: &[u8],
        ciphertext: &[u8],
    ) -> Result<Zeroizing<Vec<u8>>> {
        if nonce.len() != 12 {
            return Err(failure(
                "E-SECRET-DECRYPT",
                "認証情報の暗号形式が壊れています。",
                "バックアップから認証情報を復元してください。",
            ));
        }
        let cipher = Aes256Gcm::new_from_slice(self.0.as_slice()).map_err(|_| {
            failure(
                "E-SECRET-KEY",
                "暗号鍵が不正です。",
                "マスターキーを復元してください。",
            )
        })?;
        let aad = identity_aad(channel_id, secret_type);
        let plaintext = cipher
            .decrypt(
                Nonce::from_slice(nonce),
                Payload {
                    msg: ciphertext,
                    aad: &aad,
                },
            )
            .map_err(|_| {
                tracing::error!(
                    channel_id = channel_id.as_str(),
                    secret_type,
                    code = "E-SECRET-DECRYPT",
                    "認証情報の完全性検証に失敗しました"
                );
                failure(
                    "E-SECRET-DECRYPT",
                    "認証情報を復号できません。",
                    "元の利用者・マスターキー・バックアップを確認してください。",
                )
            })?;
        Ok(Zeroizing::new(plaintext))
    }
}

fn identity_aad(channel_id: &ChannelId, secret_type: &str) -> Vec<u8> {
    // 区切り文字で連結せず長さを含め、識別子の組合せが衝突しないようにする。
    let mut bytes = b"picocast-secret-v2".to_vec();
    bytes.extend_from_slice(&(channel_id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(channel_id.as_str().as_bytes());
    bytes.extend_from_slice(&(secret_type.len() as u64).to_be_bytes());
    bytes.extend_from_slice(secret_type.as_bytes());
    bytes
}

#[cfg(windows)]
fn protect(bytes: &[u8]) -> Result<Vec<u8>> {
    dpapi(bytes, false).map(|value| value.to_vec())
}

#[cfg(windows)]
fn unprotect(bytes: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    dpapi(bytes, true)
}

#[cfg(windows)]
fn dpapi(bytes: &[u8], decrypt: bool) -> Result<Zeroizing<Vec<u8>>> {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };

    let length = u32::try_from(bytes.len()).map_err(|_| {
        failure(
            "E-SECRET-KEY",
            "DPAPI データが大きすぎます。",
            "正しいマスターキーファイルを指定してください。",
        )
    })?;
    let input = CRYPT_INTEGER_BLOB {
        cbData: length,
        pbData: bytes.as_ptr().cast_mut(),
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // DPAPI が所有する出力領域はコピー後に消去し、必ず LocalFree で解放する。
    let succeeded = unsafe {
        if decrypt {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        }
    };
    if succeeded == 0 {
        tracing::error!(code = "E-SECRET-KEY", os_code = ?std::io::Error::last_os_error().raw_os_error(), "DPAPI 処理が失敗しました");
        return Err(failure(
            "E-SECRET-KEY",
            "Windows のキー保護に失敗しました。",
            "元の Windows 利用者で再実行してください。",
        ));
    }
    if output.pbData.is_null() {
        return Err(failure(
            "E-SECRET-KEY",
            "Windows のキー保護結果が不正です。",
            "元の Windows 利用者で再実行してください。",
        ));
    }
    let value = unsafe {
        let output_slice = std::slice::from_raw_parts_mut(output.pbData, output.cbData as usize);
        let value = Zeroizing::new(output_slice.to_vec());
        zeroize::Zeroize::zeroize(output_slice);
        LocalFree(output.pbData.cast());
        value
    };
    Ok(value)
}

#[cfg(not(windows))]
fn protect(_bytes: &[u8]) -> Result<Vec<u8>> {
    Err(failure(
        "E-SECRET-PLATFORM",
        "この OS のマスターキー保護は未実装です。",
        "現段階では Windows で認証情報を保存してください。",
    ))
}

#[cfg(not(windows))]
fn unprotect(_bytes: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    Err(failure(
        "E-SECRET-PLATFORM",
        "この OS のマスターキー復号は未実装です。",
        "現段階では元の Windows 利用者で開いてください。",
    ))
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn channel(value: &str) -> ChannelId {
        ChannelId::new(value).unwrap()
    }

    #[test]
    fn authentication_rejects_wrong_type_key_and_modified_payload() {
        let key = MasterKey::generate().unwrap();
        let other_key = MasterKey::generate().unwrap();
        let (nonce, mut encrypted) = key.encrypt(&channel("channel"), "api", b"sample").unwrap();
        assert!(key
            .decrypt(&channel("channel"), "token", &nonce, &encrypted)
            .is_err());
        assert!(other_key
            .decrypt(&channel("channel"), "api", &nonce, &encrypted)
            .is_err());
        encrypted[0] ^= 1;
        assert!(key
            .decrypt(&channel("channel"), "api", &nonce, &encrypted)
            .is_err());
        assert!(key
            .decrypt(&channel("channel"), "api", &[1], &encrypted)
            .is_err());
    }

    #[cfg(windows)]
    #[test]
    fn protected_key_roundtrip_and_existing_key_are_preserved() {
        let temporary = tempfile::tempdir().unwrap();
        let path = temporary.path().join("secret_master.key");
        let created = MasterKey::create(&path).unwrap();
        let loaded = MasterKey::load(&path).unwrap();
        let (nonce, encrypted) = created
            .encrypt(&channel("channel"), "api", b"sample")
            .unwrap();
        assert_eq!(
            loaded
                .decrypt(&channel("channel"), "api", &nonce, &encrypted)
                .unwrap()
                .as_slice(),
            b"sample"
        );
        let before = std::fs::read(&path).unwrap();
        assert!(MasterKey::create(&path).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), before);
    }

    #[test]
    fn legacy_cipher_matches_aes256_gcm_without_aad_and_rejects_damage() {
        let key = MasterKey(Zeroizing::new([0u8; 32]));
        // AES-256-GCMの公開既知値。旧PythonのAAD=Noneと同じ形式。
        let tag = [
            0x53, 0x0f, 0x8a, 0xfb, 0xc7, 0x45, 0x36, 0xb9, 0xa9, 0x63, 0xb4, 0xf1, 0xc4, 0xcb,
            0x73, 0x8b,
        ];
        assert!(key.decrypt_legacy(&[0u8; 12], &tag).unwrap().is_empty());
        let mut changed = tag;
        changed[0] ^= 1;
        assert!(key.decrypt_legacy(&[0u8; 12], &changed).is_err());
        assert!(key.decrypt_legacy(&[0u8; 11], &tag).is_err());
        assert!(key
            .decrypt(&channel("a"), "google_api_key", &[0u8; 12], &tag)
            .is_err());
    }
}
