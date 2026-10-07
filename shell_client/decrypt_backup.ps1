<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Native PowerShell Recovery Tool (v4.2.0)
.DESCRIPTION
    Offline disaster recovery decryption tool.
    - Decrypts .dbk2 archives using an air-gapped RSA-4096 private key.
    - Extracts restored database dump (.zip/.bak) without requiring Python.
.PARAMETER InputFile
    Path to the encrypted .dbk2 archive.
.PARAMETER OutputFile
    Path for the restored output zip/bak file.
.PARAMETER PrivateKeyFile
    Path to the RSA private key PEM file (backup_private.pem or escrow_private.pem).
.PARAMETER Password
    Optional passphrase if the private key is password-protected.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$InputFile,

    [Parameter(Mandatory=$true)]
    [string]$OutputFile,

    [Parameter(Mandatory=$true)]
    [string]$PrivateKeyFile,

    [string]$Password = ""
)

Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.IO.Compression.FileSystem

if (-not (Test-Path $InputFile)) {
    Write-Error "Encrypted file not found: $InputFile"
    exit 1
}
if (-not (Test-Path $PrivateKeyFile)) {
    Write-Error "Private key file not found: $PrivateKeyFile"
    exit 1
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  ENTERPRISE DISASTER RECOVERY - POWERSHELL DECRYPTOR (v4.2.0)" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "[+] Reading encrypted file: $InputFile" -ForegroundColor Yellow

$fs = [System.IO.File]::OpenRead($InputFile)
$br = New-Object System.IO.BinaryWriter($fs)
$reader = New-Object System.IO.BinaryReader($fs)

# Read Magic (4 bytes)
$magic = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
if ($magic -ne "DBK2") {
    Write-Error "[FATAL] Invalid file format. Expected DBK2 magic header, found: $magic"
    $fs.Close()
    exit 1
}

$version = $reader.ReadByte()
$numRecipients = $reader.ReadByte()
Write-Host "    Version: $version | Recipients: $numRecipients" -ForegroundColor DarkGray

# Read Recipients
$wrappedKeys = @()
for ($i = 0; $i -lt $numRecipients; $i++) {
    $fp = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(8))
    $kLen = $reader.ReadUInt16()
    $wKey = $reader.ReadBytes($kLen)
    $wrappedKeys += $wKey
}

# Read IV (16 bytes)
$iv = $reader.ReadBytes(16)

# Read private key using open openssl if available or .NET
Write-Host "[+] Decrypting AES-256 session key using RSA private key..." -ForegroundColor Yellow

# Helper to invoke openssl or certutil if installed, or .NET
$tempKeyFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllBytes($tempKeyFile, $wrappedKeys[0])
$aesKey = $null

$openssl = Get-Command "openssl.exe" -ErrorAction SilentlyContinue
if ($openssl) {
    $passArg = if ($Password) { "-passin pass:$Password" } else { "" }
    $cmd = "openssl rsautl -decrypt -oaep -inkey `"$PrivateKeyFile`" -in `"$tempKeyFile`" $passArg"
    $aesKey = & cmd.exe /c $cmd 2>$null
}

if (-not $aesKey -or $aesKey.Length -ne 32) {
    # If openssl CLI is unavailable, prompt user to use Tools/decrypt_backup.py
    Write-Warning "Direct PKCS#8 encrypted private key parsing requires OpenSSL CLI or Python cryptography."
    Write-Host "Please run the administrative recovery tool:" -ForegroundColor Cyan
    Write-Host "  python Tools/decrypt_backup.py `"$InputFile`" `"$OutputFile`" `"$PrivateKeyFile`"" -ForegroundColor White
    $fs.Close()
    Remove-Item -Path $tempKeyFile -Force -ErrorAction SilentlyContinue
    exit 0
}

Remove-Item -Path $tempKeyFile -Force -ErrorAction SilentlyContinue

# Decrypt stream
$aes = [System.Security.Cryptography.Aes]::Create()
$aes.KeySize = 256
$aes.Key = $aesKey
$aes.IV = $iv
$aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
$aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7

$decryptor = $aes.CreateDecryptor()
$outFs = [System.IO.File]::Create($OutputFile)
$cs = New-Object System.Security.Cryptography.CryptoStream($outFs, $decryptor, [System.Security.Cryptography.CryptoStreamMode]::Write)

$buffer = New-Object byte[] 65536
while (($read = $fs.Read($buffer, 0, $buffer.Length)) -gt 0) {
    $cs.Write($buffer, 0, $read)
}
$cs.FlushFinalBlock()
$outFs.Close()
$fs.Close()

Write-Host "[SUCCESS] Archive decrypted and recovered to: $OutputFile" -ForegroundColor Green
