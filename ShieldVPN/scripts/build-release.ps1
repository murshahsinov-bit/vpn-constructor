# One-shot release build for ShieldVPN (Windows PowerShell).
# Produces app\build\outputs\apk\playstore\release\ShieldVPN_<version>_universal.apk
$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir

& (Join-Path $PSScriptRoot "fetch-libs.ps1")

if (-not $env:JAVA_HOME) {
    Write-Host ""
    Write-Host "JAVA_HOME is not set. Install JDK 21 and set JAVA_HOME first:" -ForegroundColor Yellow
    Write-Host '  setx JAVA_HOME "C:\Program Files\Eclipse Adoptium\jdk-21"' -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $projectDir "local.properties"))) {
    if (-not $env:ANDROID_HOME -and -not $env:ANDROID_SDK_ROOT) {
        Write-Host ""
        Write-Host "Android SDK not found. Set ANDROID_HOME or create local.properties with sdk.dir=..." -ForegroundColor Yellow
    }
}

& (Join-Path $projectDir "gradlew.bat") --no-daemon assemblePlaystoreRelease
if ($LASTEXITCODE -ne 0) { throw "Gradle build failed" }

Get-ChildItem (Join-Path $projectDir "app\build\outputs\apk\playstore\release") -Filter *.apk |
    Select-Object FullName, Length
