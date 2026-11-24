# OPA-7 — Implementation Report: Native YAML File Selection

**Date:** 2026-11-24
**Branch:** `feature/opa-7-yaml-file-selection`
**Implementation commits:** `f073e05` (original) → `fcdf9df` (review fixes)
**Status:** Implementation complete; review findings addressed; automated tests pass (37/37); manual acceptance passed; PR CI pending.

## Summary

Replaced the free-text YAML file path widget in the `YAMLExpressionLoader` node with a native ComfyUI file-selection dropdown that lists catalogues from `input/yaml/` (the `yaml` subdirectory of ComfyUI's configured input directory). All discovery, resolution and loading happens on the ComfyUI backend; no custom frontend JavaScript and no new dependencies were introduced.

## Implementation decisions

- **Catalogue directory (FR-01).** `_yaml_directory()` resolves `input/yaml/` via `folder_paths.get_input_directory()` — ComfyUI's own configured input directory — rather than deriving it from the installation directory. Works with any configured layout across Desktop, local and remote setups.
- **Dropdown pattern (FR-02).** `INPUT_TYPES` returns `(_catalogue_files(), {tooltip})` for the existing `yaml_path` identifier — the same mechanism the host's own `LoadImage` node uses to present a native file dropdown. No custom frontend code, no new dependencies.
- **Discovery.** `_catalogue_files()` lists only `.yaml`/`.yml` files (extensions matched case-insensitively) directly in the directory (non-recursive), sorted alphabetically, excluding directories, other file types and symlinks. A missing or empty directory yields an empty list, so the dropdown is simply empty instead of erroring.
- **Safe resolution (FR-03 / security).** `_resolve_catalogue_path()` is the single resolver shared by `load` and `IS_CHANGED`. It rejects missing/empty names, absolute paths, `/` / `\` / `.` / `..` in the name, and symlinks whose `resolve()` points outside the directory (`is_relative_to` check). Errors are clear and show only the filename, not the full path.
- **Lazy `folder_paths` import.** `folder_paths` is imported only inside `_folder_paths()` so the package-registration test can import the module in the host-less CI environment; it is required at runtime once the schema is built or a workflow is queued.
- **Preserved behaviour (FR-04 / FR-05).** YAML catalogue structure, validation rules, expression ordering, case-insensitive duplicate detection, seed handling, output names/types, list-output behaviour (`OUTPUT_IS_LIST = (True, False)`), SHA-256 content-based cache invalidation via `IS_CHANGED`, and the `YAMLExpressionExtractor` were all kept unchanged. Node name, category, input identifier and node registration are unchanged.
- **No unrestricted absolute-path access** was added as a compatibility workaround; old absolute paths are rejected by design.

## Review findings (second pass) and changes

An implementation review raised three findings, each fixed in `fcdf9df`:

1. **Discovery and resolution must agree.** Discovery (the dropdown) filtered out unsupported extensions and symbolic links, but resolution did not — a workflow could still store an unsupported extension or a symlink name and only fail at read. Both paths now share a single `_is_catalogue_entry()` predicate (regular, non-symlink, `.yaml`/`.yml` case-insensitive), and `_resolve_catalogue_path()` checks the extension and symlinks as well. A subtle regression was caught while doing this: pathlib normalises a Windows-leading `.\` away (`Path(".\outer.yaml").parts == ("outer.yaml",)`), so the interim parts-based traversal check missed `.\` traversal. Name validation now rejects any path separator (`/` or `\`, both OSes) plus exact `.`/`..`, and a filename with consecutive dots (`my..file.yaml`) — no separator — resolves successfully, as the review required.
2. **`test_missing_and_empty_catalogue_directory` was only testing one case.** Because `setUp` always creates `yaml/`, the "missing" branch never ran. It now removes the directory with `rmdir()` for the missing case and exercises both missing and empty directories under `subTest`.
3. **Test mocking must preserve and restore the real `folder_paths` module.** Tests now use `unittest.mock.patch.dict(sys.modules, {"folder_paths": fake})`, which saves whatever module (or absence) is present and restores it on teardown, instead of overwriting and deleting `folder_paths` from `sys.modules`.

Regression tests added: a consecutive-dots filename is listed and loads; an unsupported extension is rejected at resolution (not just omitted from the dropdown); an in-directory symbolic link is rejected at both discovery and resolution.

## Files changed

### Original implementation (`f073e05`)

| File | Change |
| --- | --- |
| `nodes/yaml_expressions.py` | Free-text `yaml_path` → native file dropdown; added `_folder_paths()`, `_yaml_directory()`, `_resolve_catalogue_path()`, `_catalogue_files()`; `load`/`IS_CHANGED` use the shared resolver. |
| `tests/test_yaml_expressions.py` | Rewritten for the new contract: mocked `folder_paths.get_input_directory()` over per-test temp dirs; new discovery/ordering/exclusion/missing-dir/selection/security/rejection tests. |
| `README.md` | Updated requirements line, example catalogue location, added a "Catalogue file selection" section (directory, refresh, local/remote behaviour, migration) and a validation rule. |

### Review fixes (`fcdf9df`, +113 / −19)

| File | Change |
| --- | --- |
| `nodes/yaml_expressions.py` | Added shared `_is_catalogue_entry()` predicate so discovery and resolution reject the same files (extensions and symlinks now checked at resolution); separator-based name validation that rejects any `/` or `\` plus exact `.`/`..` while still allowing consecutive-dot filenames. (+55, −7) |
| `tests/test_yaml_expressions.py` | Mocked `folder_paths` via `patch.dict` (preserves/restores the real module); fixed missing/empty-dir test to exercise both cases under `subTest`; added regression tests for consecutive-dot filenames, unsupported-extension rejection at resolution, and in-directory symlink rejection. (+77, −4) |

## Automated test results

Command (from repository root, `requirements.txt` installed):

```sh
python -m unittest discover -s tests -v
```

```
Ran 37 tests in 0.214s
OK
```

All 37 tests pass with zero skips. Coverage (per the brief, plus review regressions):

- Discovery of `.yaml` and `.yml` files (case-insensitive).
- Exclusion of unsupported files and subdirectories.
- Deterministic alphabetical ordering.
- Missing and empty catalogue directories.
- Correct resolution and loading of each selected file.
- Rejection of absolute paths and path traversal (incl. Windows-style `\\`).
- Rejection of unsupported extensions at resolution (not just omission from the dropdown).
- Resolution of valid filenames with consecutive dots (`my..file.yaml`).
- Rejection of filesystem links escaping the catalogue directory (graceful `skipTest` where the platform cannot create symlinks), and rejection of in-directory symlinks at resolution.
- Handling of deleted or renamed catalogues.
- Existing YAML validation behaviour and cache invalidation on content change.
- Package registration (node schema, categories, function callables).

Engine tests need no ComfyUI and no GPU; V3 node tests run against the host's `comfy_api` when present or the `tests/comfyio_stub.py` stand-in when absent.

## Compatibility implications

- **Old workflows:** workflows that stored an *absolute path* in `yaml_path` will now raise a clear error instead of silently mis-resolving. Migration: move the catalogue file into `input/yaml/`, reselect it in the dropdown, and save the workflow (documented in `README.md`).
- **New workflows:** drop-in compatible — node name, category, `yaml_path` identifier and both outputs (`expressions`, `seed`) are unchanged.
- **Workflow storage:** selections now store relative filenames (e.g. `ava.yaml`), so a workflow loads identically across machines that share a catalogue in `input/yaml/`.
- **Local and remote:** identical behaviour in ComfyUI Desktop, a local web browser and a remote web browser — the browser only picks a name from the dropdown; all directory discovery, file resolution and YAML loading run on the ComfyUI backend. No browser ever sees or touches a filesystem path.

## Manual acceptance results (2026-11-24)

User-confirmed live ComfyUI Desktop and remote laptop browser results:

- [x] Desktop: create `input/yaml/`, add two valid catalogues; confirm both appear in the dropdown.
- [x] Desktop: select each catalogue and confirm the correct expressions and seed are returned.
- [x] Desktop: modify a catalogue and confirm cache invalidation works.
- [x] Desktop: add a third catalogue and verify it appears via ComfyUI's standard refresh (Ctrl+R / refresh).
- [x] Save and reload a workflow and confirm the selection persists.
- [x] Remote web browser: verify equivalent behaviour to the Desktop checks above.
- [x] Verify existing expression-extraction and loop workflows continue to function.

Two workflow configuration issues were resolved during testing: a legacy absolute YAML selection was cleared, and incorrect contact sheet wiring was corrected. No implementation changes were required. CI remains pending.

## Commit

Implementation commits (this report is a separate follow-up commit):

```
f073e05 Add native file dropdown for YAML Expression Loader catalogue
fcdf9df Consistent catalogue discovery/resolution, robust folder_paths mocking
```

Branch: `feature/opa-7-yaml-file-selection` — not merged into `main`, per the brief.
