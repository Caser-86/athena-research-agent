@echo off
REM ============================================================
REM pgvector v0.8.0 for PostgreSQL 16 - 一键安装脚本
REM 用法：右键本文件 -> 以管理员身份运行 -> UAC 点"是"
REM 自动：拷贝 DLL+SQL -> 重启 PG 服务 -> 创建 vector 扩展 -> 验证
REM ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion

echo [+] 检查管理员权限...
net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo     当前非管理员，重新以管理员启动...
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
    exit /b
)
echo [OK] 已获得管理员权限。

set PKGBASE=%TEMP%\pgvector_pg16
set PGROOT=D:\Program Files\PostgreSQL

if not exist "%PKGBASE%\pgvector-x86_64-pc-windows-msvc-pg16\lib\vector.dll" (
    echo [-] 未找到已解压的 pgvector 包，尝试重新下载...
    powershell -NoProfile -Command "Set-Location $env:TEMP; if (Test-Path 'pgvector_pg16.zip') { Remove-Item -Force 'pgvector_pg16.zip' }; Invoke-WebRequest -Uri 'https://github.com/portalcorp/pgvector_compiled/releases/download/v0.16.105/pgvector-x86_64-pc-windows-msvc-pg16.zip' -OutFile 'pgvector_pg16.zip'"
    if errorlevel 1 (
        echo [-] 下载失败,请检查网络。日志见 %TEMP%\pgvector_install.log
        pause
        exit /b 1
    )
    powershell -NoProfile -Command "Expand-Archive -Path \"$env:TEMP\pgvector_pg16.zip\" -DestinationPath \"$env:TEMP\pgvector_pg16\" -Force"
)

set SRC=%PKGBASE%\pgvector-x86_64-pc-windows-msvc-pg16

echo [+] [1/4] 拷贝 vector.dll -> lib
copy /Y "%SRC%\lib\vector.dll" "%PGROOT%\lib\" >nul
if errorlevel 1 (
    echo [-] 拷贝失败,请确认 D:\Program Files\PostgreSQL 存在且有写权限
    pause
    exit /b 1
)
echo [OK] vector.dll 已就位。

echo [+] [2/4] 拷贝 vector SQL/control -> share\extension
if not exist "%PGROOT%\share\extension" mkdir "%PGROOT%\share\extension"
copy /Y "%SRC%\share\extension\vector*" "%PGROOT%\share\extension\" >nul
if errorlevel 1 (
    echo [-] SQL/control 拷贝失败
    pause
    exit /b 1
)
echo [OK] SQL 与 control 已就位。

echo [+] [3/4] 重启 PostgreSQL 服务 postgresql-x64-16 ...
net stop postgresql-x64-16 >nul 2>&1
net start postgresql-x64-16 >nul
if errorlevel 1 (
    echo [-] 服务启动失败,请检查服务状态
    pause
    exit /b 1
)
echo [OK] 服务已重启。

echo [+] [4/4] 创建 vector 扩展并验证...
set PGPASSWORD=920220
"%PGROOT%\bin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
if errorlevel 1 (
    echo [-] 创建 vector 扩展失败，请检查 psql 输出
    pause
    exit /b 1
)
echo --- 扩展版本 ---
"%PGROOT%\bin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -t -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
echo --- 向量距离自检 ----------
"%PGROOT%\bin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -t -c "SELECT '[1,2,3]'::vector <-> '[1,2,4]';"

echo.
echo ==========================================
echo  PGVECTOR_INSTALL_DONE  - 安装完成!
echo ==========================================
pause