[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Write-Host 'Learn With Stories - user-owned OpenAI key pool' -ForegroundColor Cyan
$count = [int](Read-Host 'How many keys do you own and want to configure? (1-50)')
if ($count -lt 1 -or $count -gt 50) { throw 'Enter a number from 1 to 50.' }
$keys = [System.Collections.Generic.List[string]]::new()
for ($index = 1; $index -le $count; $index++) {
    $secure = Read-Host "Paste key $index" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim().Trim([char]34, [char]39)
        if ($key -cnotmatch '^sk-[A-Za-z0-9_-]+$') { throw "Key $index contains invalid or altered characters." }
        if (-not $keys.Contains($key)) { $keys.Add($key) }
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
}
$joined = $keys -join ';'
[Environment]::SetEnvironmentVariable('OPENAI_API_KEYS', $joined, 'User')
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $null, 'User')
$secretDirectory = Join-Path $PSScriptRoot 'secrets'
$secretFile = Join-Path $secretDirectory 'openai_api_keys.txt'
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
[IO.File]::WriteAllLines($secretFile, $keys, [Text.UTF8Encoding]::new($false))
icacls.exe $secretFile /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
Write-Host "$($keys.Count) key(s) saved. Their values will never appear in the UI." -ForegroundColor Green
Write-Host 'Restart the native application or run: docker compose up -d --build' -ForegroundColor Green
