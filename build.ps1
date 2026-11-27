# 一键构建 + 自签名
# 用法：在 PowerShell 里执行  .\build.ps1
# 说明：证书是一次性生成的（见 cert\automute-dev.cer，已导入本机受信任根/受信任发布者）。
#       每次重新构建都会覆盖 exe 的签名，所以必须重新签一次。

$ErrorActionPreference = 'Stop'
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $proj

$exe = Join-Path $proj 'dist\background_muter\background_muter.exe'

Write-Host '[1/3] PyInstaller 构建（带 requireAdministrator 清单）...'
& py -3 -m PyInstaller --noconfirm --clean -D -w --uac-admin `
    --add-data "$proj\resource;resource" `
    -i "$proj\resource\mute.ico" `
    -n background_muter `
    --distpath "$proj\dist" `
    --workpath "$proj\..\temp\automute-build-dir" `
    --specpath "$proj\..\temp\automute-spec-dir" `
    "$proj\main.py"

if (-not (Test-Path $exe)) { throw "构建失败，找不到 $exe" }

Write-Host '[2/3] 查找自签名证书...'
$cert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -like 'CN=AutoMuteBG Dev*' -and $_.HasPrivateKey } |
    Select-Object -First 1
if (-not $cert) { throw '找不到签名证书，请先创建（见 README 或 cert\automute-dev.cer）' }

Write-Host "[3/3] 签名 $exe"
Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256 | Out-Null

$sig = Get-AuthenticodeSignature -FilePath $exe
Write-Host "签名状态: $($sig.Status)  $($sig.StatusMessage)"
Write-Host "发布者  : $($sig.SignerCertificate.Subject)"
