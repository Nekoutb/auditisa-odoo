@echo off
rem Make my signing key: AuditISA. Double-click, once, as a new signer. Runs make-my-signing-key.sh (beside this file) in Git for Windows.
rem It makes YOUR OWN passphrase-locked key in the auditisa-signing folder of your user profile, never overwriting one.
setlocal
set "HERE=%~dp0"
set "SCRIPT=%HERE%make-my-signing-key.sh"
set "TITLE=Make my signing key"
if not exist "%SCRIPT%" (
  echo.
  echo  The file make-my-signing-key.sh must stay in the same folder as this one.
  echo  Le fichier make-my-signing-key.sh doit rester dans le meme dossier que celui-ci.
  echo.
  pause
  exit /b 1
)
call :findgit
if not defined GITDIR goto nogit
if exist "%GITDIR%\usr\bin\mintty.exe" (
  start "" "%GITDIR%\usr\bin\mintty.exe" -t "%TITLE%" -s 110,44 -o Charset=UTF-8 "%GITDIR%\bin\bash.exe" -l "%SCRIPT%" %*
) else (
  "%GITDIR%\bin\bash.exe" -l "%SCRIPT%" %*
)
exit /b 0

:findgit
set "GITDIR="
for %%G in ("%ProgramFiles%\Git" "%ProgramW6432%\Git" "%ProgramFiles(x86)%\Git" "%LOCALAPPDATA%\Programs\Git") do (
  if not defined GITDIR if exist "%%~G\bin\bash.exe" set "GITDIR=%%~G"
)
if defined GITDIR exit /b 0
for /f "delims=" %%P in ('where git.exe 2^>nul') do (
  if not defined GITDIR if exist "%%~dpP..\bin\bash.exe" set "GITDIR=%%~dpP.."
)
exit /b 0

:nogit
echo.
echo  Git for Windows is not installed on this computer.
echo  Install Git for Windows from git-scm.com, then try again.
echo.
echo  Git pour Windows n'est pas installe sur cet ordinateur.
echo  Installez Git pour Windows depuis git-scm.com, puis recommencez.
echo.
pause
exit /b 1
