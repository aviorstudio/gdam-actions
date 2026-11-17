<!-- Generated from private documentation source. Do not edit directly. Source SHA256: 84d7d4f1c5255ce2b07f6ba6266a01165dd2015f3f8662c2733bc324466887bb -->

# gdam Actions

GitHub Actions for installing gdam and publishing verified addon releases. Pin action references to a reviewed full commit SHA.

Use `install` with an exact `version` and reviewed `archive-sha256`. Use `publish` to register an existing immutable GitHub Release, or `release` to create one from verified ZIP bytes. Publishing requires `contents: read` and `id-token: write`; the release action also requires `contents: write`.

For development, install the tool versions in `mise.toml`, prepare the pinned Tools helper checkout described below, then run `mise run check`. CI retains real Linux and macOS installations and trusted-publishing refusal controls.

## Contributor verification

Tool versions and native tasks live in `mise.toml`. Prepare the pinned helper source and run the complete gate:

```sh
git clone https://github.com/nicodes/tools.git .ci-tools
git -C .ci-tools checkout --detach 71540eb673ebd47162de3b78bb6ffbf77605d2ab
mise install
mise run check
```

Native build and test commands retain source and output checks, with receipts in `.artifacts/verification`. Existing product release rules and artifacts remain owned by this repository. End users install the product’s published distribution.

## Contributor task interface

Contributor tool versions and task entry points live in the native Mise configuration. Use `mise run lint` for source checks, `mise run test` for the applicable behavioral tests, and `mise run check` for the complete supported gate. `mise run clean` removes declared generated outputs while preserving source, credentials and retained data. This package has no application development service.
