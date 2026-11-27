[CmdletBinding()]
param([string]$UERoot='D:\UE_4.26',[string]$GameRoot='D:\Sifu',[switch]$Install)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$out=Join-Path $root 'build\execution-domain'
$editor=Join-Path $UERoot 'Engine\Binaries\Win64\UE4Editor-Cmd.exe'
$project=Join-Path $PSScriptRoot 'ue\Sifu.uproject'
$source=Join-Path $PSScriptRoot 'SifuExecutionDomain'
New-Item -ItemType Directory -Force $out | Out-Null
& gcc -shared -O2 -Wall -Wextra -Werror -Wno-cast-function-type (Join-Path $PSScriptRoot 'ExecutionBridge.c') -o (Join-Path $source 'Scripts\ExecutionBridge.dll')
if($LASTEXITCODE -ne 0){throw 'Native bridge build failed'}
& $editor $project -run=pythonscript "-script=$PSScriptRoot\build_effects.py" -unattended -nop4 -nosplash -nullrhi -stdout -FullStdOutLogOutput *> (Join-Path $out 'effects-editor.log')
if($LASTEXITCODE -ne 0){throw 'Effects authoring failed'}
$report=Get-Content -LiteralPath (Join-Path $out 'effects-build.json') -Raw | ConvertFrom-Json
if(!$report.ok){throw $report.error}
& $editor $project -run=cook -targetplatform=WindowsNoEditor "-cookdir=$PSScriptRoot\ue\Content\ExecutionDomain" -unattended -nop4 -nosplash -stdout -FullStdOutLogOutput *> (Join-Path $out 'effects-cook.log')
if($LASTEXITCODE -ne 0){throw 'Effects cooking failed'}
$cooked=Join-Path $PSScriptRoot 'ue\Saved\Cooked\WindowsNoEditor\Sifu\Content\ExecutionDomain'
$stage=Join-Path $out ('stage-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force (Join-Path $stage 'ExecutionDomain') | Out-Null
Copy-Item -LiteralPath $cooked -Destination $stage -Recurse -Force
$package=Join-Path $out 'package'
$paks=Join-Path $package 'Content\Paks\~mods'
$mods=Join-Path $package 'Binaries\Win64\ue4ss\Mods'
New-Item -ItemType Directory -Force $paks,$mods | Out-Null
$pak=Join-Path $paks 'pakchunk98-ExecutionDomain_P.pak'
& (Join-Path $root 'tools\repak\repak.exe') pack $stage $pak --mount-point '../../../Sifu/Content/' --version V11 --compression Zlib
if($LASTEXITCODE -ne 0){throw 'Pak build failed'}
$entries=& (Join-Path $root 'tools\repak\repak.exe') list $pak
if($LASTEXITCODE -ne 0 -or @($entries).Count -lt 10 -or ($entries | Where-Object {$_ -notmatch '^Sifu/Content/ExecutionDomain/'})){throw 'Unexpected pak entries'}
$entries | Set-Content -LiteralPath (Join-Path $out 'pak-contents.txt')
Copy-Item -LiteralPath (Join-Path $GameRoot 'Sifu\Content\Paks\pakchunk0-WindowsNoEditor.sig') -Destination ([IO.Path]::ChangeExtension($pak,'.sig'))
Copy-Item -LiteralPath $source -Destination $mods -Recurse -Force
if(Test-Path -LiteralPath (Join-Path $PSScriptRoot '安装说明.md')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot '安装说明.md') -Destination $package}
Compress-Archive -Path (Join-Path $package '*') -DestinationPath (Join-Path $out 'Sifu-ExecutionDomain-Epic-6770.zip') -Force
if($Install){
    if(Get-Process 'Sifu-Win64-Shipping' -ErrorAction SilentlyContinue){throw 'Exit Sifu before installing'}
    $backup=Join-Path $out ('backups\'+(Get-Date -Format yyyyMMdd-HHmmss))
    $installed=Join-Path $GameRoot 'Sifu\Binaries\Win64\ue4ss\Mods\SifuExecutionDomain'
    New-Item -ItemType Directory -Force $backup | Out-Null
    if(Test-Path -LiteralPath $installed){Copy-Item -LiteralPath $installed -Destination $backup -Recurse}
    Copy-Item -LiteralPath (Join-Path $mods 'SifuExecutionDomain') -Destination (Split-Path -Parent $installed) -Recurse -Force
    Get-ChildItem -LiteralPath $paks -File | Copy-Item -Destination (Join-Path $GameRoot 'Sifu\Content\Paks\~mods') -Force
}
Get-Item -LiteralPath (Join-Path $out 'Sifu-ExecutionDomain-Epic-6770.zip')
