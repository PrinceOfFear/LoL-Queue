# Cria o atalho "LoL Queue" na Área de Trabalho.
#
# Por que um atalho e não o .exe compilado: o Smart App Control do
# Windows 11, quando ligado, recusa carregar binário sem assinatura e
# sem reputação. Cada recompilação do Nuitka produz um arquivo novo,
# que por definição não tem reputação nenhuma — o build de hoje foi
# bloqueado assim que nasceu (evento 3118 no log CodeIntegrity), e não
# adianta insistir: só passaria com um certificado de code signing
# comprado. O `pythonw.exe` da Python Software Foundation já é
# assinado, então o mesmo código roda sem esbarrar na política.
#
# O `pythonw` (e não `python`) é o que abre sem janela de console.
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = & py -c "import sys, pathlib; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))"
if (-not (Test-Path $pythonw)) { throw "pythonw.exe nao encontrado em $pythonw" }

$icone = Join-Path $repo "lolqueue\assets\icon.ico"
$destino = Join-Path ([Environment]::GetFolderPath("Desktop")) "LoL Queue.lnk"

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($destino)
$lnk.TargetPath = $pythonw
$lnk.Arguments = '"' + (Join-Path $repo "main.py") + '"'
$lnk.WorkingDirectory = $repo
$lnk.IconLocation = $icone
$lnk.Description = "Abre o LoL Queue"
$lnk.Save()

Write-Output "Atalho criado em $destino"
