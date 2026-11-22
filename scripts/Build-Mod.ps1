[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$UERoot,
    [string]$GameRoot = 'D:\Sifu',
    [string]$GripSockets,
    [int]$WandererOutfitIndex = -1,
    [string]$BaseNailoongPak,
    [int]$TongjiOutfitIndex = -1,
    [switch]$Sirung,
    [switch]$Cape,
    [switch]$Cloth
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$wanderer = $WandererOutfitIndex -ne -1
$tongji = $TongjiOutfitIndex -ne -1
if ($wanderer -and $tongji) { throw 'Build one outfit variant at a time.' }
if ($Sirung -and !$tongji) { throw 'Sirung requires a Tongji outfit slot.' }
if ($Cape -and !$Sirung) { throw 'The cape requires the Tongji Sirung outfit.' }
if ($Cloth -and !$Cape) { throw 'Cloth requires the Tongji cape.' }
$variant = if ($tongji) { 'Tongji' } elseif ($wanderer) { 'Wanderer' }
$outfitIndex = if ($tongji) { $TongjiOutfitIndex } else { $WandererOutfitIndex }
if ($variant -and ($outfitIndex -lt 1 -or !$BaseNailoongPak -or !$GripSockets)) {
    throw "$variant requires a non-default costume index, a base pak and a grip-socket specification."
}
if ($variant) { $BaseNailoongPak = (Resolve-Path -LiteralPath $BaseNailoongPak).Path }
$meshName = if ($variant) { "SK_Nailoong_$variant" } else { 'SK_Nailoong' }
$engine = Join-Path $UERoot 'Engine'
$version = Get-Content -Raw -LiteralPath (Join-Path $engine 'Build\Build.version') | ConvertFrom-Json
if ("$($version.MajorVersion).$($version.MinorVersion).$($version.PatchVersion)" -ne '4.26.2') {
    throw 'This project targets Unreal Engine 4.26.2.'
}

$editor = Join-Path $engine 'Binaries\Win64\UE4Editor-Cmd.exe'
$unrealPak = Join-Path $engine 'Binaries\Win64\UnrealPak.exe'
$repak = Join-Path $root 'tools\repak\repak.exe'
$project = Join-Path $root 'ue\Sifu.uproject'
$build = Join-Path $root $(if ($variant) { "build/$($variant.ToLowerInvariant())" } else { 'build' })
if ($Cloth) { $build = Join-Path $build 'cloth' }
elseif ($Cape) { $build = Join-Path $build 'cape' }
elseif ($Sirung) { $build = Join-Path $build 'sirung' }
$importReport = Join-Path $build 'ue-import.json'
$importScript = Join-Path $PSScriptRoot 'import_ue.py'
$cooked = Join-Path $root 'ue\Saved\Cooked\WindowsNoEditor\Sifu\Content'
$release = Join-Path $build 'local-mod'
$response = Join-Path $build 'pak-response.txt'
$gamePakDir = Join-Path $GameRoot 'Sifu\Content\Paks'
$sig = Join-Path $gamePakDir 'pakchunk0-WindowsNoEditor.sig'
Get-Item -LiteralPath $editor,$repak,$sig | Out-Null
New-Item -ItemType Directory -Force -Path $release | Out-Null
if (Test-Path -LiteralPath $importReport) { Remove-Item -LiteralPath $importReport }

$previousMode = $env:SIFU_BUILD_WANDERER
$previousTongjiMode = $env:SIFU_BUILD_TONGJI
$previousSirungMode = $env:SIFU_BUILD_SIRUNG
$previousCapeMode = $env:SIFU_BUILD_TONGJI_CAPE
$previousClothMode = $env:SIFU_BUILD_TONGJI_CLOTH
try {
    $env:SIFU_BUILD_WANDERER = if ($wanderer) { '1' } else { '0' }
    $env:SIFU_BUILD_TONGJI = if ($tongji) { '1' } else { '0' }
    $env:SIFU_BUILD_SIRUNG = if ($Sirung) { '1' } else { '0' }
    $env:SIFU_BUILD_TONGJI_CAPE = if ($Cape) { '1' } else { '0' }
    $env:SIFU_BUILD_TONGJI_CLOTH = if ($Cloth) { '1' } else { '0' }
    & $editor $project '-run=pythonscript' "-script=$importScript" -unattended -nop4 -nosplash -nullrhi -stdout -FullStdOutLogOutput *> (Join-Path $build 'ue-import.log')
} finally {
    $env:SIFU_BUILD_WANDERER = $previousMode
    $env:SIFU_BUILD_TONGJI = $previousTongjiMode
    $env:SIFU_BUILD_SIRUNG = $previousSirungMode
    $env:SIFU_BUILD_TONGJI_CAPE = $previousCapeMode
    $env:SIFU_BUILD_TONGJI_CLOTH = $previousClothMode
}
if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $importReport)) {
    throw 'UE import failed. See build/ue-import.log.'
}

$content = Join-Path $root 'ue\Content'
& $editor $project -run=cook -targetplatform=WindowsNoEditor "-cookdir=$content" -unattended -nop4 -nosplash -stdout -FullStdOutLogOutput *> (Join-Path $build 'ue-cook.log')
if ($LASTEXITCODE -ne 0) { throw 'UE cooking failed. See build/ue-cook.log.' }

$assetRelativePath = 'Characters\MainChar\M\Nailoong'
$ownAssets = Get-ChildItem -LiteralPath (Join-Path $cooked $assetRelativePath) -File -Recurse |
    Where-Object {
        if ($tongji) {
            $_.BaseName.Contains('_Tongji') -and ($Sirung -or !$_.BaseName.Contains('_Sirung')) -and
                ($Cape -or !$_.BaseName.Contains('_Cape')) -and ($Cloth -or !$_.BaseName.Contains('_Cloth'))
        }
        elseif ($variant) { $_.BaseName.Contains("_$variant") }
        else { $_.BaseName -notmatch '_(Wanderer|Tongji)(_|$)' }
    }
if (!(Test-Path -LiteralPath (Join-Path $cooked "$assetRelativePath\$meshName.uasset"))) {
    throw 'The cooked output does not contain the Nailoong skeletal mesh.'
}

$inputBlueprint = Join-Path $root 'local\reference\Sifu\Content\Blueprints\BP_FightingPlayer.uasset'
$outputBlueprint = Join-Path $build 'player-patch\BP_FightingPlayer.uasset'
$dotnet = Join-Path $root 'tools\dotnet\dotnet.exe'
if ($variant) {
    $originalPlayer = Get-Content -Raw -LiteralPath ([IO.Path]::ChangeExtension($inputBlueprint, '.json')) |
        ConvertFrom-Json -Depth 100 | Where-Object Name -eq 'PlayerFighting_GEN_VARIABLE'
    $outfits = $originalPlayer.Properties.m_ByGenderData.m_Outfits
    if ($outfitIndex -ge $outfits.Count) { throw "$variant outfit index is out of range." }
    $selection = $outfits[$outfitIndex].m_Mesh.AssetPathName
    $patchArgs = @($variant.ToLowerInvariant(), $outfitIndex, $selection)
} else {
    $patchArgs = @('nailoong')
}
& $dotnet run --project (Join-Path $PSScriptRoot 'OutfitPatch') -c Release -- $inputBlueprint $outputBlueprint @patchArgs
if ($LASTEXITCODE -ne 0) { throw 'The male default outfit could not be patched.' }

$entries = foreach ($asset in $ownAssets) {
    $relative = $asset.FullName.Substring($cooked.Length + 1).Replace('\', '/')
    '"{0}" "../../../Sifu/Content/{1}"' -f $asset.FullName,$relative
}
$entries += '"{0}" "../../../Sifu/Content/Blueprints/BP_FightingPlayer.uasset"' -f $outputBlueprint
$entries += '"{0}" "../../../Sifu/Content/Blueprints/BP_FightingPlayer.uexp"' -f [IO.Path]::ChangeExtension($outputBlueprint, '.uexp')
$entries | Set-Content -LiteralPath $response -Encoding Ascii

$pak = Join-Path $release 'pakchunk99-Nailoong_P.pak'
# Use the V11 format already validated in this Epic install. Each build gets a
# fresh staging folder so no prior diagnostic or shared skeleton can leak in.
$stage = Join-Path $build ('pak-stage-' + [guid]::NewGuid().ToString('N'))
if ($variant) {
    & $repak unpack $BaseNailoongPak -o $stage --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract the base Nailoong pak.' }
    $stage = Join-Path $stage 'Sifu/Content'
    if (!(Test-Path -LiteralPath (Join-Path $stage "$assetRelativePath\SK_Nailoong.uasset"))) {
        throw 'The supplied base pak does not contain the v14 default mesh.'
    }
    if ($tongji -and !(Test-Path -LiteralPath (Join-Path $stage "$assetRelativePath\SK_Nailoong_Wanderer.uasset"))) {
        throw 'The Tongji build needs the combined v14 and Wanderer pak.'
    }
}
$stageMesh = Join-Path $stage $assetRelativePath
$stageBlueprint = Join-Path $stage 'Blueprints'
New-Item -ItemType Directory -Force -Path $stageMesh,$stageBlueprint | Out-Null
foreach ($asset in $ownAssets) {
    $relative = $asset.FullName.Substring((Join-Path $cooked $assetRelativePath).Length + 1)
    $target = Join-Path $stageMesh $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $asset.FullName -Destination $target
}
Copy-Item -LiteralPath $outputBlueprint,([IO.Path]::ChangeExtension($outputBlueprint, '.uexp')) -Destination $stageBlueprint
if ($GripSockets) {
    $specPath = (Resolve-Path -LiteralPath $GripSockets).Path
    $cookedMesh = Join-Path $cooked "$assetRelativePath\$meshName.uasset"
    $stagedMesh = Join-Path $stageMesh "$meshName.uasset"
    & $dotnet run --project (Join-Path $PSScriptRoot 'GripSocketPatch') -c Release -- $cookedMesh $stagedMesh $specPath
    if ($LASTEXITCODE -ne 0) { throw 'Adding mesh-only grip sockets failed.' }
}
& $repak pack $stage $pak --mount-point '../../../Sifu/Content/' --version V11 --compression Zlib
if ($LASTEXITCODE -ne 0) { throw 'repak did not build the mod.' }
$pakList = & $repak list $pak
if ($LASTEXITCODE -ne 0) { throw 'repak could not open the generated mod.' }
if ($pakList | Where-Object { $_ -notmatch '^Sifu/Content/(Characters/MainChar/M/Nailoong/|Blueprints/BP_FightingPlayer\.)' }) {
    throw 'Unexpected asset in the mod archive.'
}
$pakList | Set-Content -LiteralPath (Join-Path $build 'pak-contents.txt')

$readback = Join-Path $build 'mod-readback'
$exporter = Join-Path $root 'tools\SifuExport\SifuExport.dll'
$meshPath = "/Game/Characters/MainChar/M/Nailoong/$meshName"
& $dotnet $exporter $release $readback json $meshPath
if ($LASTEXITCODE -ne 0) { throw 'The final skeletal mesh could not be read back.' }
$meshJson = Join-Path $readback "Sifu\Content\Characters\MainChar\M\Nailoong\$meshName.json"
$mesh = Get-Content -LiteralPath $meshJson -Raw | ConvertFrom-Json -Depth 100 | Where-Object Type -eq 'SkeletalMesh'
if ($mesh.Properties.Skeleton.ObjectName -ne "Skeleton'Base_skeleton'" -or
    $mesh.Properties.PhysicsAsset.ObjectName -ne "PhysicsAsset'PA_M_MainChar'" -or
    $mesh.Properties.ShadowPhysicsAsset.ObjectName -ne "PhysicsAsset'PA_M_MainChar_ShadowCapsules'") {
    throw 'The cooked mesh does not reference the expected original skeleton and physics assets.'
}
$meshText = Get-Content -LiteralPath $meshJson -Raw
if (!$meshText.Contains('MI_Nailoong')) { throw 'The cooked mesh does not reference the Nailoong material.' }
if ($wanderer -and (!$meshText.Contains("MaterialInstanceConstant'MI_Nailoong'") -or
                   !$meshText.Contains("MaterialInstanceConstant'MI_Nailoong_Wanderer'"))) {
    throw 'The Wanderer mesh did not retain its body and outfit materials.'
}
if ($tongji -and !$meshText.Contains("MaterialInstanceConstant'MI_Nailoong_Tongji'")) {
    throw 'The Tongji mesh did not retain its skin material.'
}
if ($Sirung -and !$meshText.Contains("MaterialInstanceConstant'MI_Nailoong_Tongji_Sirung'")) {
    throw 'The Tongji mesh did not retain its SIRUNG material.'
}
if ($Cape -and !$meshText.Contains("MaterialInstanceConstant'MI_Nailoong_Tongji_Cape'")) {
    throw 'The Tongji mesh did not retain its cape material.'
}
if ($Cloth -and (!$meshText.Contains('Cloth_Tongji_Cape') -or !$meshText.Contains('PA_Nailoong_Tongji_Cloth'))) {
    throw 'The cooked cape did not retain its clothing asset and collision physics.'
}
if ($Cloth) {
    $expectedSections = Get-Content -LiteralPath $importReport -Raw | ConvertFrom-Json -Depth 20
    $cookedSections = $mesh.LODModels[0].Sections
    if ($cookedSections.Count -ne $expectedSections.cloth.sections.sections.Count) {
        throw 'The cooked mesh has an unexpected section count.'
    }
    foreach ($expected in $expectedSections.cloth.sections.sections) {
        $section = $cookedSections[$expected.section]
        if ($mesh.SkeletalMaterials[$section.MaterialIndex].MaterialSlotName -cne $expected.slot -or
            $section.bDisabled -ne [bool]$expected.disabled -or
            $section.CorrespondClothAssetIndex -ne $expected.cloth_index -or $section.NumTriangles -le 0) {
            throw "The cooked mesh did not preserve the expected section state for $($expected.slot)."
        }
    }
}
if ($GripSockets) {
    $socketExports = Get-Content -LiteralPath $meshJson -Raw | ConvertFrom-Json -Depth 100 |
        Where-Object Type -eq 'SkeletalMeshSocket'
    $expectedSockets = Get-Content -LiteralPath $specPath -Raw | ConvertFrom-Json
    if (@($socketExports).Count -ne @($expectedSockets).Count) {
        throw 'The package did not retain the grip socket exports.'
    }
    foreach ($expected in $expectedSockets) {
        $socket = $socketExports | Where-Object { $_.Properties.SocketName -ceq $expected.name }
        if (!$socket -or $socket.Properties.BoneName -cne $expected.bone) {
            throw "Unexpected packed socket $($expected.name)."
        }
        for ($axis = 0; $axis -lt 3; $axis++) {
            $component = @('X','Y','Z')[$axis]
            if ([Math]::Abs($socket.Properties.RelativeLocation.$component - $expected.position[$axis]) -gt .001) {
                throw "Unexpected packed socket translation $($expected.name)."
            }
        }
    }
}
& $dotnet $exporter $release $readback skel $meshPath
if ($LASTEXITCODE -ne 0) { throw 'Could not audit the cooked reference skeleton.' }
$original = (Get-Content -Raw -LiteralPath (Join-Path $root 'local\reference\Sifu\Content\Characters\MainChar\M\Meshes\SK_M_MainChar_01.SK_M_MainChar_01.skel.json') | ConvertFrom-Json -Depth 100).bones
$actual = (Get-Content -Raw -LiteralPath (Join-Path $readback "Sifu\Content\Characters\MainChar\M\Nailoong\$meshName.$meshName.skel.json") | ConvertFrom-Json -Depth 100).bones
if ($actual.Count -ne $original.Count) { throw 'Cooked bone count differs from the original.' }
for ($i = 0; $i -lt $original.Count; $i++) {
    if ($actual[$i].name -ne $original[$i].name -or $actual[$i].parent -ne $original[$i].parent) {
        throw "Cooked bone hierarchy differs at $i."
    }
    foreach ($field in 't','s') {
        for ($j = 0; $j -lt 3; $j++) {
            if ([Math]::Abs($actual[$i].$field[$j] - $original[$i].$field[$j]) -gt .005) {
                throw "Cooked bone transform differs at $i/$field."
            }
        }
    }
    $dot = 0.0
    for ($j = 0; $j -lt 4; $j++) { $dot += $actual[$i].q[$j] * $original[$i].q[$j] }
    if ([Math]::Abs($dot) -lt .99999) { throw "Cooked bone rotation differs at $i." }
}

Copy-Item -LiteralPath $sig -Destination ([IO.Path]::ChangeExtension($pak, '.sig'))
Get-Item -LiteralPath $pak
