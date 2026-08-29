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

# 1. O interpretador. `py` é o launcher que a instalação oficial deixa
#    no PATH; `python` costuma não estar lá, ou ser o atalho da Store
#    que abre a loja em vez de rodar.
$versao = $null
try { $versao = & py -3 -c "import sys; print('%d.%d' % sys.version_info[:2])" } catch { }
if (-not $versao) {
    Write-Output ""
    Write-Output "Falta o Python. Instale a versao 3.13 ou mais nova em"
    Write-Output "    https://www.python.org/downloads/"
    Write-Output "e marque 'Add python.exe to PATH' na primeira tela."
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
#    aqui de propósito: duas listas viram uma desatualizada, e foi assim
#    que o `edge-tts` ficou de fora uma vez e a máquina jogou muda.
$pacotes = & py -3 -c "from lolqueue.ambiente import requisitos; print('\n'.join(requisitos()))"
$pacotes = @($pacotes -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($pacotes.Count -eq 0) {
    Write-Output "Nao consegui ler as dependencias do pyproject.toml."
    exit 1
}

Write-Output "Instalando: $($pacotes -join ', ')"
# Sem `--upgrade`: numa maquina que ja roda o app, atualizar o Qt por
# conta propria e um jeito de quebrar o que funcionava. O pip so
# instala o que estiver faltando.
& py -3 -m pip install --disable-pip-version-check @pacotes
if ($LASTEXITCODE -ne 0) {
    Write-Output ""
    Write-Output "O pip falhou. Sem isso o app nao abre; releia o erro acima."
    exit 1
}

# 3. A prova. "O pip disse que instalou" não é a mesma coisa que "o
#    import encontra" — e é o import que decide se o app abre.
$faltando = & py -3 -c "from lolqueue.ambiente import faltando; print(','.join(faltando()))"
$faltando = $faltando.Trim()
if ($faltando) {
    Write-Output ""
    Write-Output "Instalou, mas ainda nao da para importar: $faltando"
    exit 1
}
Write-Output "Todas as dependencias respondem ao import."

# 4. O atalho, que é como o app é aberto no dia a dia.
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "atalho.ps1")

Write-Output ""
Write-Output "Pronto. Abra pelo atalho 'LoL Queue' na Area de Trabalho."
