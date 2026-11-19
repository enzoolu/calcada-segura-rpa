param([switch]$Campo)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Instale Python 3.12 e o inicializador py.' }
}
$requisitos = @('-r', 'rpa/requirements.txt', '-r', 'integracao/requirements.txt')
if ($Campo) {
    $requisitos += @('-r', 'visao/requirements.txt')
}
& $python -m pip install @requisitos
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências.' }
if ($Campo) {
    $saida = '.demo/campo-' + [guid]::NewGuid().ToString('N')
    & $python -m integracao.demonstrar_campo --fonte integracao/evidencias/campo/trecho.mp4 --saida $saida --painel
} else {
    & $python -m integracao.demonstrar_rpa
}
exit $LASTEXITCODE
