# EasyMANET Desktop

Public desktop operator-console surface for EasyMANET.

This repository is generated from `the-Drunken-coder/easymanet`. It contains
the local-first desktop app that helps users choose fleet nodes, choose
removable media safely, preview the flash plan, flash nodes, and inspect local
boot or network evidence.

The generated desktop repo now includes the Electron shell, the Python bridge,
and the GitHub Actions release plumbing needed to build packaged artifacts for
macOS and Windows from checked-in source.

## Release Flow

The tiny bootstrap workflow accepts an intentional `repository_dispatch` or
manual trigger, then invokes the larger desktop release workflow. That workflow
installs the desktop repo, freezes the Python bridge with PyInstaller, and
builds the Electron artifacts for release.
