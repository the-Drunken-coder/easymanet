# EasyMANET CLI

Public installable CLI and automation surface for EasyMANET.

This repository is generated from `the-Drunken-coder/easymanet`. Its job is to
publish the command-line tool that validates fleet files, renders node
provisioning payloads, lists disks, downloads or builds images, flashes media,
and exposes diagnostics-friendly workflows for humans, scripts, and local AI
agents.

## Install From Source

```bash
python -m pip install -e ".[dev]"
```

## Common Commands

```bash
easymanet validate --config fleet.yml
easymanet render --config fleet.yml --node point01
easymanet disks
easymanet flash --config fleet.yml --node point01 --device /dev/disk4 --base-image ./image.img.gz --dry-run
```

## Release Flow

The tiny bootstrap workflow accepts an intentional `repository_dispatch` or
manual trigger, then invokes the larger CLI release workflow. The release
workflow runs tests, builds the wheel and source distribution, uploads them as
artifacts, and creates a GitHub Release when a release tag is supplied.
