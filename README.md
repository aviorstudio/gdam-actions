# gdam-actions

GitHub Actions for [GDAM](https://github.com/aviorstudio/gdam), the Godot Addon
Manager. One definition of how to install the CLI and how to publish an addon,
shared by every repository that needs either.

## Install GDAM

```yaml
- uses: aviorstudio/gdam-actions/install@v0
```

Pin the version for reproducible runs:

```yaml
- uses: aviorstudio/gdam-actions/install@v0
  with:
    version: v0.0.7
```

| Input | Default | Purpose |
| ----- | ------- | ------- |
| `version` | `latest` | Release to install. `0.0.7` and `v0.0.7` are equivalent. |
| `install-dir` | `$RUNNER_TEMP/gdam-bin` | Where the binary goes. Needs no sudo. |

| Output | Purpose |
| ------ | ------- |
| `version` | What was installed, as `gdam --version` reports it. |

The binary is added to `PATH`, so later steps can just call `gdam`. The download
is checksum-verified against the release's `checksums.txt`.

## Publish to GDAM

```yaml
- uses: aviorstudio/gdam-actions/install@v0

- uses: aviorstudio/gdam-actions/publish@v0
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

Consumers should track the major tag, `@v0`. It moves forward with each release
in the 0.x line, so a fix reaches every repository without 17 pull requests.
Pin `@v0.1.0` instead if you want a release to stay put.

These actions are pre-1.0 on purpose: while the line is `0.x`, inputs may still
change between releases.

## License

MIT
