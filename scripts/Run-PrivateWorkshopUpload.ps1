param(
    [Parameter(Mandatory = $true)][string]$Stage,
    [string]$SteamLogin,
    [Parameter(Mandatory = $true)][ValidateSet('create', 'full', 'download')][string]$Phase
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$steamcmd = Join-Path $repo 'artifacts/steamcmd/steamcmd.exe'
if (-not (Test-Path -LiteralPath $steamcmd -PathType Leaf)) {
    throw 'Valve SteamCMD is not installed under artifacts/steamcmd.'
}
if ([string]::IsNullOrWhiteSpace($SteamLogin)) {
    $SteamLogin = Read-Host 'Steam login name (not a password)'
}
if ([string]::IsNullOrWhiteSpace($SteamLogin)) {
    throw 'A Steam login name is required. Never pass a password to this script.'
}
$stagePath = [IO.Path]::GetFullPath($Stage)
$vdfName = if ($Phase -eq 'create') { 'create.vdf' } else { 'full.vdf' }
$vdf = Join-Path $stagePath (Join-Path 'steamcmd-private' $vdfName)
if (-not (Test-Path -LiteralPath $vdf -PathType Leaf)) {
    throw "Private Workshop VDF is missing: $vdf"
}
$text = Get-Content -LiteralPath $vdf -Raw -Encoding UTF8
if ($text -notmatch '"appid"\s+"1611600"' -or $text -notmatch '"visibility"\s+"2"') {
    throw 'Refusing a VDF without WARNO app ID and private visibility.'
}
$ids = [regex]::Matches($text, '"publishedfileid"\s+"([0-9]+)"')
if ($ids.Count -ne 1 -or
    ($Phase -eq 'create' -and $ids[0].Groups[1].Value -ne '0') -or
    ($Phase -ne 'create' -and $ids[0].Groups[1].Value -eq '0')) {
    throw 'Refusing a VDF with the wrong item identity for this upload phase.'
}
$contentMatches = [regex]::Matches($text, '"contentfolder"\s+"([^"]+)"')
$previewMatches = [regex]::Matches($text, '"previewfile"\s+"([^"]+)"')
if ($contentMatches.Count -ne 1 -or $previewMatches.Count -ne 1) {
    throw 'Private Workshop VDF needs exactly one content folder and preview.'
}
$expectedContent = if ($Phase -eq 'create') {
    Join-Path $stagePath 'steamcmd-private/placeholder'
} else {
    Join-Path $stagePath 'steamcmd-private/complete-content'
}
$actualContent = [IO.Path]::GetFullPath($contentMatches[0].Groups[1].Value)
if (-not [string]::Equals($actualContent, [IO.Path]::GetFullPath($expectedContent),
    [StringComparison]::OrdinalIgnoreCase)) {
    throw 'VDF content folder does not match the verified private stage.'
}
$preview = [IO.Path]::GetFullPath($previewMatches[0].Groups[1].Value)
$expectedPreviewParent = [IO.Path]::GetFullPath((Join-Path $stagePath 'preview'))
if (-not [string]::Equals((Split-Path -Parent $preview), $expectedPreviewParent,
    [StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath $preview -PathType Leaf) -or
    (Get-Item -LiteralPath $preview).Length -ge 1MB) {
    throw 'Private Workshop preview is missing, too large or outside the stage.'
}
$files = @(Get-ChildItem -LiteralPath $expectedContent -Recurse -File -ErrorAction Stop)
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
if ($Phase -eq 'full' -and ($files.Count -lt 200 -or $bytes -gt 512MB) -or
    $Phase -eq 'create' -and ($files.Count -ne 1 -or $bytes -gt 1MB)) {
    throw "Private Workshop payload is unexpected: $($files.Count) files, $bytes bytes."
}
Write-Output "Verified private $Phase upload size: $($files.Count) files, $bytes bytes."
Write-Host "Starting Valve SteamCMD for private Workshop $Phase. Enter your password and Steam Guard code only in this local window."
Push-Location (Split-Path -Parent $steamcmd)
try {
    if ($Phase -eq 'download') {
        & $steamcmd '+login' $SteamLogin '+workshop_download_item' '1611600' $ids[0].Groups[1].Value '+quit'
    }
    else {
        & $steamcmd '+login' $SteamLogin '+workshop_build_item' $vdf '+quit'
    }
    $exitCode = $LASTEXITCODE
}
finally { Pop-Location }
Write-Output "SteamCMD exit code: $exitCode"
if ($exitCode -ne 0) {
    throw 'SteamCMD did not complete the private Workshop phase. Inspect its own Workshop_log.txt.'
}
