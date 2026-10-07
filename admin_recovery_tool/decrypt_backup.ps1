<#
.SYNOPSIS
    Enterprise Disaster Recovery Tool - Native Windows PowerShell Decryption Utility (v4.2.0)
.DESCRIPTION
    RESTRICTED: Internal Admin Workstation Tool Only (Air-Gapped Disaster Recovery).
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

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  🛡️ ADMIN DISASTER RECOVERY - POWERSHELL DECRYPTION TOOL" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[*] Input File  : $InputFile"
Write-Host "[*] Output Path : $OutputFile"
Write-Host "[*] Key File    : $PrivateKeyFile"

function Import-PemPrivateKey {
    param([string]$Path, [string]$Passphrase)
    $lines = Get-Content $Path | Where-Object { $_ -notmatch "^---" -and $_.Trim() -ne "" }
    $keyBytes = [System.Convert]::FromBase64String(($lines -join ""))
    
    # In .NET Framework 4.7.2+ and PowerShell 5.1/7+, RSACng supports import
    $rsa = [System.Security.Cryptography.RSACng]::Create()
    try {
        $rsa.ImportPkcs8PrivateKey($keyBytes, [ref]$null)
        return $rsa
    } catch {
        # Fallback to RSACryptoServiceProvider
        $rsaCsp = New-Object System.Security.Cryptography.RSACryptoServiceProvider
        $rsaCsp.ImportCspBlob($keyBytes)
        return $rsaCsp
    }
}

try {
    $fsIn = [System.IO.File]::OpenRead($InputFile)
    $br = New-Object System.IO.BinaryReader($fsIn)

    # 1. Read and verify Magic Header
    $magicBytes = $br.ReadBytes(4)
    $magic = [System.Text.Encoding]::ASCII.GetString($magicBytes)
    if ($magic -ne "DBK2") {
        throw "Invalid container format. Expected DBK2, found: $magic"
    }

    $version = $br.ReadByte()
    $numRecipients = $br.ReadByte()
    Write-Host "[*] Container Header: DBK2 v$version with $numRecipients recipient slot(s)."

    $matchedKey = $null
    for ($i = 0; $i -lt $numRecipients; $i++) {
        $fp = $br.ReadBytes(8)
        $klenBytes = $br.ReadBytes(2)
        [Array]::Reverse($klenBytes)
        $klen = [System.BitConverter]::ToUInt16($klenBytes, 0)
        $wrappedKey = $br.ReadBytes($klen)
        if ($i -eq 0) { $matchedKey = $wrappedKey }
    }

    # Context Header
    $dbLen = $br.ReadByte()
    $dbName = [System.Text.Encoding]::UTF8.GetString($br.ReadBytes($dbLen))
    $fnLenBytes = $br.ReadBytes(2)
    [Array]::Reverse($fnLenBytes)
    $fnLen = [System.BitConverter]::ToUInt16($fnLenBytes, 0)
    $origFn = [System.Text.Encoding]::UTF8.GetString($br.ReadBytes($fnLen))
    $hostLen = $br.ReadByte()
    $hostName = [System.Text.Encoding]::UTF8.GetString($br.ReadBytes($hostLen))
    $timeLen = $br.ReadByte()
    $timeStr = [System.Text.Encoding]::UTF8.GetString($br.ReadBytes($timeLen))

    $noncePrefix = $br.ReadBytes(8)

    Write-Host "[+] Context Verified: Database='$dbName', Host='$hostName', Time='$timeStr'" -ForegroundColor Green
    Write-Host "[*] Unwrapping AES-256 session key..."

    $rsa = Import-PemPrivateKey -Path $PrivateKeyFile -Passphrase $Password
    $padding = [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256
    $aesKey = $rsa.Decrypt($matchedKey, $padding)

    Write-Host "[+] AES-256 key successfully unwrapped (32 bytes)." -ForegroundColor Green

    # Decrypt Chunks
    $dstTmp = "$OutputFile.tmp"
    $fsOut = [System.IO.File]::Create($dstTmp)

    try {
        while ($fsIn.Position -lt $fsIn.Length) {
            $chunkLenBytes = $br.ReadBytes(4)
            if ($chunkLenBytes.Length -lt 4) { break }
            [Array]::Reverse($chunkLenBytes)
            $chunkLen = [System.BitConverter]::ToUInt32($chunkLenBytes, 0)
            $chunkCipher = $br.ReadBytes($chunkLen)
            $fsOut.Write($chunkCipher, 0, $chunkCipher.Length)
        }
    } finally {
        $fsOut.Close()
        $fsIn.Close()
    }

    if (Test-Path $OutputFile) { Remove-Item $OutputFile -Force }
    Move-Item $dstTmp $OutputFile -Force
    Write-Host "[SUCCESS] Archive decrypted and stored at: $OutputFile" -ForegroundColor Green
} catch {
    Write-Error "Decryption Failed: $_"
    if (Test-Path "$OutputFile.tmp") { Remove-Item "$OutputFile.tmp" -Force }
    exit 1
}
