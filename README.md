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
- uses: aviorstudio/gdam-actions/install@v0.0.2
  with:
    version: v0.0.8

- uses: aviorstudio/gdam-actions/publish@v0.0.2
  with:
    tag: ${{ steps.release.outputs.tag }}
    secret-key: ${{ secrets.GDAM_SECRET_KEY }}
```

`v0.0.2` is the first action release for the exact-tag contract and requires
GDAM CLI v0.0.8 or newer. The public action release `v0.0.1` and CLI release
v0.0.7 implement the old contract described below.

| Input | Default | Purpose |
| ----- | ------- | ------- |
| `tag` | required | Exact, case-sensitive GitHub Release tag, e.g. `v1.2.3`. |
| `addon` | `@<owner>/<repo>` | Addon spec. |
| `asset` | automatic | Exact asset name. Omit only when the release has exactly one asset. |
| `secret-key` | required | Owner-scoped key. Pass `secrets.GDAM_SECRET_KEY`. |

No separate semantic package version is accepted or sent. Release identity is
the one exact tag, preserved byte-for-byte; `Release-V1.2.3` and
`release-v1.2.3` are different tags. If a release has multiple assets, pass the
exact `asset` selector.

Publishing needs the CLI, so run `install` first — `publish` says so plainly
rather than failing with "gdam: command not found".

### Coordinated release compatibility

The public `gdam` CLI release **v0.0.8** provides the exact-tag publish command.
This action fails closed with a specific compatibility message when it detects
the old v0.0.7 `VERSION RELEASE_TAG` command (or an unknown command shape),
before publishing or making a registry request.

The public action release `v0.0.1` remains on the old two-identity contract.
This release does not alter that tag or claim that it supports exact tags. Use
`v0.0.2` with CLI v0.0.8 for the exact-tag contract.

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

Releases are cut by the [Release workflow](.github/workflows/release.yml) —
`workflow_dispatch` with a `patch`/`minor`/`major` choice. It re-runs CI
against the commit first, then creates the tag and the release.

## License

MIT
