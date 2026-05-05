param(
    [string]$LastoolsDir = $env:LASTOOLS_DIR,
    [string]$Image = "ml-groundfiltering-app",
    [string]$Las = "data/PK_last.laz",
    [string]$Geojson = "data/PK_segments.geojson",
    [string]$TrainLas = "data/PK_last.laz",
    [string]$TrainGeojson = "data/PK_segments_assigned.geojson",
    [string]$OutDir = "output",
    [string]$Library = "data/output",
    [string]$Epsg = "25833",
    [double]$DtmResolution = 0.5,
    [switch]$DryRun,
    [switch]$NoRetrain,
    [switch]$SkipDtm
)

$ErrorActionPreference = "Stop"

function Find-LastoolsDir {
    $candidates = @(
        $env:LASTOOLS_DIR,
        "C:\LAStools",
        "C:\lastools",
        "$HOME\LAStools",
        "$HOME\lastools",
        "$HOME\Downloads\LAStools",
        "$HOME\Downloads\lastools",
        "$PWD\LAStools",
        "$PWD\lastools"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    foreach ($candidate in $candidates) {
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        if (Test-Path -LiteralPath (Join-Path $resolved "bin")) {
            return $resolved
        }
        if (
            (Test-Path -LiteralPath (Join-Path $resolved "lasground_new64")) -or
            (Test-Path -LiteralPath (Join-Path $resolved "lasground_new64.exe"))
        ) {
            return $resolved
        }
    }

    return $null
}

function Test-LastoolsLinuxBinary {
    param([string]$BinDir)

    $linuxExecutables = @(
        "lasground_new64",
        "lasground_new",
        "lasground64",
        "lasground"
    )
    $windowsExecutables = @(
        "lasground_new64.exe",
        "lasground_new.exe",
        "lasground64.exe",
        "lasground.exe"
    )

    $linuxMatch = $linuxExecutables | Where-Object {
        Test-Path -LiteralPath (Join-Path $BinDir $_)
    } | Select-Object -First 1

    if ($linuxMatch) {
        return $linuxMatch
    }

    $windowsMatch = $windowsExecutables | Where-Object {
        Test-Path -LiteralPath (Join-Path $BinDir $_)
    } | Select-Object -First 1

    if ($windowsMatch) {
        throw @"
Nasiel som iba Windows LASTools executable '$windowsMatch' v:
  $BinDir

Tento Docker image je Linuxovy, preto potrebuje Linux LASTools build
alebo Wine-enabled image. Stiahni Linux balik LAStools.tar.gz z rapidlasso,
rozbal ho napriklad do C:\lastools-linux a spusti:

  .\run_pk_with_lastools.ps1 -LastoolsDir C:\lastools-linux
"@
    }

    throw "V '$BinDir' som nenasiel lasground_new64/lasground_new/lasground64/lasground."
}

function Ensure-AfwizardLastoolsCompatibility {
    param([string]$BinDir)

    $source = Join-Path $BinDir "lasground_new64"
    $target = Join-Path $BinDir "lasground_new64.exe"

    if ((Test-Path -LiteralPath $source) -and -not (Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $source -Destination $target
    }
}

if (-not $LastoolsDir) {
    $LastoolsDir = Find-LastoolsDir
}

if (-not $LastoolsDir) {
    throw @"
LASTools priecinok som nenasiel automaticky.

Rozbal Linux LASTools balik do priecinka, napriklad C:\lastools-linux, a spusti:
  .\run_pk_with_lastools.ps1 -LastoolsDir C:\lastools-linux

Alternativne nastav premennu prostredia:
  `$env:LASTOOLS_DIR = "C:\lastools-linux"
"@
}

$LastoolsDir = (Resolve-Path -LiteralPath $LastoolsDir).Path
$LastoolsBinDir = Join-Path $LastoolsDir "bin"
if (-not (Test-Path -LiteralPath $LastoolsBinDir)) {
    $LastoolsBinDir = $LastoolsDir
}

$groundExecutable = Test-LastoolsLinuxBinary -BinDir $LastoolsBinDir
Ensure-AfwizardLastoolsCompatibility -BinDir $LastoolsBinDir
Write-Host "Using LASTools: $LastoolsDir"
Write-Host "Using ground executable: $groundExecutable"

$dockerArgs = @(
    "run",
    "--rm",
    "-v", "${PWD}:/app",
    "-v", "${LastoolsDir}:/lastools:ro",
    "-e", "LASTOOLS_DIR=/lastools",
    "-e", "LD_LIBRARY_PATH=/lastools/bin/lib:/lastools/lib:/opt/conda/lib",
    "-w", "/app",
    $Image,
    "--las", $Las,
    "--geojson", $Geojson,
    "--train-las", $TrainLas,
    "--train-geojson", $TrainGeojson,
    "--outdir", $OutDir,
    "--library", $Library,
    "--lastools", "/lastools"
)

if (-not $NoRetrain) {
    $dockerArgs += "--retrain"
}

if (-not $DryRun) {
    $dockerArgs += "--run-afwizard"
}

docker @dockerArgs

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not $DryRun -and -not $SkipDtm) {
    $lasBaseName = [System.IO.Path]::GetFileNameWithoutExtension(($Las -replace "/", [System.IO.Path]::DirectorySeparatorChar))
    $filteredLas = "$OutDir/${lasBaseName}_filtered.las"
    $dtmTiff = "$OutDir/${lasBaseName}_filtered_dtm.tiff"

    if (Test-Path -LiteralPath $filteredLas) {
        docker run --rm `
            --entrypoint /usr/local/bin/_entrypoint.sh `
            -v "${PWD}:/app" `
            -w /app `
            $Image `
            python rasterize_dtm.py `
            --las $filteredLas `
            --out $dtmTiff `
            --epsg $Epsg `
            --resolution $DtmResolution
    } else {
        Write-Warning "Filtered LAS '$filteredLas' was not found, skipping DTM rasterization."
    }
}
