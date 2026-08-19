# Cria um atalho que abre o app sem janela preta.
#
# O executável de dist\ resolve o mesmo problema, mas o Smart App
# Control do Windows 11 bloqueia binário sem assinatura reconhecida —
# e desligá-lo é irreversível. O atalho contorna isso porque quem roda
# é o pythonw.exe, que já é assinado e confiável; o "w" no nome é
# justamente a versão que não abre console.
#
# Uso:
#     powershell -ExecutionPolicy Bypass -File tools\criar-atalho.ps1
#     powershell -ExecutionPolicy Bypass -File tools\criar-atalho.ps1 -AreaDeTrabalho

param([switch]$AreaDeTrabalho)

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
$pythonw = & py -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"

if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe não encontrado em $pythonw"
}

$destino = if ($AreaDeTrabalho) { [Environment]::GetFolderPath("Desktop") } else { $raiz }
$atalho = Join-Path $destino "LoL Queue.lnk"

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($atalho)
$link.TargetPath = $pythonw
$link.Arguments = "main.py"
$link.WorkingDirectory = $raiz
$link.IconLocation = Join-Path $raiz "lolqueue\assets\icon.ico"
$link.Description = "Abre o LoL Queue sem janela de console"
$link.Save()

Write-Output $atalho
