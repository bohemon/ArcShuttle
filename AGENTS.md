# ArcShuttle Repository Instructions

This file applies to the entire repository. More specific `AGENTS.md` files may add
rules for a subtree, but they must not weaken the compatibility, safety, or verification
requirements below.

## Project direction

- The product name is **ArcShuttle**. The current release target is version 0.3.1.
- The distribution, primary Python package, and primary CLI are all named `arcshuttle`.
- `parxtract` remains a compatibility surface. Do not remove or silently change its CLI,
  Python-module entry point, manifest v1 support, JSON Lines contract, or exit behavior.
- Historical roadmap ordering is not an instruction to reopen completed issues. Track new work
  in its own issue and follow the dependencies recorded there.

## Branching and integration

Use trunk-based development. `main` is the only permanent branch and must remain green and
releasable.

1. Start from an up-to-date, clean `main`. Preserve any user changes; never discard them to
   make a branch or test pass.
2. Every change must have a GitHub issue with scope and acceptance criteria.
3. Create a short-lived branch from `main` for one reviewable change:
   - Codex-created work: `codex/<issue>-<slug>`
   - Feature work: `feat/<issue>-<slug>`
   - Fixes: `fix/<issue>-<slug>`
   - Documentation: `docs/<issue>-<slug>`
   - Maintenance: `chore/<issue>-<slug>`
4. Open a pull request; never push implementation commits directly to `main`.
5. Require the `required` CI check, an up-to-date branch, and resolved conversations before
   merge.
6. Squash-merge the pull request and delete its branch after merge.

An issue may use several pull requests when that makes review safer. Intermediate pull
requests use `Refs #N`; only the final pull request uses `Closes #N`. Separate mechanical
moves from behavior changes, and do not mix unrelated cleanup into a feature pull request.

Avoid stacked pull requests by default. When dependency work truly must proceed in parallel,
base the dependent pull request on the prerequisite branch, state the dependency prominently,
and do not merge it first. After the prerequisite merges, rebase the dependent branch onto
`main`, retarget it to `main`, and rerun all checks. After issue #5, issues #6 and #7 may run
independently from the same updated `main`.

Do not create `develop` or a long-lived release branch for an ordinary release. Tag releases
from verified `main`. Add a maintenance branch such as `0.3.x` only when an older release must
be supported in parallel with later development.

## Commits and pull requests

- Use focused commits and Conventional Commit subjects such as `feat:`, `fix:`, `docs:`,
  `test:`, `refactor:`, and `chore:`.
- Use an imperative, outcome-oriented pull-request title suitable for the squash commit.
- Explain user-visible behavior, safety or compatibility effects, and verification in the
  pull-request body.
- Keep generated files, caches, build output, virtual environments, and editor state out of
  commits.
- Do not rewrite or force-push a branch after review has started unless necessary; explain
  the reason when it is necessary.

## Required verification

Run checks in proportion to the change, and always run the complete gate before declaring an
implementation issue complete:

```sh
hatch run check
```

Run `hatch build` for packaging, entry-point, PowerShell-module, or documentation-inclusion
changes. Issue #12 additionally requires installing the wheel into a clean temporary
environment and smoke-testing both `arcshuttle` and `parxtract` entry points.

Tests must run on Windows and Linux and must not require a real 7-Zip installation. Extend the
fake 7-Zip executable for deterministic behavior. A real-7-Zip test may only be an optional,
skip-when-unavailable integration test. Add a regression test with every bug fix.

The GitHub Actions `required` job is the stable branch-protection check. It must depend on the
complete supported OS/Python matrix and fail unless the entire matrix succeeds. Do not rename
or bypass it without updating the protection rule in the same governance change.

## Compatibility and safety invariants

- Support Python 3.11 and later on Windows and Linux.
- Keep runtime dependencies empty unless a dependency is clearly justified, documented in
  the dependency policy, and covered by packaging tests.
- Keep stdout machine-readable UTF-8 JSON Lines. Send diagnostics and progress to stderr.
- Validate complete manifests and output collisions before starting any job.
- Preserve manifest v1 execution while adding schema v2. Reject unknown schemas, operations,
  missing required fields, and integrity failures before job start with exit 64.
- Never delete, move, or modify source archives or create sources.
- Never destructively overwrite an existing output.
- Never move or delete existing `.parxtract` data or failed staging directories during the
  ArcShuttle migration.
- Only delete or rename staging paths after verifying ArcShuttle's ownership marker.
- Invoke 7-Zip with an argument array, `shell=False`, and closed stdin. Never concatenate
  filenames into shell command strings or accept arbitrary raw 7-Zip options.
- Preserve CPU, process, and I/O resource invariants across mixed operations.
- Treat symlinks, junctions/reparse points, devices, sockets, and other non-regular create
  inputs conservatively; do not follow them.

## Editing and documentation

- Inspect before editing. Prefer `rg` and `rg --files` for repository searches.
- Preserve unrelated and uncommitted user changes.
- Use `apply_patch` for hand-authored file changes.
- Keep English and Japanese manuals aligned. Update documentation coverage tests whenever
  commands, options, environment variables, manifest fields, or safety contracts change.
- Public behavior changes require README/manual updates in the same issue or a linked,
  explicitly ordered documentation issue.

## GitHub repository policy

The repository is expected to enforce these settings:

- pull requests required for `main`, with no approval count while there is only one maintainer;
- strict required status check `required` and resolved conversations;
- linear history, with force pushes and deletion disabled for `main`;
- Squash merge enabled; merge commits and rebase merge disabled;
- merged branches deleted automatically.

If actual settings differ, report the drift. Do not weaken protection to work around a failing
check; fix the change or the check through a reviewed governance pull request.
