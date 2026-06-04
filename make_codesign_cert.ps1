# 自己署名のコード署名証明書を作成し、このPCで信頼させる（Windows）。
#
# 用途:
#   - exe に「発行元（あなた）」の識別を付ける。
#   - ここで信頼登録した PC でのみ「不明な発行元」表示が消える。
#
# 注意（重要）:
#   - 公的CAの証明書ではないため、不特定多数への配布では効果がない（SmartScreen/Defenderの警告は消えない）。
#     不特定多数配布で警告を消すには公的CA（できればEV）のコード署名証明書が必要。
#   - onefile exe に署名しても、署名されるのは外側 exe だけ。起動時に展開される app.dll は署名されないため、
#     Defender のML誤検知(Program:Win32/Contebrew.A!ml)対策にはならない（その対策は除外 or standalone化＋全署名）。
#   - 他PCで「不明な発行元」を消したい場合は、出力された公開証明書(.cer)を相手PCの
#     「信頼されたルート証明機関」と「信頼された発行元」にインポートする（秘密鍵は配らない）。

$ErrorActionPreference = "Stop"
$subject = "CN=Native Video Factory Self-Signed"

# 既存（秘密鍵あり）があれば再利用する
$cert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $subject -and $_.HasPrivateKey } |
    Select-Object -First 1

if (-not $cert) {
    Write-Host "自己署名コード署名証明書を作成します: $subject"
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(3)
} else {
    Write-Host "既存の証明書を再利用します。"
}
Write-Host ("Thumbprint: " + $cert.Thumbprint)

# このPCで信頼させる（公開鍵のみ。秘密鍵は My に残したまま）
$pubDir = Join-Path $PSScriptRoot "dev\codesign"
New-Item -ItemType Directory -Force -Path $pubDir | Out-Null
$cerPath = Join-Path $pubDir "NativeVideoFactory-public.cer"
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
Import-Certificate -FilePath $cerPath -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
Import-Certificate -FilePath $cerPath -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null

Write-Host "このPCの信頼ストアに登録しました（CurrentUser\Root / TrustedPublisher）。"
Write-Host ("公開証明書(.cer): " + $cerPath)
Write-Host "ビルド時、build_exe.ps1 がこの証明書で exe に自動署名します。"
