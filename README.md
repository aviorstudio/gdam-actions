<!-- Generated from private documentation source. Do not edit directly. Source SHA256: 6daf3445585d087060cb1b83f50773afe4014ea2cce1e1f0bc92aa07a56ae147 -->

# gdam Actions

GitHub Actions for installing gdam and publishing verified addon releases. Pin action references to a reviewed full commit SHA.

Use `install` with an exact `version` and reviewed `archive-sha256`. Use `publish` to register an existing immutable GitHub Release, or `release` to create one from verified ZIP bytes. Publishing requires `contents: read` and `id-token: write`; the release action also requires `contents: write`.

For development, install the [komizo release](https://github.com/nicodes/komizo#install) matching `komizo.lock`, then run `komizo check`. CI retains real Linux and macOS installations and trusted-publishing refusal controls.
