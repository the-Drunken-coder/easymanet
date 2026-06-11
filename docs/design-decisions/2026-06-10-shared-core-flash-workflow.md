# Shared Core Flash Workflow

## Status

Accepted

## Context

The CLI and desktop both need the same flash behavior: resolve a fleet, validate
the selected node, choose an image, check disk safety, write the image, stage the
boot payload, and finish/eject. Keeping that orchestration in the CLI made the
desktop depend on terminal text and an app-to-app import.

## Decision

Own flash orchestration in `packages/core` as a structured workflow API. The CLI
and desktop bridge are presenters: they pass options, receive events and
results, and decide how to display them.

## Consequences

Flash behavior has one implementation and one set of result/error codes.
Terminal wording can change without breaking desktop integration, and desktop
users can receive progress events during long writes.
