# EasyMANET Desktop

Public desktop operator-console surface for EasyMANET.

This repository is generated from `the-Drunken-coder/easymanet`. It is reserved
for the local-first desktop app that will help users download compatible images,
choose fleet nodes, choose removable media safely, flash nodes, and inspect
local boot or network evidence.

The first generated version intentionally contains product direction and release
plumbing rather than app code. The desktop framework and app internals are still
an authoring-repo decision.

## Release Flow

The tiny bootstrap workflow accepts an intentional `repository_dispatch` or
manual trigger, then invokes the larger desktop release workflow. Until app code
exists, that workflow publishes a provenance artifact only, so the release path
is wired without pretending a desktop binary exists.
