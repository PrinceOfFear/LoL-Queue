# Gera o executável final em dist-standalone\main.dist\LoL Queue.exe.
#
# Usa Nuitka em vez de PyInstaller: o Nuitka compila o Python para C e
# gera um binário nativo de verdade, então não dá pra extrair o
# bytecode e decompilar de volta pra algo parecido com o fonte original
# — o que o PyInstaller sozinho não impede. Na primeira vez ele baixa
# um compilador C próprio, porque esta máquina não tem nenhum
# instalado; `-AssumeYesForDownloads` evita a pergunta interativa.
#
# É lento (minutos, não segundos) porque está compilando C de verdade,
# não só empacotando bytecode. Rode de novo sempre que o código ou os
# assets mudarem.
#
# Por que `--standalone` e não `--onefile`: no modo onefile o Nuitka põe
# o programa inteiro numa `main.dll` que o executável extrai pro %TEMP%
# e carrega em tempo de execução. Essa DLL não é assinada, e o Smart App
# Control do Windows 11 (quando ligado) recusa carregar DLL sem
# assinatura — o app abria e morria com "Imagem Incorreta", status
# 0xc0e90002, registrado no log Microsoft-Windows-CodeIntegrity como
# bloqueio de política. No modo standalone o código compilado vai dentro
# do próprio .exe e as DLLs que sobram são as do Python, da Qt e da
# Microsoft, todas assinadas — então passa. O preço é distribuir a pasta
# main.dist inteira em vez de um arquivo só.
#
# O `--include-package=edge_tts` é explícito de propósito. O import dele
# mora dentro de uma função, e a voz é a única coisa que o app faz de
# fato barulhenta: se ficar de fora do pacote, o executável abre, acha o
# jungler, mira certo e não fala — o modo de falha mais caro daqui,
# porque parece funcionar. Já aconteceu por outro caminho (o pacote
# faltando nas dependências), e a lição é a mesma: a voz não pode
# depender de alguém adivinhar que ela é necessária.
#
# Uso:
#     powershell -ExecutionPolicy Bypass -File tools\build.ps1

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

py -m nuitka main.py `
    --standalone `
    --enable-plugin=pyside6 `
    --windows-console-mode=disable `
    --windows-icon-from-ico=lolqueue/assets/icon.ico `
    --include-data-dir=lolqueue/assets=lolqueue/assets `
    --include-package=edge_tts `
    --output-dir=dist-standalone `
    --output-filename="LoL Queue.exe" `
    --assume-yes-for-downloads `
    --company-name="LoL Queue" `
    --product-name="LoL Queue" `
    --file-version=0.1.0.0 `
    --product-version=0.1.0.0

Write-Output "`ndist-standalone\main.dist\LoL Queue.exe pronto."
