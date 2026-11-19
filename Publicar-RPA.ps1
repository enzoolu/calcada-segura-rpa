# Calçada Segura - publicar o projeto completo no GitHub
# Executar no PowerShell: powershell -ExecutionPolicy Bypass -File .\Publicar-RPA.ps1
# Requer Git instalado e autenticado (Git Credential Manager ou git login).
$ErrorActionPreference = 'Stop'
$repo = 'https://github.com/enzoolu/calcada-segura-rpa.git'
$origem = $PSScriptRoot
$destino = Join-Path $env:TEMP ('calcada-segura-rpa-' + [Guid]::NewGuid().ToString('N'))

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git nao encontrado. Instale Git for Windows, entre na sua conta e tente novamente.'
}
Write-Host "Clonando $repo..."
& git clone --depth 1 $repo $destino
if ($LASTEXITCODE -ne 0) { throw 'Falha ao clonar. Confira o acesso/autenticacao no GitHub.' }
Write-Host 'Copiando arquivos completos (incluindo video, PDF, BPMN e pesos do modelo)...'
Get-ChildItem -LiteralPath $origem -Force | Where-Object { $_.Name -ne '.git' } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $destino $_.Name) -Force -Recurse
}
& git -C $destino add -A
if ($LASTEXITCODE -ne 0) { throw 'Falha ao adicionar os arquivos.' }
& git -C $destino status --short
& git -C $destino diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Tudo ja esta publicado. Nenhuma alteracao pendente.'
    exit 0
}
& git -C $destino commit -m 'Publica implementacao completa, BPMN, PDF, video e evidencias de RPA'
if ($LASTEXITCODE -ne 0) { throw 'Falha no commit. Configure user.name e user.email no Git.' }
& git -C $destino push origin HEAD:main
if ($LASTEXITCODE -ne 0) { throw 'Falha no push. Confira permissao de escrita no repositorio.' }
Write-Host 'PUBLICACAO CONCLUIDA: https://github.com/enzoolu/calcada-segura-rpa'
