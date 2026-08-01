# gdam-actions

GitHub Actions for [GDAM](https://github.com/aviorstudio/gdam), the Godot Addon
Manager. One definition of how to install the CLI and how to publish an addon,
shared by every repository that needs either.

## Install GDAM

```yaml
- uses: aviorstudio/gdam-actions/install@v0.1.2
```

Pin the version for reproducible runs:

```yaml
- uses: aviorstudio/gdam-actions/install@v0.1.2
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
is checksum-verified against the release's `checksums.txt`.

## Publish to GDAM

```yaml
- uses: aviorstudio/gdam-actions/install@v0.1.2

- uses: aviorstudio/gdam-actions/publish@v0.1.2
  with:
    version: ${{ steps.release.outputs.version }}
    tag: ${{ steps.release.outputs.tag }}
    secret-key: ${{ secrets.GDAM_SECRET_KEY }}
```

| Input | Default | Purpose |
| ----- | ------- | ------- |
| `version` | required | Semver package version, e.g. `1.2.3`. |
| `tag` | required | GitHub release tag holding the asset, e.g. `v1.2.3`. |
| `addon` | `@<owner>/<repo>` | Addon spec. |
| `asset` | `@<owner>_<repo>.zip` | Release asset to publish. |
| `secret-key` | required | Owner-scoped key. Pass `secrets.GDAM_SECRET_KEY`. |

The defaults match what the addon release workflows already build, so a normal
addon repository only passes `version`, `tag`, and `secret-key`.

Publishing needs the CLI, so run `install` first — `publish` says so plainly
rather than failing with "gdam: command not found".

## Versioning

**Every release is its own tag, and no tag ever moves.** Pin one:

```yaml
- uses: aviorstudio/gdam-actions/install@v0.1.2
```

`@v0.1.2` resolves to the same files for as long as it exists, so upgrading is
a visible edit in a pull request and rolling back is naming the version before
it.

There used to be a moving `@v0` that each release repointed. It bought "a fix
reaches every repository without 17 pull requests" and cost the other half of
that sentence: a BAD release also reached every repository, immediately, with
no way to stay on the previous one short of finding its SHA by hand — and
nothing in a consumer's workflow recorded which files it was actually running.
Seventeen pull requests is the price of knowing.

A commit SHA is stronger still, because a tag can in principle be deleted and
recreated where a commit cannot.

These actions are pre-1.0 on purpose: while the line is `0.x`, inputs may still
change between releases. Read the release notes before bumping.

Releases are cut by the [Release workflow](.github/workflows/release.yml) —
`workflow_dispatch` with a `patch`/`minor`/`major` choice. It re-runs CI
against the commit first, then creates the tag and the release.

## License

MIT
