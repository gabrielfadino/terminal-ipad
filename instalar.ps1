# Terminal iPad - instalação automática no Windows
# Rode pelo arquivo instalar.bat (dois cliques). Pode rodar de novo quantas vezes precisar.

$ErrorActionPreference = 'Continue'
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $pasta
$log = Join-Path $pasta 'instalar-log.txt'
Start-Transcript -Path $log -Append | Out-Null

function Passo($t) { Write-Host ''; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   OK  $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   !!  $t" -ForegroundColor Yellow }
function Fim($cod) {
  Stop-Transcript | Out-Null
  Write-Host ''
  Read-Host 'Pressione Enter para fechar'
  exit $cod
}

# ---------------------------------------------------------------- 1. Diagnóstico
Passo 'Verificando o computador'
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$win = (Get-CimInstance Win32_OperatingSystem).Caption
Ok "$win, $ramGB GB de RAM"
if ($ramGB -lt 7) { Aviso 'Menos de 8 GB de RAM: o Terminal vai funcionar, mas o PC pode ficar lento.' }

$docker = Get-Command docker -ErrorAction SilentlyContinue
$dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $tailscale) {
  $ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
  if (Test-Path $ts) { $tailscale = Get-Item $ts }
}
if ($tailscale) { Ok 'Tailscale encontrado' } else { Aviso 'Tailscale não encontrado neste PC' }

# ---------------------------------------------------------------- 2. Docker Desktop
Passo 'Docker Desktop'
if (-not $docker -and -not (Test-Path $dockerDesktop)) {
  Aviso 'Docker Desktop não está instalado. Instalando agora (o Windows vai pedir permissão).'
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Aviso 'Este Windows não tem o winget. Baixe e instale o Docker Desktop: https://www.docker.com/products/docker-desktop'
    Fim 1
  }
  winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    Aviso 'A instalação automática falhou. Baixe e instale manualmente: https://www.docker.com/products/docker-desktop'
    Fim 1
  }
  Write-Host ''
  Aviso 'Docker Desktop instalado. REINICIE o computador, abra o Docker Desktop uma vez,'
  Aviso 'aceite os termos e depois rode o instalar.bat de novo.'
  Fim 0
}
Ok 'Docker Desktop instalado'

if (-not $docker) { $env:Path += ";$env:ProgramFiles\Docker\Docker\resources\bin" }

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host '   Ligando o Docker Desktop...'
  if (Test-Path $dockerDesktop) { Start-Process $dockerDesktop }
  $ligou = $false
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { $ligou = $true; break }
  }
  if (-not $ligou) {
    Aviso 'O Docker não ligou em 5 minutos. Abra o Docker Desktop, resolva o que ele pedir e rode de novo.'
    Fim 1
  }
}
Ok 'Docker funcionando'

# ---------------------------------------------------------------- 3. Senha
Passo 'Senha de acesso'
$env_ = Join-Path $pasta '.env'
if (-not (Test-Path $env_)) {
  $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'.ToCharArray()
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $bytes = New-Object byte[] 16
  $rng.GetBytes($bytes)
  $senha = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
  $conteudo = "SENHA=$senha`r`nSESSAO_OCIOSA_MIN=30`r`nSESSAO_MAX_HORAS=8`r`nATUALIZAR_REPO=gabrielfadino/terminal-ipad`r`nGITHUB_TOKEN=`r`n"
  [System.IO.File]::WriteAllText($env_, $conteudo, (New-Object System.Text.UTF8Encoding $false))
  Ok 'Senha criada e guardada no arquivo .env desta pasta'
} else {
  Ok 'Usando a senha que já está no arquivo .env'
  if (-not (Select-String -Path $env_ -Pattern '^ATUALIZAR_REPO=' -Quiet)) {
    Add-Content -Path $env_ -Value "ATUALIZAR_REPO=gabrielfadino/terminal-ipad`r`nGITHUB_TOKEN="
    Ok 'Botão "Atualizar sistema" configurado no .env'
  }
}
$linha = Select-String -Path $env_ -Pattern '^SENHA=' | Select-Object -First 1
$senhaAtual = $linha.Line.Substring(6)

# ---------------------------------------------------------------- 4. Computador virtual
Passo 'Montando e ligando o computador virtual (a primeira vez leva de 10 a 20 minutos)'
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
  Aviso 'Falhou ao montar o computador virtual. Veja o erro acima e o arquivo instalar-log.txt.'
  Fim 1
}
$pronto = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:8090/saude
    if ($r.Content -eq 'ok') { $pronto = $true; break }
  } catch {}
  Start-Sleep -Seconds 2
}
if ($pronto) { Ok 'Terminal ligado em http://localhost:8090' }
else { Aviso 'O Terminal ainda não respondeu. Veja com: docker compose logs' ; Fim 1 }

# ---------------------------------------------------------------- 5. Funnel
Passo 'Publicando pelo Funnel do Tailscale'
$endereco = ''
if ($tailscale) {
  & $tailscale funnel --bg 8090
  if ($LASTEXITCODE -eq 0) {
    $st = & $tailscale funnel status 2>&1 | Out-String
    $m = [regex]::Match($st, 'https://[^\s]+\.ts\.net')
    if ($m.Success) { $endereco = $m.Value }
    Ok 'Funnel ligado'
  } else {
    Aviso 'O Funnel não ligou. Libere o atributo "funnel" para este PC no painel do Tailscale (Access controls) e rode de novo.'
  }
} else {
  Aviso 'Instale o Tailscale neste PC (https://tailscale.com/download), entre na sua conta e rode de novo.'
}

# ---------------------------------------------------------------- Resumo
$resumo = @"
TERMINAL iPad - pronto

No PC:    http://localhost:8090
No iPad:  $(if ($endereco) { $endereco } else { '(endereço do Funnel ainda não disponível)' })
Senha:    $senhaAtual

No iPad 2, antes do primeiro acesso, instale os certificados (uma vez só):
  http://x1.i.lencr.org/   e   http://x2.i.lencr.org/
Depois abra o endereço acima, entre com a senha e use
Compartilhar > Adicionar à Tela de Início.
"@
$resumo | Set-Content -Encoding UTF8 (Join-Path $pasta 'ACESSO.txt')
Write-Host ''
Write-Host $resumo -ForegroundColor Green
Write-Host '(Estas informações também ficaram no arquivo ACESSO.txt desta pasta.)'
Fim 0
