<!-- Generated from private documentation source. Do not edit directly. Source SHA256: 694b88b39eb1ad4c2e7b2e4868c78f423cdf7ae97352b7318aa20b3a920a9637 -->

# gdam-actions

GitHub Actions for [GDAM](https://github.com/aviorstudio/gdam), the Godot Addon
Manager. One definition of how to install the CLI and how to publish an addon,
shared by every repository that needs either.

## Install GDAM

```yaml
- uses: aviorstudio/gdam-actions/install@v0.0.1
```

Pin the version for reproducible runs:

```yaml
- uses: aviorstudio/gdam-actions/install@v0.0.1
  with:
    version: v0.0.7
```

| Input | Default | Purpose |
| ----- | ------- | ------- |
| `version` | `latest` | Release to install. `0.0.7` and `v0.0.7` are equivalent. |
| `token` | `${{ github.token }}` | Authenticates the API call that resolves `latest`. The default is almost always right — pass one only if the release lives somewhere the workflow's own token cannot read. |
| `archive-sha256` | empty | Reviewed archive SHA256; requires an exact release version. |
| `install-dir` | `$RUNNER_TEMP/gdam-bin` | Where the binary goes. Needs no sudo. |

| Output | Purpose |
| ------ | ------- |
| `version` | What was installed, as `gdam --version` reports it. |

The binary is added to `PATH`, so later steps can just call `gdam`. The download
is checksum-verified against the release's `checksums.txt`. The installer script
itself is fetched from a full `gdam` commit SHA rather than mutable `main`; the
checksum verification remains part of that pinned script.

## Publish to GDAM

```yaml
jobs:
  publish:
    permissions:
      contents: read   # read the release and its asset
      id-token: write  # mint the GitHub Actions OIDC token the registry trusts
    steps:
      - uses: aviorstudio/gdam-actions/publish@v0.3.0
        with:
          tag: ${{ steps.release.outputs.tag }}
```

`v0.3.0` publishes by **trusted publishing**: the action reads the GitHub
Release named by `tag`, picks one asset, downloads it to hash its bytes, and
posts the release facts (release id, asset id, name, size, SHA256, target
commit, `published_at`, `prerelease`) to `POST /api/v1/publish` with the job's
GitHub Actions OIDC token for audience `api.gdam.dev`. There is no registry
credential: the registry trusts the token's repository identity. `GDAM_SECRET_KEY`
and the `secret-key` input are gone, the GDAM CLI is no longer needed to
publish, and `install` is unchanged.

| Input | Default | Purpose |
| ----- | ------- | ------- |
| `tag` | required | Exact, case-sensitive GitHub Release tag, e.g. `v1.2.3`. |
| `addon` | `@<owner>/<repo>` | Addon spec. The owner must be the workflow's GitHub organisation. |
| `asset` | automatic | Exact asset name. Omit when the release has exactly one asset or one named `@<owner>_<addon>.gdam.zip`. |
| `api-url` | `https://api.gdam.dev` | Registry base URL. |
| `audience` | `api.gdam.dev` | OIDC token audience the registry expects. |
| `editor-plugin` | empty | `true` marks the addon as an editor plugin; the registry records it only when this publish creates the addon. |
| `token` | `${{ github.token }}` | Reads the release and downloads the asset for hashing. |

| Output | Purpose |
| ------ | ------- |
| `created` | `true` for a new registry row; `false` when the registry already held identical facts (a re-run is idempotent). |
| `sha256` | SHA256 of the published asset bytes. |

The registry's policy, which the action cannot work around:

- The token's `repository_owner` must equal the addon's owner handle, so
  `@aviorstudio/*` is published only by workflows of `github.com/aviorstudio/*`.
  The first publish binds the addon to the workflow's repository; later
  publishes must come from the same repository.
- `commit_sha` must equal the commit the workflow checked out (the token's
  `sha`). The action resolves the tag's commit and fails early, before any token
  is minted, when it differs from `GITHUB_SHA`. A `workflow_dispatch` from
  `main` therefore publishes only a release whose tag points at `main`'s head.
- The run must be a `push`, `release` or `workflow_dispatch` event on a branch
  or tag ref, never a pull request.
- A tag already recorded with identical facts answers `200` (success, `created:
  false`); different facts under the same tag, or the same GitHub release under
  another tag, answer `409` and the action fails with the registry's message.

If GitHub declares an asset `digest`, it must match the downloaded bytes; a
mismatch, a size mismatch or a draft release fails before anything is sent.
The action prints the registry's response and never prints either token.

No separate semantic package version is accepted or sent. Release identity is
the one exact tag, preserved byte-for-byte; `Release-V1.2.3` and
`release-v1.2.3` are different tags.

### Release (tested ZIP) action

`aviorstudio/gdam-actions/release` creates the GitHub Release from a ZIP the
same job verified and then runs `publish` on it. Its `secret-key` input is
gone too; the job needs `contents: write` and `id-token: write`.

### Earlier releases

`v0.2.0` and earlier shelled out to `gdam publish` with an owner-scoped
`secret-key`. The registry no longer fills release facts in from GitHub, so
those releases (and CLI v0.0.8 `gdam publish`) can no longer publish. Upgrade
the pin, add `id-token: write`, and delete the `GDAM_SECRET_KEY` secret.

## Versioning

Every release has its own tag, and repository policy is never to move one. Pin
one:

```yaml
- uses: aviorstudio/gdam-actions/install@v0.0.1
```

**Correction:** earlier documentation called those tags immutable. Git tags can
be moved or deleted; GitHub documents a full 40-character commit SHA as the only
immutable action pin. Prefer a verified full SHA when that guarantee is needed.
Version tags remain the readable project convention and are protected by the
release workflow's no-overwrite check and the repository's no-move policy.

There used to be a moving `@v0` that each release repointed. It bought "a fix
reaches every repository without 17 pull requests" and cost the other half of
that sentence: a BAD release also reached every repository, immediately, with
no way to stay on the previous one short of finding its SHA by hand — and
nothing in a consumer's workflow recorded which files it was actually running.
Seventeen pull requests is the price of knowing.

A commit SHA is the immutable option because a tag can be deleted and recreated.

These actions are pre-1.0 on purpose: while the line is `0.x`, inputs may still
change between releases. Read the release notes before bumping.

Releases are cut by the [Release workflow](https://github.com/aviorstudio/gdam-actions/blob/39fec1638576d27bd5c1195e7b6117d0a6b4bb3e/.github/workflows/release.yml) —
`workflow_dispatch` with a `patch`/`minor`/`major` choice. It re-runs CI
against the commit first, then creates the tag and the release.

## License

MIT
