# OPA-7 — Improve YAML File Selection

## Objective

Replace the free-text YAML file path widget in the ComfyUI-OpalFruit YAML Expression Loader with a native ComfyUI file selection dropdown.

The implementation must work consistently when using ComfyUI Desktop or accessing the ComfyUI backend through a web browser on another device.

## References

- Repository: https://github.com/opalfruitai/ComfyUI-OpalFruit
- Linear issue: https://linear.app/opalfruitai/issue/OPA-7/improve-yaml-file-selection-in-comfyui-opalfruit
- Primary implementation: `nodes/yaml_expressions.py`
- Node: `YAMLExpressionLoader`

## Current implementation

The YAML Expression Loader currently exposes a `STRING` input named `yaml_path`, requiring users to manually enter a filesystem path.

The loader:

- Reads YAML using `yaml.safe_load`.
- Validates the catalogue structure, seed and expression entries.
- Rejects duplicate expression names.
- Returns an expression list and integer seed.
- Uses a SHA-256 content fingerprint through `IS_CHANGED` for cache invalidation.

These behaviours must be preserved.

The loader currently uses the ComfyUI V1 node API. Migration to V3 is not required for this change.

## Functional requirements

### FR-01 — Catalogue directory

Use the `yaml` subdirectory of ComfyUI's configured input directory.

```text
input/
└── yaml/
    ├── expressions.yaml
    ├── ava.yaml
    └── emily.yml
```

Resolve the input directory using ComfyUI's supported `folder_paths` API, rather than deriving it from the application installation directory.

The implementation must not assume a specific operating system or installation layout.

### FR-02 — File selection

Replace the existing free-text widget with a native ComfyUI dropdown.

- Discover files with `.yaml` and `.yml` extensions.
- Present filenames in a deterministic, alphabetical order.
- Exclude directories and unsupported file types.
- Retain the existing `yaml_path` input identifier.
- Store relative filenames rather than absolute filesystem paths in workflows.
- Handle missing or empty catalogue directories gracefully.
- Ensure newly added files become available through the standard ComfyUI refresh mechanism, where supported.

For this initial implementation, only files directly within `input/yaml/` need to be discovered.

### FR-03 — Backend file resolution

All file discovery, resolution and loading must occur on the ComfyUI backend.

The frontend must not require access to the backend filesystem.

The same catalogue selection must work from:

- ComfyUI Desktop.
- A local web browser.
- A remote web browser.

### FR-04 — Existing functionality

Preserve:

- YAML catalogue structure.
- Existing validation rules.
- Expression ordering.
- Duplicate expression detection.
- Seed handling.
- Output names and types.
- List output behaviour.
- Content-based cache invalidation.
- Existing YAML Expression Extractor functionality.

The `load` and `IS_CHANGED` methods must resolve the selected catalogue consistently.

### FR-05 — Existing workflows

Retain the existing node registration and input identifier to minimise workflow compatibility issues.

Existing workflows containing absolute file paths may require migration.

Document the migration procedure, including moving the catalogue into `input/yaml/` and reselecting it within the node.

Do not introduce unrestricted absolute-path access as a compatibility workaround.

## Non-functional requirements

### Security

- Restrict catalogue loading to the designated YAML directory.
- Reject path traversal and absolute paths.
- Prevent symbolic links or equivalent filesystem mechanisms from escaping the designated directory.
- Retain safe YAML parsing.
- Provide meaningful errors for missing, invalid or inaccessible files.

### Maintainability

- Prefer native ComfyUI APIs and standard Python libraries.
- Do not introduce additional third-party dependencies.
- Do not introduce custom frontend JavaScript.
- Avoid unrelated refactoring.
- Follow existing repository conventions.
- Preserve the existing automated test architecture.

### Portability

Support ComfyUI Desktop and conventional ComfyUI installations across supported operating systems.

## Testing

Inspect the existing test suite and extend it using established conventions.

Automated tests should cover:

- Discovery of `.yaml` and `.yml` files.
- Exclusion of unsupported files and directories.
- Deterministic file ordering.
- Missing and empty catalogue directories.
- Correct resolution and loading of selected files.
- Rejection of absolute paths and path traversal.
- Rejection of filesystem links escaping the catalogue directory.
- Existing YAML validation behaviour.
- Cache invalidation when catalogue contents change.
- Handling of deleted or renamed catalogues.

Use temporary directories and mock the ComfyUI input-directory API where appropriate.

Automated tests must not require a running ComfyUI instance.

## Manual acceptance tests

- [ ] Create `input/yaml/` under the configured ComfyUI input directory.
- [ ] Add at least two valid YAML catalogues.
- [ ] Confirm both catalogues appear in the dropdown.
- [ ] Select each catalogue and confirm the correct expressions and seed are returned.
- [ ] Modify a catalogue and confirm cache invalidation works.
- [ ] Add another catalogue and verify the supported refresh behaviour.
- [ ] Save and reload a workflow, confirming the selection persists.
- [ ] Verify equivalent behaviour through a remote web browser.
- [ ] Verify existing expression extraction and loop workflows continue to function.

## Documentation

Update the README to explain:

- Catalogue directory location.
- Supported file extensions.
- File selection and refresh behaviour.
- Local and remote usage.
- Migration from previous absolute-path workflows.

## Out of scope

- YAML file uploads.
- Arbitrary filesystem browsing.
- Recursive subdirectory discovery.
- Additional catalogue directory configuration.
- Integration with `extra_model_paths.yaml`.
- Custom frontend components.
- V1-to-V3 node migration.
- Changes to YAML catalogue schemas.
- Changes to unrelated nodes.

## Delivery

1. Review the existing implementation, tests and repository guidance.
2. Verify the relevant ComfyUI API contracts.
3. Implement the smallest maintainable solution satisfying the requirements.
4. Extend the automated tests.
5. Run the complete existing test suite.
6. Update the README.
7. Review the diff for unintended changes.
8. Commit changes to the implementation branch.

Do not merge into `main`.

Report implementation details, test results, compatibility implications and any unresolved issues. Distinguish automated test results from validation performed within a real ComfyUI environment.

## Definition of done

The implementation is complete when all automated tests pass, documentation is updated, and the manual acceptance tests have been successfully completed in both ComfyUI Desktop and a remote browser.
