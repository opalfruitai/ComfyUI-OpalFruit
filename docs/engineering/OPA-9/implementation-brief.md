# OPA-9 — Contact sheet path resolution

## Authorised scope

Issue: https://linear.app/opalfruitai/issue/OPA-9/investigate-image-contact-sheet-directory-resolution-failure
Branch: `fix/opa-9-contact-sheet-path-resolution`
Approved: 2026-11-24

## Evidence and diagnosis

ComfyUI Desktop 0.46.3 on Windows: the workflow supplies `Expressions/test` to Image Contact Sheet, with End Loop connected to trigger. The backend uses a configured shared output directory, but the node searches the installation working directory and raises ValueError (directory does not exist). Repeated failures occurred after generation. Replacing only the directory input with the correct absolute output path succeeded, as confirmed by the user.

Current main: nodes/contact_sheet.py resolves Path(image_directory).expanduser().resolve(); nodes/image_contact_sheet.py passes the string unchanged. README recommends absolute paths. This is a pre-existing path resolution limitation, not an established OPA-7 regression.

## Approved behaviour

- Resolve relative directory inputs against the backend's configured output directory using folder_paths.get_output_directory() at execution time, not cwd or a hardcoded installation path.
- Resolve canonical paths and reject relative paths escaping the canonical output root, including traversal and symlink escapes. Permit nested paths and the output root itself (e.g. "."). Do not silently fall back to cwd.
- Preserve explicitly absolute paths, including those outside the output root, and existing home expansion (~). Reject empty or whitespace-only input with a clear ValueError. Do not trim valid nonempty path names. Reject ambiguous Windows drive-relative/root-relative paths rather than allowing implicit drive/cwd resolution; use native platform path semantics.
- Keep the PIL-only engine unchanged and host-independent; put resolution in the V3 wrapper. Preserve node ID, sockets, defaults, output path contract, trigger dependency, fingerprint behaviour and image processing.
- No frontend changes, new dependencies, YAML changes or unrelated refactoring.

## Implementation and tests

Inspect current source and tests before editing. Use lazy host folder_paths access where appropriate, consistent with existing YAML loader. Keep test stubs isolated and restore any patched modules. Add wrapper tests using temporary directories and a configured output root distinct from cwd. Cover nested relative paths, root, absolute paths outside output, home expansion, empty/whitespace, missing directory, traversal escape, symlink escape (platform-aware), and Windows ambiguous paths where applicable. Verify generated sheet is written to the intended directory and existing engine and wrapper tests remain green. Document changed relative-path semantics and absolute-path compatibility in README. Note that containment is a path-resolution safeguard, not a filesystem sandbox; explicit absolute paths remain supported.

Run `python -m unittest discover -s tests -v`. Report actual results and any platform-specific skips or limitations. Do not claim real-host validation unless performed.

## Manual acceptance (user)

- Restore the original relative workflow input and retain the End Loop trigger.
- Generate a sheet in the configured shared output directory, verify expected source images and output.
- Repeat with fresh images and verify the sheet updates.
- Repeat from remote browser and confirm absolute path compatibility.
- Confirm no YAML selection regression.

## Delivery

Work only on the named fix branch. Use Conventional Commits with Refs: OPA-9; no personal identifiers in branch names or public audit documents. Do not merge or release. Commit and push implementation, tests and README. Write final report to docs/engineering/OPA-9/implementation-report.md, recording actual changes, commit SHAs, test commands/results, decisions, limitations and pending manual acceptance. Retain both brief and report in repository audit directory. Return branch and final commit SHA for independent review. Do not mark issue Done.
