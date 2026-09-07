#!/usr/bin/env bash
# ============================================================================
#  publish_to_github.sh
#  Publica el proyecto Bitácora GRM en el repositorio de GitHub del usuario.
#
#  Requisitos:
#    - git instalado
#    - gh (CLI de GitHub) autenticado,  O  variable GITHUB_TOKEN presente
#
#  Uso:
#    ./publish_to_github.sh
#  o, con token personal:
#    GITHUB_TOKEN=ghp_xxx ./publish_to_github.sh
# ============================================================================
set -euo pipefail

REPO_URL="https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM.git"
REPO_NAME="Bitacora-GRM"

cd "$(dirname "$0")"
echo "▶ Directorio: $(pwd)"

# 1) Identidad git
git config user.name  "MiniMax Agent"   2>/dev/null || true
git config user.email "agent@bitacora-grm.local" 2>/dev/null || true

# 2) Remote
if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "$REPO_URL"
fi
git remote set-url origin "$REPO_URL"
echo "✔ Remote configurado: $(git remote get-url origin)"

# 3) Push
if [ -n "${GITHUB_TOKEN:-}" ]; then
    AUTH_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/moisesarancibiasanchez-cpu/${REPO_NAME}.git"
    git remote set-url origin "$AUTH_URL"
    echo "▶ Push con token de GitHub…"
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo "▶ gh CLI autenticada, usando protocolo nativo…"
else
    echo "▶ Sin credenciales detectadas. Se pedirá usuario/contraseña o PAT."
    echo "   Consejo: export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx"
fi

git branch -M main
git push -u origin main
echo "✔ Push completado."
