<#
Publica os dois ZIPs e o manifesto assinado numa GitHub Release.

Este script NAO e executado automaticamente pelo build. Ele exige dono/repo
explicito, chave privada local e `gh auth status` valido antes de mudar algo
na internet. Use -DryRun para conferir tudo sem publicar.

Exemplo:
  powershell -ExecutionPolicy Bypass -File tools\publicar-atualizacao-github.ps1 `
    -Repositorio dono/LoL-Queue `
    -ChavePrivada chaves-atualizacao\release.chave-privada `
    -Notas docs\release-0.1.2.md
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repositorio,

    [Parameter(Mandatory = $true)]
    [string]$ChavePrivada,

    [Parameter(Mandatory = $true)]
    [string]$Notas,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$raiz = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location $raiz

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI (gh) nao esta instalado. Instale-o e execute gh auth login antes de publicar.'
}
& gh auth status --hostname github.com
if ($LASTEXITCODE -ne 0) { throw 'gh nao esta autenticado no GitHub.' }
if (-not (Test-Path -LiteralPath $ChavePrivada)) { throw "Nao achei a chave privada: $ChavePrivada" }
if (-not (Test-Path -LiteralPath $Notas)) { throw "Nao achei as notas da release: $Notas" }

$match = Select-String -LiteralPath (Join-Path $raiz 'pyproject.toml') -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($null -eq $match) { throw 'Nao consegui ler a versao em pyproject.toml.' }
$versao = $match.Matches[0].Groups[1].Value
$versaoRuntime = ((& py -3 -c "from lolqueue.version import VERSION; print(VERSION)" | Select-Object -Last 1).ToString()).Trim()
if ($LASTEXITCODE -ne 0 -or $versaoRuntime -ne $versao) {
    throw "A versao de lolqueue/version.py ('$versaoRuntime') nao confere com pyproject.toml ('$versao')."
}
$release = Join-Path $raiz 'Distribuicao'
$standalone = Join-Path $release ("LoL Queue-" + $versao + '-win64.zip')
$python = Join-Path $release ("LoL Queue-" + $versao + '-instalacao-python.zip')
foreach ($arquivo in @($standalone, $python)) {
    if (-not (Test-Path -LiteralPath $arquivo)) { throw "Falta o ZIP de distribuicao: $arquivo. Rode tools/build.ps1 primeiro." }
}

# O GitHub normaliza espacos de nomes de anexos para pontos. Se o manifesto
# assinasse o nome local "LoL Queue-...", a API listaria "LoL.Queue-..." e
# o cliente recusaria a release por nao encontrar o arquivo que assinamos.
# As copias abaixo tem nome estavel sem espaco e sao as unicas enviadas para
# a release; os ZIPs com nome amigavel continuam na pasta de distribuicao
# para envio manual.
$standaloneUpload = Join-Path $release ("LoL-Queue-" + $versao + '-win64.zip')
$pythonUpload = Join-Path $release ("LoL-Queue-" + $versao + '-instalacao-python.zip')
Copy-Item -LiteralPath $standalone -Destination $standaloneUpload -Force
Copy-Item -LiteralPath $python -Destination $pythonUpload -Force

& py -3 tools\gerar_manifesto_atualizacao.py `
    --version $versao `
    --standalone $standaloneUpload `
    --python $pythonUpload `
    --chave-privada $ChavePrivada `
    --notas $Notas
if ($LASTEXITCODE -ne 0) { throw 'Nao consegui gerar o manifesto assinado.' }

$manifesto = Join-Path $release 'lolqueue-update.json'
$assinatura = Join-Path $release 'lolqueue-update.json.sig'
$tag = 'v' + $versao
$assets = @($standaloneUpload, $pythonUpload, $manifesto, $assinatura)
if ($DryRun) {
    Write-Output "DRY RUN: gh release create $tag --repo $Repositorio (4 assets assinados)"
    $assets | ForEach-Object { Write-Output "  $_" }
    exit 0
}

& gh release create $tag --repo $Repositorio --title ("LoL Queue " + $versao) --notes-file $Notas @assets
if ($LASTEXITCODE -ne 0) { throw 'GitHub recusou a publicacao da release.' }
Write-Output "Release $tag publicada em $Repositorio."
