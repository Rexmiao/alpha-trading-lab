param([Parameter(Mandatory=$true)][string]$RuntimeDir)
$ErrorActionPreference = 'Stop'
$alphaRuntime = [System.IO.Path]::GetFullPath($RuntimeDir)
if (-not [System.IO.Path]::IsPathRooted($RuntimeDir) -or $alphaRuntime -match '(?i)[\\/](Dropbox|OneDrive)[\\/]') {
    throw 'Choose an absolute local runtime directory outside Dropbox and OneDrive.'
}
New-Item -ItemType Directory -Path $alphaRuntime -Force | Out-Null
$alphaCredentialPath = Join-Path $alphaRuntime 'hf-snapshot-write-token.dpapi'
Write-Host 'Use a Hugging Face token with Write permission ONLY for the PRIVATE dataset Rexymiao/alpha-trading-snapshots.'
Write-Host 'Do not paste a broker key or the GitHub/HF deployment token here.'
$alphaSecureToken = Read-Host 'Dataset write token (hidden)' -AsSecureString
if ($alphaSecureToken.Length -lt 20) { throw 'No usable token was entered.' }
$alphaProtectedToken = ConvertFrom-SecureString -SecureString $alphaSecureToken
[System.IO.File]::WriteAllText($alphaCredentialPath, $alphaProtectedToken, [System.Text.UTF8Encoding]::new($false))
$env:ALPHA_SNAPSHOT_TOKEN_DPAPI = $alphaCredentialPath
Write-Host 'Encrypted token saved for this Windows user; the plaintext was not printed.'
Write-Host ('This PowerShell session is configured. On a later run set ALPHA_SNAPSHOT_TOKEN_DPAPI to: ' + $alphaCredentialPath)
