@echo off
rem Same as build_dll.ps1 but plain batch, for shells without PowerShell.
rem vswhere lives under "Program Files (x86)" whose parens break for /f
rem when the path is quoted inside backquotes, so it goes on PATH and is
rem called bare instead.
setlocal
set "ROOT=%~dp0.."
set "PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer;%PATH%"

where vswhere >nul 2>&1
if errorlevel 1 (
  echo vswhere.exe not found. Install Build Tools for Visual Studio with the C++ workload.
  exit /b 1
)

set "VS="
for /f "usebackq delims=" %%i in (`vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i"
if "%VS%"=="" (
  echo vswhere found no MSVC toolset. Install the "Desktop development with C++" workload.
  exit /b 1
)

call "%VS%\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 (
  echo VsDevCmd.bat failed.
  exit /b 1
)

rem Intermediates go to %TEMP% so the repo root stays clean.
cl /nologo /LD /O2 /W4 /EHsc /DNDEBUG "%ROOT%\app-cs2\native\mouse_driver.c" ^
   /Fo"%TEMP%\mouse_driver.obj" ^
   /link /OUT:"%ROOT%\app-cs2\native\mouse_driver.dll" /IMPLIB:"%TEMP%\mouse_driver.lib" ^
   user32.lib winmm.lib
exit /b %ERRORLEVEL%
