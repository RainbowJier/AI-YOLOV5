# Builds app-cs2/native/mouse_driver.dll with the MSVC Build Tools.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_dll.ps1
#
# No Visual Studio install needed beyond "Build Tools for Visual Studio"
# with the C++ workload and a Windows 10/11 SDK. vswhere finds the
# toolchain; the SDK include/lib paths come from the current environment
# after VsDevCmd, so this does not hardcode SDK versions.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root 'app-cs2\native\mouse_driver.c'
$out = Join-Path $root 'app-cs2\native\mouse_driver.dll'

if (-not (Test-Path $src)) { throw "source not found: $src" }

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found. Install 'Build Tools for Visual Studio' with the C++ workload."
}

$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "no MSVC C++ toolset found (Build Tools > Desktop development with C++)" }

$devCmd = Join-Path $vsPath 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path $devCmd)) { throw "VsDevCmd.bat not found under $vsPath" }

# Run cl inside a cmd that has the MSVC + SDK environment loaded.
# Intermediates go to $env:TEMP so the repo root stays clean.
$obj = Join-Path $env:TEMP 'mouse_driver.obj'
$implib = Join-Path $env:TEMP 'mouse_driver.lib'
$cl = 'cl /nologo /LD /O2 /W4 /EHsc /DNDEBUG ' + ('"{0}"' -f $src) +
      ' /Fo"' + $obj + '"' +
      ' /link /OUT:"' + $out + '" /IMPLIB:"' + $implib + '"' +
      ' user32.lib winmm.lib'
$cmd = 'call "{0}" -arch=x64 -host_arch=x64 >nul && {1}' -f $devCmd, $cl

Write-Host "Building $out ..."
cmd /c $cmd
if ($LASTEXITCODE -ne 0) { throw "cl failed with exit code $LASTEXITCODE" }
if (-not (Test-Path $out)) { throw "compiler reported success but $out is missing" }

$size = (Get-Item $out).Length
Write-Host ""
Write-Host ("Done: {0} ({1:N0} bytes)" -f $out, $size)
Write-Host "Then set mouse_driver = `"dll`" in app-cs2/config.py"
