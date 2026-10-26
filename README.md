<!-- Generated from private documentation source. Do not edit directly. Source SHA256: 77ce0c40ca3311c9e835c30cf40d5dc6c6888be49893e5b7d03566e8cf2e0d9d -->

# GDAM Actions

GitHub Actions for installing GDAM and publishing verified addon releases. Pin action references to a reviewed full commit SHA.

Use `install` with an exact `version` and reviewed `archive-sha256`. Use `publish` to register an existing immutable GitHub Release, or `release` to create one from verified ZIP bytes. Publishing requires `contents: read` and `id-token: write`; the release action also requires `contents: write`.

For development, install the [Komizo release](https://github.com/nicodes/komizo#install) matching `komizo.lock`, then run `komizo check`. CI retains real Linux and macOS installations and trusted-publishing refusal controls.
