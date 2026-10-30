<!-- Generated from private documentation source. Do not edit directly. Source SHA256: bd9c0265b9b5f5ae15e7bffa51f1964b4eb4aebe45aa78db7e82c8f07ec784e7 -->

# gdam Actions

GitHub Actions for installing gdam and publishing verified addon releases. Pin action references to a reviewed full commit SHA.

Use `install` with an exact `version` and reviewed `archive-sha256`. Use `publish` to register an existing immutable GitHub Release, or `release` to create one from verified ZIP bytes. Publishing requires `contents: read` and `id-token: write`; the release action also requires `contents: write`.

For development, install the [komizo release](https://github.com/nicodes/komizo#install) matching `komizo.lock`, then run `mise run check`. CI retains real Linux and macOS installations and trusted-publishing refusal controls.

## Contributor verification

Tool versions and native tasks live in `mise.toml`. Prepare the pinned helper source and run the complete gate:

```sh
git clone https://github.com/nicodes/tools.git .ci-tools
git -C .ci-tools checkout --detach 091101094fedf5ce2e67c339c1c9c842d6a662dc
mise install
mise run check
```

Native build and test commands retain source and output checks, with receipts in `.artifacts/verification`. Existing product release rules and artifacts remain owned by this repository. End users install the product’s published distribution.
