param(
    [string]$Root = "."
)

$ErrorActionPreference = "Stop"

$patterns = @(
    @{ Name = "OCI OCID"; Pattern = "ocid1\." },
    @{ Name = "PEM material"; Pattern = "-----BEGIN" },
    @{ Name = "Fingerprint assignment"; Pattern = "fingerprint\s*=" },
    @{ Name = "Key file assignment"; Pattern = "key_file\s*=" },
    @{ Name = "Session token"; Pattern = "session[_-]?token" },
    @{ Name = "SSH key reference"; Pattern = "ssh-key" },
    @{ Name = "Personal Windows path"; Pattern = "C:\\Users\\" },
    @{ Name = "Email address"; Pattern = "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" },
    @{ Name = "Public IPv4 address"; Pattern = "\b(?!(?:10|127|169\.254|172\.(?:1[6-9]|2[0-9]|3[0-1])|192\.168)\.)((?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-5])\.){3}(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-5])\b" }
)

$excludedPathParts = @(
    "\.git\",
    "\__pycache__\",
    "\.pytest_cache\",
    "\.venv\",
    "\venv\",
    "\docs\screenshots\"
)

$rootPath = (Resolve-Path $Root).Path
$findings = @()

Get-ChildItem -Path $rootPath -Recurse -File | ForEach-Object {
    $path = $_.FullName
    if ($_.Name -in @("check-secrets.ps1", "check-secrets.sh", "github-publication-checklist.md")) {
        return
    }
    foreach ($part in $excludedPathParts) {
        if ($path -like "*$part*") {
            return
        }
    }
    if ($_.Extension -in @(".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".ico")) {
        return
    }

    $content = Get-Content -Raw -LiteralPath $path
    foreach ($item in $patterns) {
        if ($content -match $item.Pattern) {
            $relative = $path.Substring($rootPath.Length).TrimStart("\", "/")
            $findings += [pscustomobject]@{
                File = $relative
                Finding = $item.Name
            }
        }
    }
}

if ($findings.Count -gt 0) {
    Write-Host "Potential secrets or environment-specific values found:" -ForegroundColor Red
    $findings | Sort-Object File, Finding | Format-Table -AutoSize
    exit 1
}

Write-Host "Secret scan passed." -ForegroundColor Green
