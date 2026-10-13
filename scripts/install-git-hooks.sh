#!/usr/bin/env bash
# Install this repo's git hooks (currently: a gitleaks pre-commit secret scan).
# Run once after cloning: ./scripts/install-git-hooks.sh
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)"
cp "$REPO_ROOT/githooks/pre-commit" "$REPO_ROOT/.git/hooks/pre-commit"
chmod +x "$REPO_ROOT/.git/hooks/pre-commit"
echo "Installed pre-commit secret scan hook into $REPO_ROOT/.git/hooks/pre-commit"

if ! command -v gitleaks >/dev/null 2>&1; then
  echo
  echo "NOTE: gitleaks is not on your PATH yet, so the hook will no-op until you install it."
  echo "  Fedora/RHEL: sudo dnf install -y gitleaks"
  echo "  Or: https://github.com/gitleaks/gitleaks#installing"
fi
