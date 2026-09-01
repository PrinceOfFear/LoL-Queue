param(
    [Parameter(Mandatory = $true)][string]$Version
)

# Cria uma única pasta clara para quem vai enviar o LoL Queue. Os artefatos
# antigos continuam em Distribuicao para não perder um backup, mas não aparecem
# na pasta de envio.
$ErrorActionPreference = "Stop"

$raiz = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$releaseRoot = Join-Path $raiz "Distribuicao"
$deliveryRoot = Join-Path $releaseRoot "ENVIAR PARA OUTRAS PESSOAS"

function Remove-OnlyInsideRelease {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $root = [System.IO.Path]::GetFullPath($releaseRoot).TrimEnd([char[]]@('\', '/'))
    $target = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Recusei apagar fora de '$root': $target"
    }
    Remove-Item -LiteralPath $target -Recurse -Force
}

$exeZip = Join-Path $releaseRoot ("LoL Queue-" + $Version + "-win64.zip")
$exeHash = $exeZip + ".sha256"
$pythonZip = Join-Path $releaseRoot ("LoL Queue-" + $Version + "-instalacao-python.zip")
$pythonHash = $pythonZip + ".sha256"
$required = @($exeZip, $exeHash, $pythonZip, $pythonHash)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
    throw "Faltam arquivos para montar a pasta de envio:`n$($missing -join "`n")"
}

Remove-OnlyInsideRelease -Path $deliveryRoot
New-Item -ItemType Directory -Force -Path $deliveryRoot | Out-Null

$exeFolder = Join-Path $deliveryRoot "1 - Enviar normalmente (executável)"
$pythonFolder = Join-Path $deliveryRoot "2 - Usar se o EXE não abrir (Python)"
New-Item -ItemType Directory -Force -Path $exeFolder, $pythonFolder | Out-Null

Copy-Item -LiteralPath $exeZip, $exeHash -Destination $exeFolder -Force
Copy-Item -LiteralPath $pythonZip, $pythonHash -Destination $pythonFolder -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LEIA-ME-ENVIAR.txt") `
    -Destination (Join-Path $deliveryRoot "LEIA-ME - QUAL ARQUIVO ENVIAR.txt") -Force

Write-Output "Pasta de envio pronta: $deliveryRoot"
