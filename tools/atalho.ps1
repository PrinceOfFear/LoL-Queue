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
param(
    # O instalador envia o executável exato no qual instalou as bibliotecas.
    # Isso impede que o atalho escolha outro Python em uma máquina com mais
    # de uma versão instalada.
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    # Uso manual do script: mantém o mesmo seletor do instalador, em vez do
    # `py` sem versão, que pode apontar para outro runtime.
    $PythonExe = & py -3 -c "import sys; print(sys.executable)"
}
$python = (($PythonExe | Select-Object -Last 1).ToString()).Trim()
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    throw "python.exe nao encontrado em $python"
}
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) { throw "pythonw.exe nao encontrado em $pythonw" }

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
