@echo off
setlocal
pushd "%~dp0" || exit /b 1
call npm run release
set "BUILD_EXIT=%errorlevel%"
popd
exit /b %BUILD_EXIT%
