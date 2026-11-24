# OPA-9 — Contact sheet path resolution: implementation report

## Status

- **In progress — pending manual acceptance** (not marked Done).
- **Branch:** `fix/opa-9-contact-sheet-path-resolution`
- **Approved:** 2026-11-24
- **Issue:** https://linear.app/opalfruitai/issue/OPA-9/investigate-image-contact-sheet-directory-resolution-failure

## Actual changes

Implementation commit **`b9aa2e3ffc0f10562596db266e0ec1d2042cf58c`**
— `fix(contact-sheet): resolve relative image_directory against configured output dir` (3 files, 227 insertions, 4 deletions).

### `nodes/image_contact_sheet.py` (V3 wrapper; +98 lines)

Added module-level helpers and rewired `execute`:

- `_folder_paths()` — lazy import of ComfyUI's `folder_paths`, mirroring the
  existing pattern in `nodes/yaml_expressions.py`. Keeps the wrapper
  importable in the host-less CI environment; the host API is only required
  at execution time, when a relative path must be anchored.
- `_output_root()` — `Path(folder_paths.get_output_directory()).expanduser().resolve()`.
- `_resolve_image_directory(image_directory)` — the new contract:
  - Rejects empty/whitespace-only input with a clear `ValueError`.
  - Expands `~` *before* classification, so home paths are treated as absolute.
  - Explicitly absolute paths (including `~`-expanded, and paths outside the
    output root, and UNC) are canonicalised and **preserved as-is**.
  - Windows: non-absolute root-relative (`\subdir`, `/subdir`) and
    drive-relative (`C:subdir`, `C:`) paths are **rejected** rather than
    resolved against the current drive/cwd; native platform semantics via
    `pathlib.Path.is_absolute()`.
  - Relative paths are resolved against `_output_root()`; if the resolved
    path escapes the canonical output root (via `..` traversal or a symlink
    pointing outside), a `ValueError` is raised. No silent cwd fallback.
- `execute` now calls `directory = _resolve_image_directory(image_directory)`
  and passes `str(directory)` to `build_contact_sheet`. Node ID, sockets,
  defaults, `output_path` contract, optional `trigger` handling, `fingerprint_inputs`
  (float nan), and the PIL image processing are unchanged.

### `nodes/contact_sheet.py` (PIL-only engine)

**Unchanged.** It remains a pure, host-independent PIL helper. The wrapper
passes it a canonical absolute path, so the engine's existing
`Path(image_directory).expanduser().resolve()` is a no-op.

### `tests/test_image_contact_sheet.py` (+125 lines)

Added `ContactSheetPathResolutionTests` (10 tests) with a temp output root
distinct from cwd, a real sibling `outside` directory, and a per-test isolated
fake `folder_paths` module patched via `patch.dict(sys.modules, ...)` and
restored by `addCleanup` (same pattern as `tests/test_yaml_expressions.py`):

- `test_root_dot_resolves_to_output_root` — `.` → output root.
- `test_relative_nested_resolves_under_output_root` — nested relative path.
- `test_generated_sheet_lands_in_intended_dir_not_cwd` — verifies the sheet is
  physically written to the intended directory, not cwd.
- `test_absolute_outside_output_is_preserved` — absolute path outside the
  output root is used as-is; output root stays untouched.
- `test_home_expansion_treated_as_absolute` — `~/...` resolved as absolute.
- `test_empty_and_whitespace_rejected` — empty/whitespace-only inputs raise
  `ValueError` ("nonempty").
- `test_missing_directory_rejected` — nonexistent directory raises
  `ValueError` ("does not exist").
- `test_traversal_escape_rejected` — `../..`, `sub/../../..`, `../` escape.
- `test_symlink_escape_rejected` — symlink pointing outside the root (platform-
  aware; `skipTest` where `os.symlink` is unavailable).
- `test_windows_root_and_drive_relative_rejected` — `\subdir`, `/subdir`,
  `C:subdir`, `C:` rejected (Windows-only; `skipTest` elsewhere).

### `README.md`

- Updated the `image_directory` input row to describe the new relative-path
  semantics.
- Added a **Path resolution** note block after the inputs table, stating that
  relative paths are anchored to the configured output directory and that
  containment is a **path-resolution safeguard, not a filesystem sandbox**.
- Updated the Requirements paragraph to describe the new `image_directory`
  semantics (relative → configured output directory; absolute/`~` → used as-is,
  even outside the output directory).

> **Independent-review correction.** Applied in the follow-up commit on the same
> branch: the redundant `_within_root()` helper and its string-based case
> folding were removed, and output-root containment is now checked directly with
> `resolved.is_relative_to(root)` — `pathlib` already provides native Windows
> path comparison semantics. The "Decisions" section reflects the final choice.

## Test results

**Command** (from the repository root, environment with `requirements.txt`):

```
python -m unittest discover -s tests -v
```

**Result:**

```
Ran 47 tests in 0.262s

OK
```

All 47 tests pass — 10 new `ContactSheetPathResolutionTests` plus all existing
engine and wrapper tests remain green. No failures, no errors, no skips on this
run. The run is recorded at the final state, after the independent-review
correction; it reproduces the identical 47/47 result.

**Platform notes (run on Windows, `win32`/PowerShell):**

- `test_windows_root_and_drive_relative_rejected` was **executed** (Windows
  path semantics available).
- `test_symlink_escape_rejected` was **executed** (symlink creation succeeded on
  this platform); it is platform-aware and will skip where `os.symlink` fails.
- The separate real-host integration check
  (`python -m unittest discover -s tests -p "comfy_integration_check*.py" -v`)
  was **not** validated here: in this environment the host's own `comfy_api`
  could not be imported (host runtime dependencies absent), so its tests skip
  as designed. Per the README, this is a local/manual check, not part of CI, and
  no real-host validation is claimed for this change.

## Decisions

1. **Resolution lives in the V3 wrapper, not the engine.** The PIL engine stays
   pure and host-independent; the wrapper supplies a canonical absolute path so
   the engine's internal `Path(...).expanduser().resolve()` is a no-op.
2. **Lazy host access.** `folder_paths` is imported only at execution time
   via `_folder_paths()`, consistent with `nodes/yaml_expressions.py`, so the
   wrapper remains importable in host-less CI.
3. **Canonicalisation.** The output root and every candidate path are resolved
   with `expanduser().resolve()` before the containment decision; the root is
   the canonical output directory, not the process cwd.
4. **Native path containment.** Containment is checked directly with
   `resolved.is_relative_to(root)`; `pathlib` already provides native Windows
   path comparison semantics (case-insensitive on case-insensitive filesystems),
   so no extra helper or string-based case folding is needed.
5. **Reject Windows ambiguity rather than guess.** Non-absolute root-relative
   (`\subdir`, `/subdir`) and drive-relative (`C:subdir`, `C:`) paths would
   resolve against the *current* drive/cwd; they are rejected with a clear error.
   Genuinely absolute Windows paths (`C:\x`, `D:\x`, UNC) are preserved.
6. **No silent fallback to cwd.** Only `ValueError` with actionable messages;
   never a fallback path.
7. **Absolute-path compatibility preserved.** Explicit absolute paths and `~`
   paths are used as-is, even when outside the output directory — matching the
   documented workaround that the user already confirmed working.

## Limitations

- Containment is a **path-resolution safeguard, not a filesystem sandbox**:
  explicit absolute paths outside the output root remain fully supported.
- Windows root-/drive-relative non-absolute paths are intentionally rejected
  (clear error) rather than resolved against an implicit current drive/cwd.
- Path resolution occurs **at execution time** using the host's currently
  configured output directory; a mid-session configuration change would affect
  subsequent runs.
- Real-host integration check not performed in this environment (host runtime
  dependencies absent); unit suite runs against the `comfyio_stub` stand-in.
- Symlink-escape test is platform-aware and skips where symlink creation is
  unavailable.

## Pending manual acceptance (user)

Per the approved brief, the following remain for the user:

1. Restore the original relative workflow input and retain the End Loop trigger.
2. Generate a sheet in the configured shared output directory; verify expected
   source images and output.
3. Repeat with fresh images and verify the sheet updates.
4. Repeat from a remote browser and confirm absolute path compatibility.
5. Confirm no YAML selection regression.

## Audit

Both the approved implementation brief and this report are retained in
`docs/engineering/OPA-9/`. The work was performed only on the named fix branch;
no merge or release was performed.
