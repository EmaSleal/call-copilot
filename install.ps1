<#
Call Copilot installer for Windows.

Usage:
    irm https://raw.githubusercontent.com/EmaSleal/call-copilot/main/install.ps1 | iex

Installs call-copilot as a global command via pipx (no manual git clone
needed -- pipx clones the repo internally). Prompts once for which
optional components to install; the choice is saved to
$HOME\.call-copilot\install-profile so 'call-copilot update' can reinstall
later without asking again. Re-running this script (e.g. to switch
profiles) is safe.
#>

$RepoUrl = "https://github.com/EmaSleal/call-copilot.git"
$Branch = "main"
$AppHome = Join-Path $HOME ".call-copilot"

function Read-PromptWithDefault {
    param([string]$Message, [string]$Default = "")
    $reply = Read-Host $Message
    if ([string]::IsNullOrWhiteSpace($reply)) { return $Default }
    return $reply
}

# Todo el proceso vive en esta funcion (en vez de a nivel de script) porque
# el script se corre con 'irm ... | iex': ese codigo se ejecuta en el mismo
# scope de la consola interactiva, asi que un 'exit' ahi adentro no corta
# solo el script -- corta la sesion de PowerShell entera y cierra la
# ventana antes de que puedas leer el error. Adentro de una funcion,
# 'return' corta solo la funcion.
function Invoke-Install {
Write-Host "==============================================="
Write-Host "  Call Copilot - instalador"
Write-Host "==============================================="
Write-Host ""

# -- python ----------------------------------------------------------------
$pythonCmd = $null
foreach ($candidate in @("python", "py")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $pythonCmd = $candidate
        break
    }
}
if (-not $pythonCmd) {
    Write-Error "python no esta instalado. Instalalo desde python.org o la Microsoft Store y volve a correr este script."
    return 1
}

$pyVersionOutput = & $pythonCmd -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
$pyMajor, $pyMinor = $pyVersionOutput.Split(".")
if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 10)) {
    Write-Error "Se requiere Python >= 3.10 (encontrado $pyVersionOutput)."
    return 1
}

# -- pipx --------------------------------------------------------------------
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
    Write-Host "pipx no esta instalado -- instalando con pip..."
    & $pythonCmd -m pip install --user pipx
    if ($LASTEXITCODE -ne 0) { return 1 }
    & $pythonCmd -m pipx ensurepath
    if ($LASTEXITCODE -ne 0) { return 1 }
    Write-Host ""
    Write-Host "pipx se instalo. Puede que necesites abrir una terminal nueva"
    Write-Host "para que 'pipx' quede en el PATH. Volve a correr este script despues de eso."
    return 0
}

# -- perfil de instalacion ----------------------------------------------------
Write-Host "Que queres instalar?"
Write-Host "  1) Minimo   - solo llamadas en vivo (Deepgram + GPT/Claude/Ollama)"
Write-Host "  2) Completo - todo (Whisper local, video, catalogo de tools con RAG)"
Write-Host "  3) Elegir a mano"
$profileChoice = Read-PromptWithDefault "Elegi [1-3] (default: 1)" "1"

$extras = ""
switch ($profileChoice) {
    "1" { $extras = "" }
    "2" { $extras = "whisper-local,video,rag" }
    "3" {
        $reply = Read-PromptWithDefault "Whisper local para STT? [y/N]" "n"
        if ($reply -match "^[Yy]") { $extras = "whisper-local" }

        $reply = Read-PromptWithDefault "Procesar videos de YouTube? [y/N]" "n"
        if ($reply -match "^[Yy]") {
            if ($extras) { $extras = "$extras,video" } else { $extras = "video" }
        }

        $reply = Read-PromptWithDefault "Catalogo de tools con busqueda semantica (RAG)? [y/N]" "n"
        if ($reply -match "^[Yy]") {
            if ($extras) { $extras = "$extras,rag" } else { $extras = "rag" }
        }
    }
    default {
        Write-Warning "Opcion invalida -- instalo el perfil minimo."
        $extras = ""
    }
}

# -- instalacion ---------------------------------------------------------------
if ($extras) {
    $spec = "call-copilot[$extras] @ git+$RepoUrl@$Branch"
} else {
    $spec = "call-copilot @ git+$RepoUrl@$Branch"
}

Write-Host ""
Write-Host "Instalando: $spec"
# uninstall-then-install en vez de 'pipx install --force' -- mismo motivo que
# en install.sh: falla en desinstalar un paquete que todavia no existe
# (primera corrida), se ignora a proposito.
pipx uninstall call-copilot *> $null
pipx install $spec
if ($LASTEXITCODE -ne 0) { return 1 }

New-Item -ItemType Directory -Force -Path $AppHome | Out-Null
Set-Content -Path (Join-Path $AppHome "install-profile") -Value $extras -NoNewline

Write-Host ""
Write-Host "Listo. Corre 'call-copilot' para arrancar."
Write-Host "  Ctrl+S dentro de la app abre Configuracion (API keys, backends)."
Write-Host ""
Write-Host "Otros comandos:"
Write-Host "  call-copilot version        - version y commit instalado"
Write-Host "  call-copilot check-update   - avisa si hay una version nueva, sin instalarla"
Write-Host "  call-copilot update         - instala la ultima version"
Write-Host "  call-copilot doctor         - diagnostico (pipx, Python, extras, GPU)"
Write-Host "  call-copilot uninstall      - desinstala (tu config/datos en ~/.call-copilot quedan)"

return 0
}

$exitCode = 1
try {
    $exitCode = Invoke-Install
} catch {
    Write-Host ""
    Write-Host "Error inesperado: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    Write-Host ""
    Read-Host "Presiona Enter para cerrar esta ventana"
}
