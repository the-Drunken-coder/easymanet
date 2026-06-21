# EasyMANET Product And Release Planning

Historical planning note: this document records product and release direction
from an earlier repo phase. The current product-surface layout source of truth
is [`docs/monorepo.md`](monorepo.md).

This document captures the current high-level design direction for
EasyMANET after discussing how the project could grow beyond a raw image
download and manual flashing workflow.

It is intentionally not an implementation plan. It does not prescribe a
final directory layout, package structure, workflow YAML, app framework
internals, or exact release scripts. The project may change before this
work is implemented, so this file records the product decisions, release
philosophy, reasoning, constraints, and tradeoffs that should survive
repo churn.

Implementation note: the private monorepo split now lives in
`docs/monorepo.md`. Public product repositories are generated from this repo;
the current publish tooling can create local previews, push generated contents,
and dispatch public release workflows when configured with credentials.

## Starting Point

EasyMANET began as a practical way to make OpenMANET deployment less
tedious. The current user journey is centered on defining a fleet,
building or downloading an image, flashing removable media, booting a
node, and verifying that the mesh came up correctly.

That is already a useful improvement over manually configuring every
OpenMANET node through a node-local web UI. But the rough edges are
still real:

- Users must find the correct image.
- Users must download and manage image files themselves.
- Users must identify the right removable disk.
- Users must run flashing commands correctly.
- Users must understand node roles before flashing.
- Users must diagnose first-boot failures from logs, network state, and
  boot reports.
- Users must know when an image is stale or incompatible with the fleet.

The proposed direction is to turn EasyMANET from "a repo that builds an
image and offers a CLI" into a local-first deployment system with three
product surfaces:

- A public image release surface.
- A public CLI and automation surface.
- A public desktop UI surface.

The private monorepo remains the source of truth for development and
release orchestration.

## Core Product Idea

EasyMANET should not merely publish firmware images. It should help a
person deploy and prove a working mesh.

The important product promise is:

> Define the fleet once, flash nodes safely, boot them, and get clear
> evidence that the mesh is healthy.

The desktop app idea is compelling because it can turn EasyMANET into a
usable operator console instead of a collection of expert commands. A
normal user should be able to open the app, see that no compatible image
is downloaded, click to download one, choose a node, choose a removable
device, flash safely, and then verify that the node came up.

The CLI remains important because EasyMANET should still be scriptable,
agent-friendly, and usable without a GUI. The GUI should present the
same underlying model rather than becoming a separate control plane.

## Major Design Decisions

### Keep A Private Monorepo As The Source Of Truth

The private monorepo should remain the place where the system is
designed, tested, and evolved. It can contain private experiments,
shared product decisions, release orchestration, generated assets, and
cross-cutting changes that touch images, CLI behavior, and the desktop
app together.

This avoids splitting active development across several repositories too
early. It also keeps shared concepts, such as fleet configuration,
target compatibility, image manifests, provisioning rules, and
diagnostics, from drifting between separate codebases.

The monorepo should be treated as the authoring environment. The public
repositories should be treated as distribution products.

### Publish To Public Product Repositories

The public repositories should exist because different users need
different entry points:

- Image users need a clean place to find image releases, checksums,
  build provenance, and compatibility metadata.
- CLI users need a focused repo for installing and automating
  EasyMANET.
- Desktop users need a focused repo for downloading the app, reporting
  app issues, and following app releases.

The public repos should not be edited manually during normal
development. They should be updated by a monorepo publish process. That
publish process should copy or generate the public contents, commit
them to the public repos, and trigger the appropriate public release
workflows.

The public repos are product surfaces, not independent sources of truth.

### Make Public Repos Build Their Own Releases

The image build can take around four hours. Running that in the private
monorepo is unattractive because private GitHub Actions minutes are
limited and potentially billable.

The better model is:

1. The private monorepo performs a small publish operation.
2. That operation updates the relevant public repo.
3. The public repo runs the heavy build and release workflow.
4. The public repo publishes the release artifacts.

This lets the private monorepo stay private while using public
repository CI for public release artifacts.

As of June 6, 2026, GitHub's public documentation says standard
GitHub-hosted runners are free for public repositories, while private
repositories use plan quota or paid minutes. It also lists a 6-hour job
execution limit for GitHub-hosted runners. Because the image build is
expected to take about four hours, this approach fits the current limit
but leaves only moderate headroom. These external constraints should be
re-verified before implementation.

Relevant GitHub documentation:

- [GitHub Actions billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub-hosted runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GitHub Actions limits](https://docs.github.com/en/actions/reference/limits)

### Use Small Public Bootstrap Workflows

Each public repo should have a small, stable bootstrap workflow whose
job is only to receive a trusted publish trigger and invoke the larger
release workflow for that repo.

The larger release workflow should also be part of the public repo
contents published from the monorepo. That means the monorepo can evolve
the public build and release logic over time without logging into the
public repos and hand-editing CI.

This gives the desired control model:

- The public repo pays the CI cost for its own public artifact.
- The private monorepo still controls the release logic.
- The bootstrap layer remains tiny and durable.
- The heavyweight workflow can evolve with the product.

The trigger mechanics should be explicit rather than accidental. GitHub
documents that events caused by a workflow's `GITHUB_TOKEN` generally do
not trigger new workflow runs, except for `workflow_dispatch` and
`repository_dispatch`. The release design should use an intentional
dispatch mechanism instead of relying on a push side effect.

Relevant GitHub documentation:

- [Triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [GITHUB_TOKEN behavior](https://docs.github.com/en/actions/concepts/security/github_token)

### Keep The Desktop App Local-First

The desktop app should be a local deployment console, not a cloud
management service.

It should help users:

- Discover compatible image releases.
- Download images.
- Cache images locally.
- Remove stale images.
- Validate fleet configuration.
- Choose which node to flash.
- Choose a removable disk safely.
- Flash without command-line work.
- Read local boot reports.
- Run local network and SSH health checks where possible.
- Export diagnostics for humans or AI agents.

The app should not trap the user's project state inside an opaque app
database. It should read and write ordinary project files where
reasonable. That keeps the app compatible with the CLI, editors, scripts,
and local AI agents.

### Keep The CLI As The Automation Spine

The CLI should remain the stable automation surface. The desktop app can
wrap it or share its underlying engine, but the user should not lose
power by choosing the CLI.

This is important for several reasons:

- The CLI is easier to test in CI.
- The CLI is easier for AI agents to operate.
- The CLI is useful on machines where the desktop app is unavailable.
- The CLI provides a durable fallback when GUI behavior is confusing.
- The CLI can expose low-level diagnostics without crowding the UI.

The GUI should make common workflows pleasant. The CLI should make the
system composable.

### Treat Disk Flashing As A Safety-Critical Operation

The desktop app can make flashing approachable, but it must not make it
casual.

Disk flashing can destroy user data. The safety logic should be strict,
testable, and shared with the CLI or core engine. The app should never
silently choose a target disk. It should make the user confirm the
device, show enough detail to identify it, and refuse obviously unsafe
targets by default.

The product should continue to treat whole-disk validation, removable
device detection, dry-run previews, explicit confirmation, unmounting,
syncing, and ejecting as central behavior rather than incidental
implementation details.

### Make Image Releases Manifest-Driven

Images should not be discovered by filename guessing alone. Public image
releases should include machine-readable metadata that allows the CLI
and app to answer questions like:

- Which target hardware does this image support?
- Which OpenMANET version is included?
- Which EasyMANET version or source commit produced it?
- What is the checksum?
- What release channel is this?
- Is this image compatible with the current fleet?
- Is this local image stale?

This manifest concept is important even if the exact format changes
later. It turns image management from a file-picker problem into a
product workflow.

### Preserve Agent Compatibility

One explicit goal is to let local AI agents such as Codex, OpenCode, or
Claude interact with the same project state that the desktop app uses.

That means the system should prefer transparent local files, predictable
logs, explicit command surfaces, and exportable diagnostics over hidden
state. An agent should be able to update a fleet definition, run
validation, inspect release metadata, review flash logs, or summarize a
diagnostic bundle without reverse-engineering the app.

The desktop app should be friendly for humans, but it should not become
the only place where state exists.

## Public Repository Roles

### Public Image Repository

The public image repo is the public artifact factory for firmware
images.

Its main responsibility is to build, verify, and publish image releases.
It should expose release artifacts, checksums, manifests, provenance,
release notes, and any relevant build logs or diagnostic metadata.

The image repo should not become the normal development home for
provisioning behavior. Changes should originate in the private monorepo
and be published outward.

### Public CLI Repository

The public CLI repo is the installable automation product.

Its main responsibility is to expose EasyMANET's local workflows to
power users, scripts, and agents. It should make fleet validation,
rendering, disk listing, flashing, image management, and diagnostics
available without the desktop app.

The CLI should be considered part of the product, not just a developer
tool. It is the stable contract underneath automation.

### Public Desktop Repository

The public desktop repo is the human-facing operator console.

Its main responsibility is to make the common deployment path feel
simple: get an image, choose a fleet node, choose a safe removable disk,
flash the node, and verify health.

The desktop repo should publish app releases and make issue reporting
straightforward for users who may never touch the CLI directly.

## Release Philosophy

A release from the private monorepo should be intentional. It should not
be a random synchronization.

The publish operation should record what was released, where it went,
which public commits were produced, which public workflows were
triggered, and which artifacts were published.

Each public artifact should carry enough provenance to answer:

- Which monorepo source produced this?
- Which public repo commit built this?
- Which workflow built this?
- Which input version or release channel was requested?
- What checksums or signatures identify the artifact?

The system should make it hard to confuse a source publish with a
finished release. Copying files to a public repo is only the start of
the release. The public build, verification, and artifact publication
complete it.

## Security And Trust

The release pipeline will become part of the supply chain for firmware
that users flash onto hardware. It should be treated with more care than
ordinary project automation.

Important principles:

- Use narrowly scoped credentials for publishing from the private
  monorepo to public repos.
- Prefer a GitHub App or fine-grained token over broad personal tokens.
- Restrict who or what can write to the public repos.
- Avoid manual edits in public repos during normal development.
- Pin third-party Actions where possible.
- Give workflows the minimum permissions they need.
- Record source provenance in every release.
- Publish checksums for large artifacts.
- Consider signatures once the release pipeline stabilizes.

The image repo is especially sensitive because users will trust its
outputs enough to write them to SD cards.

## Why This Is Better Than A Single Public Repo

A single public repo is simpler at first, but it mixes several concerns:

- Private planning and public product work.
- Heavy image builds and lightweight CLI or app changes.
- User-facing app issues and low-level image builder issues.
- Release artifacts and development internals.

The proposed model keeps the public surface clean while preserving a
single private development brain.

The tradeoff is release orchestration complexity. That complexity is
acceptable only if the publish process remains disciplined and
automated.

## Why This Is Better Than Fully Separate Public Repos

Fully separate public repos would make each product surface clean, but
shared behavior could drift quickly.

EasyMANET has several concepts that need to stay aligned:

- Fleet configuration.
- Node roles.
- Target hardware.
- Image compatibility.
- Disk flashing safety.
- Boot report interpretation.
- Mesh health checks.
- Release provenance.

If those concepts are edited independently in separate repos, the CLI,
app, and image builder can slowly disagree. The private monorepo avoids
that by making public repos outputs rather than peer sources of truth.

## Non-Goals For This Planning Phase

This planning phase does not decide:

- The final monorepo layout.
- The final public repo names.
- The final programming language boundaries.
- The final desktop framework.
- The exact workflow YAML.
- The exact image manifest schema.
- The exact packaging system.
- The exact release command.
- The exact credential setup.
- The final CI cache strategy.

Those choices should be made when implementation starts and the actual
repo state is known.

## Risks

### Public Repos Could Drift

If anyone starts manually editing the public repos, they can stop being
generated product surfaces and become parallel sources of truth.

The mitigation is cultural and technical: document that public repos are
generated, protect important branches, and make the monorepo publish
flow the normal path for changes.

### Release Automation Could Become Too Clever

The publish pipeline could become hard to understand if it tries to do
too much.

The mitigation is to keep the private publish step simple and make each
public repo responsible for its own build and release.

### Four-Hour Builds Have Little Headroom

The current image build estimate leaves room under GitHub's documented
6-hour hosted-runner job limit, but not a large amount.

The mitigation is to watch build duration, cache carefully, split work
where possible, and be ready to use self-hosted or specialized runners
if the build grows beyond public runner limits.

### GUI Scope Could Expand Too Far

A desktop deployment app can easily turn into a cloud dashboard,
monitoring system, topology mapper, remote management plane, and support
portal.

The mitigation is to keep the first desktop product local-first and
deployment-focused.

### Disk Flashing Mistakes Are High Impact

The app could make a destructive operation feel too easy.

The mitigation is to treat disk safety as core product behavior, not UI
decoration.

## Open Questions For Later

- Should the desktop app be Electron, Tauri, or another shell?
- Should the desktop app call the CLI as a subprocess or share a core
  library directly?
- What exact release channels should exist?
- How should image signatures be handled?
- Should public repos accept outside pull requests, and if so, how are
  those changes imported back into the private monorepo?
- How much historical image retention should the app support locally?
- Should the public image repo publish to GitHub Releases only, or also
  to another artifact store?
- What health checks belong in the first version of the desktop app?
- What is the right support bundle format for diagnostics?

## Durable Direction

The durable direction is:

EasyMANET should become a local-first mesh deployment system with a
private monorepo as the authoring source, generated public repos as
product surfaces, public CI as the heavy release builder, a CLI as the
automation spine, and a desktop app as the human operator console.

The system should make the easy path safer than the manual path, while
still leaving enough transparent state for power users, scripts, and AI
agents to understand and operate it.
