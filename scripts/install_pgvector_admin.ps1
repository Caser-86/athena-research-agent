# 一键提权：安装 pgvector 到本地 PostgreSQL 16 并启用扩展
# 由 Start-Process -Verb RunAs 以管理员身份运行
$ErrorActionPreference = "Stop"
$log = "C:\Users\MR\AppData\Local\Temp\pgvector_install.log"
Start-Transcript -Path $log -Force | Out-Null

$src = "C:\Users\MR\AppData\Local\Temp\pgvector_pg16\pgvector-x86_64-pc-windows-msvc-pg16"
$pgRoot = "D:\Program Files\PostgreSQL"
$pgBin  = "$pgRoot\bin"
$pgLib  = "$pgRoot\lib"
$pgShare= "$pgRoot\share\extension"

Write-Output "[1/4] 拷贝 vector.dll -> lib"
Copy-Item "$src\lib\vector.dll" "$pgLib\" -Force

Write-Output "[2/4] 拷贝 vector.sql/.control -> share\extension"
if (-not (Test-Path $pgShare)) { New-Item -ItemType Directory -Path $pgShare -Force | Out-Null }
Copy-Item "$src\share\extension\vector*" "$pgShare\" -Force

Write-Output "[3/4] 重启 PostgreSQL 服务 postgresql-x64-16"
Restart-Service -Name "postgresql-x64-16" -Force
Start-Sleep -Seconds 5
$svc = Get-Service -Name "postgresql-x64-16"
Write-Output ("服务状态: " + $svc.Status)
if ($svc.Status -ne "Running") { throw "PostgreSQL 服务未运行" }

Write-Output "[4/4] 创建 vector 扩展并验证"
$env:PGPASSWORD = "920220"
& "$pgBin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;" | Out-Host
& "$pgBin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -t -c "SELECT extversion FROM pg_extension WHERE extname='vector';" | Out-Host
& "$pgBin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -t -c "SELECT '[1,2,3]'::vector <-> '[1,2,4]' AS dist;" | Out-Host

Stop-Transcript | Out-Null
Write-Output "PGVECTOR_INSTALL_DONE"