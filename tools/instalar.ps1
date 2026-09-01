# Prepara uma máquina nova para rodar o LoL Queue, do zero ao atalho.
#
# Existe porque até aqui não existia: copiar a pasta para outro PC
# entregava o código e mais nada. Sem as dependências, o atalho abre o
# `pythonw.exe`, o import morre sem console e o duplo clique não produz
# nem uma janela de erro — o app "não funciona" e ninguém consegue
# dizer por quê.
#
# O executável compilado seria o caminho curto, mas o Smart App Control
# do Windows 11 recusa binário sem assinatura e sem reputação (veja o
# README). Então o que se leva para a outra máquina é esta pasta, e o
# que a prepara é este script.
#
# Uso, dentro da pasta do app:
#     powershell -ExecutionPolicy Bypass -File tools\instalar.ps1

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

# 1. Escolhe o interpretador uma vez. O atalho precisa usar este mesmo
#    arquivo: instalar no Python 3.13 e abrir com outro Python que por acaso
#    seja o padrão da máquina faz recursos opcionais (como Arsenal e Análise)
#    sumirem sem que o app inteiro deixe de abrir.
#
#    Preferimos o launcher oficial, mas aceitamos `python` no PATH como plano
#    B, pois há instalações válidas sem o launcher `py`.
$python = $null
foreach ($tentativa in @(
    @{ Comando = "py"; Argumentos = @("-3", "-c", "import sys; print(sys.executable)") },
    @{ Comando = "python"; Argumentos = @("-c", "import sys; print(sys.executable)") }
)) {
    try {
        $comando = [string]$tentativa.Comando
        $argumentos = [string[]]$tentativa.Argumentos
        $saida = & $comando @argumentos 2>$null
        if ($LASTEXITCODE -eq 0) {
            $candidato = (($saida | Select-Object -Last 1).ToString()).Trim()
            if ($candidato -and (Test-Path -LiteralPath $candidato)) {
                $python = [System.IO.Path]::GetFullPath($candidato)
                break
            }
        }
    } catch { }
}

if (-not $python) {
    Write-Output ""
    Write-Output "Falta o Python. Instale a versao 3.13 ou mais nova em"
    Write-Output "    https://www.python.org/downloads/"
    Write-Output "e marque 'Add python.exe to PATH' na primeira tela."
    exit 1
}

$versao = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0 -or -not $versao) {
    Write-Output "Nao consegui executar o Python encontrado em $python."
    exit 1
}

$partes = $versao.Trim().Split(".")
if ([int]$partes[0] -lt 3 -or ([int]$partes[0] -eq 3 -and [int]$partes[1] -lt 13)) {
    Write-Output ""
    Write-Output "Python $versao e antigo demais; o app pede 3.13 ou mais novo."
    Write-Output "Instale a versao atual em https://www.python.org/downloads/"
    exit 1
}
Write-Output "Python $versao encontrado."

# 2. As dependências, lidas do pyproject.toml. A lista não se repete
#    aqui de propósito: duas listas viram uma desatualizada. Os qualificadores
#    (por exemplo, `PySide6>=6.10`) também viajam inteiros:
#    assim uma instalação antiga é atualizada quando não atende ao mínimo.
$pacotes = & $python -c "from lolqueue.ambiente import pacotes_instalacao; print('\n'.join(pacotes_instalacao()))"
$pacotes = @($pacotes -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($pacotes.Count -eq 0) {
    Write-Output "Nao consegui ler as dependencias do pyproject.toml."
    exit 1
}

Write-Output "Instalando: $($pacotes -join ', ')"
# Sem `--upgrade`: numa maquina que ja roda o app, atualizar o Qt por
# conta propria e um jeito de quebrar o que funcionava. O pip so toca
# no que estiver faltando ou abaixo do minimo declarado.
& $python -m pip install --disable-pip-version-check @pacotes
if ($LASTEXITCODE -ne 0) {
    Write-Output ""
    Write-Output "O pip falhou. Sem isso o app nao abre; releia o erro acima."
    exit 1
}

# 3. A prova. "O pip disse que instalou" não é a mesma coisa que "o
#    import encontra" — e é o import que decide se o app abre.
$faltando = & $python -c "from lolqueue.ambiente import faltando; print(','.join(faltando()))"
$faltando = $faltando.Trim()
if ($faltando) {
    Write-Output ""
    Write-Output "Instalou, mas ainda nao da para importar: $faltando"
    exit 1
}
Write-Output "Todas as dependencias respondem ao import."

# 4. O atalho, que é como o app é aberto no dia a dia. Enviamos o
# executável exato usado acima, em vez de deixar o script escolher o padrão
# de uma instalação que pode ter várias versões de Python.
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "atalho.ps1") -PythonExe $python
if ($LASTEXITCODE -ne 0) {
    Write-Output "Nao consegui criar o atalho do LoL Queue."
    exit 1
}

Write-Output ""
Write-Output "Pronto. Abra pelo atalho 'LoL Queue' na Area de Trabalho."
