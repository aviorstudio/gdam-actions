#!/usr/bin/env bash
set -euo pipefail

# A missing key otherwise surfaces as an authorization failure from the
# registry, which reads like the key is wrong rather than absent.
if [ -z "${GDAM_SECRET_KEY:-}" ]; then
  echo 'Missing required secret: GDAM_SECRET_KEY' >&2
  exit 1
fi

if ! command -v gdam >/dev/null 2>&1; then
  echo 'gdam is not on PATH — run aviorstudio/gdam-actions/install first' >&2
  exit 1
fi

if [ -z "${GDAM_PUBLISH_TAG:-}" ]; then
  echo 'Missing required exact GitHub Release tag' >&2
  exit 1
fi

if [ -z "${GDAM_PUBLISH_ADDON:-}" ] && [ -z "${GITHUB_REPOSITORY:-}" ]; then
  echo 'Cannot derive addon: GITHUB_REPOSITORY is empty; pass the addon input' >&2
  exit 1
fi
addon="${GDAM_PUBLISH_ADDON:-@${GITHUB_REPOSITORY}}"

# Probe only the local argument-count usage gate. At both released v0.0.7 and
# the exact-tag CLI on gdam/main, this exits 2 before reading the secret or
# constructing an API client. Fail closed for unknown command shapes so this
# action never guesses which positional argument contains release identity.
# Do not expose the key even to the compatibility probe. Only the real publish
# invocation below receives it.
publish_usage="$(env -u GDAM_SECRET_KEY gdam publish 2>&1 || true)"
case "$publish_usage" in
  *'usage: gdam publish @username/addon TAG [ASSET_NAME]'*) ;;
  *'usage: gdam publish @username/addon VERSION RELEASE_TAG [ASSET_NAME]'*)
    echo 'Installed gdam uses the released v0.0.7 publish contract (VERSION RELEASE_TAG); the exact-tag action requires the CLI release tracked by aviorstudio/gdam-be#80' >&2
    exit 1
    ;;
  *)
    echo 'Installed gdam has an unsupported publish command contract; expected exact TAG [ASSET_NAME] usage' >&2
    exit 1
    ;;
esac

if [ -n "${GDAM_PUBLISH_ASSET:-}" ]; then
  echo "Publishing $addon from exact tag $GDAM_PUBLISH_TAG (asset: $GDAM_PUBLISH_ASSET)"
  gdam publish "$addon" "$GDAM_PUBLISH_TAG" "$GDAM_PUBLISH_ASSET"
else
  echo "Publishing $addon from exact tag $GDAM_PUBLISH_TAG (automatic single-asset selection)"
  gdam publish "$addon" "$GDAM_PUBLISH_TAG"
fi
