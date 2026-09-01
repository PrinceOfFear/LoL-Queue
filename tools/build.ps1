# Gera uma distribuição portátil do LoL Queue, pronta para enviar.
#
# Uso:
#     powershell -ExecutionPolicy Bypass -File tools\build.ps1
#
# Resultado:
#     Distribuicao\LoL Queue\                  <- pasta que precisa ficar inteira
#     Distribuicao\LoL Queue-<versao>-win64.zip <- arquivo para enviar
#     Distribuicao\LoL Queue-<versao>-win64.sha256
#     Distribuicao\LoL Queue - instalar com Python\
#     Distribuicao\LoL Queue-<versao>-instalacao-python.zip
#
# O executável NÃO é um arquivo isolado: as DLLs do Python/Qt, os módulos
# compilados e os assets ficam ao lado dele. A falha mais comum ao passar para
# outro PC é copiar somente "LoL Queue.exe". Este script cria a pasta e o ZIP
# corretos para que isso não volte a acontecer.
#
# O build intermediário nasce em build\distribuicao-nuitka (ignorado pelo Git).
# Só depois de uma compilação e uma conferência bem-sucedidas ele substitui a
# versão que está em Distribuicao. Assim uma compilação que falhar não apaga o
# último pacote que já funcionava.

$ErrorActionPreference = "Stop"

$raiz = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location $raiz

$buildRoot = Join-Path $raiz "build\distribuicao-nuitka"
$releaseRoot = Join-Path $raiz "Distribuicao"
$payloadName = "LoL Queue"
$payloadDir = Join-Path $releaseRoot $payloadName
$stagingDir = Join-Path $releaseRoot "_em-preparo"
$pythonPayloadName = "LoL Queue - instalar com Python"
$pythonPayloadDir = Join-Path $releaseRoot $pythonPayloadName
$pythonStagingDir = Join-Path $releaseRoot "_em-preparo-python"

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

function Remove-OnlyInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$AllowedRoot
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $root = [System.IO.Path]::GetFullPath($AllowedRoot).TrimEnd([char[]]@('\', '/'))
    $target = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Recusei apagar fora de '$root': $target"
    }

    Remove-Item -LiteralPath $target -Recurse -Force
}

# Não reutilizar artefato parcial ou DLL que tenha sobrado de uma versão antiga.
Remove-OnlyInside -Path $buildRoot -AllowedRoot (Join-Path $raiz "build")
Remove-OnlyInside -Path $stagingDir -AllowedRoot $releaseRoot
Remove-OnlyInside -Path $pythonStagingDir -AllowedRoot $releaseRoot

$versionMatch = Select-String -LiteralPath (Join-Path $raiz "pyproject.toml") `
    -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($null -eq $versionMatch) {
    throw "Não consegui ler a versão em pyproject.toml."
}
$version = $versionMatch.Matches[0].Groups[1].Value
$runtimeVersion = ((& py -3 -c "from lolqueue.version import VERSION; print(VERSION)" | Select-Object -Last 1).ToString()).Trim()
if ($LASTEXITCODE -ne 0 -or $runtimeVersion -ne $version) {
    throw "A versao de lolqueue/version.py ('$runtimeVersion') nao confere com pyproject.toml ('$version'). Atualize as duas antes de empacotar."
}
$zipPath = Join-Path $releaseRoot ("LoL Queue-" + $version + "-win64.zip")
$hashPath = $zipPath + ".sha256"
$pythonZipPath = Join-Path $releaseRoot ("LoL Queue-" + $version + "-instalacao-python.zip")
$pythonHashPath = $pythonZipPath + ".sha256"

# Usa Nuitka em vez de PyInstaller: o código entra compilado em binário e a
# pasta permanece portátil. O modo standalone é deliberado: onefile extrai DLL
# temporária e é ainda mais incompatível com o Smart App Control do Windows.
#
# keyboard é importado sob demanda, e websockets sustenta a captura de PDL em
# tempo real. Incluí-los explicitamente evita que uma análise estática deixe
# recursos importantes de fora do .exe distribuído.
# O compilador Zig usado pelo Nuitka pode herdar AVX2 da máquina que está
# compilando. Isso faz um .exe fechar com 0xC000001D em CPUs x64 mais antigas
# (por exemplo, Xeon E3 v2, que não tem AVX2). A base x86_64 impede instruções
# acima do conjunto x64 padrão. CCFLAGS é a via oficial do Nuitka para entregar
# flags ao compilador C; preservamos o que já existir no ambiente do usuário.
$oldCcFlags = $env:CCFLAGS
$baselineIsa = "-march=x86_64"
$env:CCFLAGS = if ([string]::IsNullOrWhiteSpace($oldCcFlags)) {
    $baselineIsa
} else {
    "$oldCcFlags $baselineIsa"
}

$versionCore = ($version -split "-", 2)[0]
$versionParts = @($versionCore -split "\.")
while ($versionParts.Count -lt 4) {
    $versionParts += "0"
}
$fileVersion = $versionParts[0..3] -join "."

try {
    py -m nuitka main.py `
        --standalone `
        --enable-plugin=pyside6 `
        --windows-console-mode=disable `
        --windows-icon-from-ico=lolqueue/assets/icon.ico `
        --include-data-dir=lolqueue/assets=lolqueue/assets `
        --include-package=keyboard `
        --include-package=websockets `
        --include-package=cryptography `
        --output-dir=$buildRoot `
        --output-filename="LoL Queue.exe" `
        --assume-yes-for-downloads `
        --company-name="LoL Queue" `
        --product-name="LoL Queue" `
        --file-version=$fileVersion `
        --product-version=$version
    $nuitkaExit = $LASTEXITCODE
} finally {
    if ($null -eq $oldCcFlags) {
        Remove-Item Env:CCFLAGS -ErrorAction SilentlyContinue
    } else {
        $env:CCFLAGS = $oldCcFlags
    }
}

if ($nuitkaExit -ne 0) {
    throw "O Nuitka terminou com código $nuitkaExit. A distribuição anterior foi preservada."
}

$compiledDir = Join-Path $buildRoot "main.dist"
$requiredFiles = @(
    (Join-Path $compiledDir "LoL Queue.exe"),
    (Join-Path $compiledDir "PySide6"),
    (Join-Path $compiledDir "lolqueue\assets\icon.ico"),
    (Join-Path $compiledDir "lolqueue\assets\spells\flash.png"),
    (Join-Path $compiledDir "lolqueue\assets\ranks\gold.png")
)
$missing = @($requiredFiles | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
    throw "O Nuitka terminou, mas faltam arquivos obrigatórios:`n$($missing -join "`n")"
}

# Monta primeiro uma cópia completa em staging. A distribuição anterior só sai
# do lugar depois que os arquivos essenciais da nova estiverem presentes.
New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
Get-ChildItem -LiteralPath $compiledDir -Force | Copy-Item -Destination $stagingDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LEIA-ME-DISTRIBUICAO.txt") `
    -Destination (Join-Path $stagingDir "LEIA-ME.txt") -Force

$stagedExe = Join-Path $stagingDir "LoL Queue.exe"
if (-not (Test-Path -LiteralPath $stagedExe)) {
    throw "A cópia para distribuição não contém LoL Queue.exe; a versão anterior foi preservada."
}

Remove-OnlyInside -Path $payloadDir -AllowedRoot $releaseRoot
Move-Item -LiteralPath $stagingDir -Destination $payloadDir

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $hashPath) {
    Remove-Item -LiteralPath $hashPath -Force
}

Compress-Archive -LiteralPath $payloadDir -DestinationPath $zipPath -CompressionLevel Optimal -Force
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
"$hash  $([System.IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $hashPath -Encoding ascii

# Smart App Control pode bloquear executáveis novos sem assinatura, mesmo
# quando o pacote está perfeito. Esta alternativa usa o pythonw.exe assinado
# pela Python Software Foundation e instala as dependências no PC de destino.
# Ela é a rota compatível para quem receber esse bloqueio; por incluir o código
# Python, fica separada para que a pessoa que distribui possa escolhê-la.
New-Item -ItemType Directory -Force -Path $pythonStagingDir | Out-Null
Copy-Item -LiteralPath (Join-Path $raiz "main.py") -Destination $pythonStagingDir -Force
Copy-Item -LiteralPath (Join-Path $raiz "pyproject.toml") -Destination $pythonStagingDir -Force
Copy-Item -LiteralPath (Join-Path $raiz "lolqueue") -Destination $pythonStagingDir -Recurse -Force

$pythonToolsDir = Join-Path $pythonStagingDir "tools"
New-Item -ItemType Directory -Force -Path $pythonToolsDir | Out-Null
foreach ($tool in @("instalar.ps1", "atalho.ps1")) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $tool) -Destination $pythonToolsDir -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LEIA-ME-INSTALACAO-PYTHON.txt") `
    -Destination (Join-Path $pythonStagingDir "LEIA-ME.txt") -Force

# Bytecode de desenvolvimento não é necessário e pode ser incompatível com a
# versão de Python do destinatário. A pasta temporária é o único alvo removido.
foreach ($cacheDir in @(Get-ChildItem -LiteralPath $pythonStagingDir -Recurse -Directory -Filter "__pycache__")) {
    Remove-OnlyInside -Path $cacheDir.FullName -AllowedRoot $pythonStagingDir
}

$pythonRequired = @(
    (Join-Path $pythonStagingDir "main.py"),
    (Join-Path $pythonStagingDir "pyproject.toml"),
    (Join-Path $pythonStagingDir "tools\instalar.ps1"),
    (Join-Path $pythonStagingDir "tools\atalho.ps1"),
    (Join-Path $pythonStagingDir "lolqueue\assets\icon.ico"),
    (Join-Path $pythonStagingDir "lolqueue\assets\spells\flash.png")
)
$pythonMissing = @($pythonRequired | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($pythonMissing.Count -gt 0) {
    throw "A distribuição compatível está incompleta:`n$($pythonMissing -join "`n")"
}

Remove-OnlyInside -Path $pythonPayloadDir -AllowedRoot $releaseRoot
Move-Item -LiteralPath $pythonStagingDir -Destination $pythonPayloadDir
if (Test-Path -LiteralPath $pythonZipPath) {
    Remove-Item -LiteralPath $pythonZipPath -Force
}
if (Test-Path -LiteralPath $pythonHashPath) {
    Remove-Item -LiteralPath $pythonHashPath -Force
}
Compress-Archive -LiteralPath $pythonPayloadDir -DestinationPath $pythonZipPath -CompressionLevel Optimal -Force
$pythonHash = (Get-FileHash -LiteralPath $pythonZipPath -Algorithm SHA256).Hash
"$pythonHash  $([System.IO.Path]::GetFileName($pythonZipPath))" | Set-Content -LiteralPath $pythonHashPath -Encoding ascii

# Deixa uma pasta sem versões antigas para evitar que o ZIP errado seja enviado.
& (Join-Path $PSScriptRoot "organizar_distribuicao.ps1") -Version $version
if ($LASTEXITCODE -ne 0) {
    throw "Não consegui organizar a pasta pronta para envio."
}

Write-Output ""
Write-Output "Distribuição pronta:"
Write-Output "  Pasta: $payloadDir"
Write-Output "  ZIP:   $zipPath"
Write-Output "  SHA:   $hashPath"
Write-Output ""
Write-Output "Para enviar, use o ZIP inteiro. Quem receber deve extrair tudo antes de abrir LoL Queue.exe."
Write-Output ""
Write-Output "Alternativa para PCs que bloquearem o .exe sem assinatura:"
Write-Output "  Pasta: $pythonPayloadDir"
Write-Output "  ZIP:   $pythonZipPath"
Write-Output "  SHA:   $pythonHashPath"
Write-Output ""
Write-Output "Envio guiado: $(Join-Path $releaseRoot 'ENVIAR PARA OUTRAS PESSOAS')"
