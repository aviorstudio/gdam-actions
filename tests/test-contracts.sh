#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/gdam" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -eq 1 ] && [ "$1" = publish ]; then
  if [ -n "${GDAM_SECRET_KEY+x}" ]; then
    echo 'compatibility probe inherited GDAM_SECRET_KEY' >&2
    exit 2
  fi
  case "${FAKE_GDAM_CONTRACT:?}" in
    exact) echo 'usage: gdam publish @username/addon TAG [ASSET_NAME]' >&2 ;;
    old) echo 'usage: gdam publish @username/addon VERSION RELEASE_TAG [ASSET_NAME]' >&2 ;;
    mutated) echo 'usage: gdam publish something unexpected' >&2 ;;
  esac
  exit 2
fi
printf '%s\n' "$@" > "${FAKE_GDAM_ARGS:?}"
STUB
chmod +x "$tmp/bin/gdam"

run_publish() {
  PATH="$tmp/bin:$PATH" \
    GDAM_SECRET_KEY='test-placeholder-not-a-secret' \
    GDAM_PUBLISH_ADDON='@aviorstudio/example' \
    GDAM_PUBLISH_TAG='Release-V1.2.3' \
    GDAM_PUBLISH_ASSET="${1:-}" \
    FAKE_GDAM_CONTRACT="${2:-exact}" \
    FAKE_GDAM_ARGS="$tmp/args" \
    bash "$root/publish/publish.sh"
}

run_publish '@aviorstudio_example.zip'
printf '%s\n' publish '@aviorstudio/example' 'Release-V1.2.3' '@aviorstudio_example.zip' > "$tmp/expected"
cmp "$tmp/expected" "$tmp/args"

run_publish
printf '%s\n' publish '@aviorstudio/example' 'Release-V1.2.3' > "$tmp/expected"
cmp "$tmp/expected" "$tmp/args"

rm -f "$tmp/args"
if run_publish '' old >"$tmp/old.out" 2>"$tmp/old.err"; then
  echo 'old VERSION RELEASE_TAG contract should fail' >&2
  exit 1
fi
grep -F 'released v0.0.7 publish contract (VERSION RELEASE_TAG)' "$tmp/old.err"
test ! -e "$tmp/args"

if run_publish '' mutated >"$tmp/mutated.out" 2>"$tmp/mutated.err"; then
  echo 'unknown mutated CLI contract should fail closed' >&2
  exit 1
fi
grep -F 'unsupported publish command contract' "$tmp/mutated.err"
test ! -e "$tmp/args"

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

echo 'contract tests passed'
