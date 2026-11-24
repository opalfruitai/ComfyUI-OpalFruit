# OPA-7 — Implementation Report: Native YAML File Selection

**Date:** 2026-11-24
**Branch:** `darrenmilnes/opa-7-improve-yaml-file-selection-in-comfyui`
**Implementation commit:** `f073e05`
**Status:** Implementation complete; automated tests pass; manual acceptance pending (see below).

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

## Files changed

| File | Change |
| --- | --- |
| `nodes/yaml_expressions.py` | Free-text `yaml_path` → native file dropdown; added `_folder_paths()`, `_yaml_directory()`, `_resolve_catalogue_path()`, `_catalogue_files()`; `load`/`IS_CHANGED` use the shared resolver. (+94 lines, −2) |
| `tests/test_yaml_expressions.py` | Rewritten for the new contract: mocked `folder_paths.get_input_directory()` over per-test temp dirs; new discovery/ordering/exclusion/missing-dir/selection/security/rejection tests. (+188, −31) |
| `README.md` | Updated requirements line, example catalogue location, added a "Catalogue file selection" section (directory, refresh, local/remote behaviour, migration) and a validation rule. |

## Automated test results

Command (from repository root, `requirements.txt` installed):

```sh
python -m unittest discover -s tests -v
```

```
Ran 34 tests in 0.194s
OK
```

All 34 tests pass with zero skips. New coverage (per the brief):

- Discovery of `.yaml` and `.yml` files (case-insensitive).
- Exclusion of unsupported files and subdirectories.
- Deterministic alphabetical ordering.
- Missing and empty catalogue directories.
- Correct resolution and loading of each selected file.
- Rejection of absolute paths and path traversal (incl. Windows-style `\\`).
- Rejection of filesystem links escaping the catalogue directory (graceful `skipTest` where the platform cannot create symlinks).
- Handling of deleted or renamed catalogues.
- Existing YAML validation behaviour and cache invalidation on content change.
- Package registration (node schema, categories, function callables).

Engine tests need no ComfyUI and no GPU; V3 node tests run against the host's `comfy_api` when present or the `tests/comfyio_stub.py` stand-in when absent.

## Compatibility implications

- **Old workflows:** workflows that stored an *absolute path* in `yaml_path` will now raise a clear error instead of silently mis-resolving. Migration: move the catalogue file into `input/yaml/`, reselect it in the dropdown, and save the workflow (documented in `README.md`).
- **New workflows:** drop-in compatible — node name, category, `yaml_path` identifier and both outputs (`expressions`, `seed`) are unchanged.
- **Workflow storage:** selections now store relative filenames (e.g. `ava.yaml`), so a workflow loads identically across machines that share a catalogue in `input/yaml/`.
- **Local and remote:** identical behaviour in ComfyUI Desktop, a local web browser and a remote web browser — the browser only picks a name from the dropdown; all directory discovery, file resolution and YAML loading run on the ComfyUI backend. No browser ever sees or touches a filesystem path.

## Outstanding manual acceptance tests (Def of Done)

These require a live ComfyUI and were not executed from this session:

- [ ] Desktop: create `input/yaml/`, add two valid catalogues; confirm both appear in the dropdown.
- [ ] Desktop: select each catalogue and confirm the correct expressions and seed are returned.
- [ ] Desktop: modify a catalogue and confirm cache invalidation works.
- [ ] Desktop: add a third catalogue and verify it appears via ComfyUI's standard refresh (Ctrl+R / refresh).
- [ ] Save and reload a workflow and confirm the selection persists.
- [ ] Remote web browser: verify equivalent behaviour to the Desktop checks above.
- [ ] Verify existing expression-extraction and loop workflows continue to function.

## Commit

Implementation commit (this report is a separate follow-up commit):

```
f073e05 Add native file dropdown for YAML Expression Loader catalogue
```

Branch: `darrenmilnes/opa-7-improve-yaml-file-selection-in-comfyui` — not merged into `main`, per the brief.
