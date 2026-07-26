#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$PythonExecutable
)

$ErrorActionPreference = 'Stop'

$offlineRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repositoryRoot = (Resolve-Path (Join-Path $offlineRoot '..\..')).Path
$sourceDirectory = Join-Path $offlineRoot 'source'
$rawDirectory = Join-Path $offlineRoot 'work\raw'
$lockPath = Join-Path $offlineRoot 'metadata\source-lock.json'

if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $repositoryRoot `
        '.venv-weather-data\Scripts\python.exe'
}

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "找不到 Python：$PythonExecutable"
}

New-Item -ItemType Directory -Force -Path $sourceDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $rawDirectory | Out-Null

$sourceLock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 |
    ConvertFrom-Json

function Get-LowerSha256 {
    param([Parameter(Mandatory)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).
        Hash.ToLowerInvariant()
}

foreach ($archive in $sourceLock.archives) {
    $archivePath = Join-Path $sourceDirectory $archive.name
    $downloadRequired = $true

    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        $actualHash = Get-LowerSha256 -Path $archivePath
        $downloadRequired = $actualHash -ne $archive.sha256
    }

    if ($downloadRequired) {
        $temporaryPath = "$archivePath.download"
        try {
            Invoke-WebRequest -Uri $archive.url -OutFile $temporaryPath
            $downloadHash = Get-LowerSha256 -Path $temporaryPath
            if ($downloadHash -ne $archive.sha256) {
                throw (
                    "下载文件 SHA-256 不匹配：{0}`n预期：{1}`n实际：{2}" -f
                    $archive.name,
                    $archive.sha256,
                    $downloadHash
                )
            }
            Move-Item -LiteralPath $temporaryPath -Destination $archivePath `
                -Force
        }
        finally {
            if (Test-Path -LiteralPath $temporaryPath) {
                Remove-Item -LiteralPath $temporaryPath -Force
            }
        }
    }

    $actualBytes = (Get-Item -LiteralPath $archivePath).Length
    if ($actualBytes -ne $archive.bytes) {
        throw (
            "压缩包大小不匹配：{0}，预期 {1}，实际 {2}" -f
            $archive.name,
            $archive.bytes,
            $actualBytes
        )
    }

    $memberPath = Join-Path $rawDirectory $archive.usedMember
    $extractRequired = $true
    if (Test-Path -LiteralPath $memberPath -PathType Leaf) {
        $memberHash = Get-LowerSha256 -Path $memberPath
        $extractRequired = $memberHash -ne $archive.usedMemberSha256
    }

    if ($extractRequired) {
        if (Test-Path -LiteralPath $memberPath) {
            Remove-Item -LiteralPath $memberPath -Force
        }
        & $PythonExecutable -m py7zr x $archivePath $rawDirectory `
            --files $archive.usedMember
        if ($LASTEXITCODE -ne 0) {
            throw "解压失败：$($archive.usedMember)"
        }
    }

    $memberBytes = (Get-Item -LiteralPath $memberPath).Length
    $memberHash = Get-LowerSha256 -Path $memberPath
    if (
        $memberBytes -ne $archive.usedMemberBytes -or
        $memberHash -ne $archive.usedMemberSha256
    ) {
        throw "解压成员校验失败：$($archive.usedMember)"
    }

    Write-Host (
        "已就绪：{0} ({1:N0} bytes, sha256={2})" -f
        $archive.usedMember,
        $memberBytes,
        $memberHash
    )
}

Write-Host "AreaCity 离线源数据准备完成：$rawDirectory"
