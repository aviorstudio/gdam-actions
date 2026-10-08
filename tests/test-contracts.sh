#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
assert_installer_pin() {
  local action_file="$1"
  if ! grep -Eq 'raw\.githubusercontent\.com/aviorstudio/gdam/[0-9a-f]{40}/scripts/install_cli\.sh' "$action_file"; then
    echo 'installer script source must use a full 40-character commit SHA, not mutable main' >&2
    return 1
  fi
  if grep -Fq 'aviorstudio/gdam/main/scripts/install_cli.sh' "$action_file"; then
    echo 'installer script source must use a full 40-character commit SHA, not mutable main' >&2
    return 1
  fi
}

assert_installer_pin "$root/install/action.yml"
cp "$root/install/action.yml" "$tmp/mutated-install.yml"
perl -0pi -e 's#/aviorstudio/gdam/[0-9a-f]{40}/scripts#/aviorstudio/gdam/main/scripts#' "$tmp/mutated-install.yml"
if assert_installer_pin "$tmp/mutated-install.yml" >"$tmp/pin.out" 2>"$tmp/pin.err"; then
  echo 'mutable installer source should fail the pin gate' >&2
  exit 1
fi
grep -F 'installer script source must use a full 40-character commit SHA, not mutable main' "$tmp/pin.err"

# Publishing no longer needs the CLI or any registry credential: the only
# secret-shaped input left anywhere in this repository is the OIDC request
# token GitHub injects, which must never be echoed.
if grep -rn 'secret-key\|GDAM_SECRET_KEY' "$root/publish" "$root/release" "$root/install" "$root/.github/workflows"; then
  echo 'publication must not accept or forward a GDAM secret key' >&2
  exit 1
fi
if ! grep -Eq '^\s+id-token: write$' "$root/.github/workflows/ci.yml"; then
  echo 'CI must grant id-token: write so the publish guard runs the real token path' >&2
  exit 1
fi

echo 'contract tests passed'
