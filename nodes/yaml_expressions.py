"""Load YAML expression catalogues and extract individual loop entries."""

import hashlib
from pathlib import Path

import yaml

EXPRESSION_TYPE = "OPALFRUIT_EXPRESSION"

# The directory (relative to ComfyUI's configured input directory) that holds
# YAML expression catalogues.
CATALOGUE_DIR_NAME = "yaml"

# Supported catalogue file extensions, matched case-insensitively.
CATALOGUE_EXTENSIONS = (".yaml", ".yml")


def _folder_paths():
    """Return ComfyUI's ``folder_paths`` module.

    Imported lazily so that this module stays importable in the host-less CI
    environment (the package-registration test). It is only required at runtime
    once ComfyUI's node schema is being built or a workflow is executed.
    """
    import folder_paths

    return folder_paths


def _yaml_directory():
    """Absolute path to the YAML catalogue directory (``input/yaml``)."""
    return Path(_folder_paths().get_input_directory()) / CATALOGUE_DIR_NAME


def _is_catalogue_entry(path):
    """True when ``path`` is a regular, non-symlink file with a supported
    catalogue extension — exactly the set the dropdown lists and the loader
    accepts. Kept in one place so discovery and resolution never diverge."""
    return (
        path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in CATALOGUE_EXTENSIONS
    )


def _resolve_catalogue_path(yaml_path):
    """Resolve a relative catalogue filename into a safe absolute path inside the
    catalogue directory.

    Raises ``ValueError`` for a missing/empty name, absolute or subdirectory
    paths, path traversal, unsupported extensions, symbolic links, or links that
    point outside the catalogue directory. A file not on disk is left to fail
    at the read below with a clear error.
    """
    if yaml_path is None:
        raise ValueError("YAML catalogue file name is required.")
    name = str(yaml_path)
    if not name:
        raise ValueError("YAML catalogue file name is required.")

    # Catalogues live directly in the catalogue directory: the workflow-stored
    # value must be a single filename. Any path separator (either OS) makes the
    # value a path — absolute, subdirectory, or traversal ("./", "../",
    # "\.", "..\\") — so it is rejected. A filename that merely contains
    # consecutive dots ("my..file.yaml") has no separator and is allowed.
    # (On Windows pathlib normalises a leading "\." away, so a parts-based
    # check would have missed traversal — the raw-separator test does not.)
    if "/" in name or "\\" in name:
        raise ValueError(f"Invalid YAML catalogue file name: {yaml_path!r}.")
    if name in (".", ".."):
        raise ValueError(f"Invalid YAML catalogue file name: {yaml_path!r}.")

    # Discovery and resolution must agree on which files are catalogues:
    # regular .yaml/.yml files, matched case-insensitively.
    if Path(name).suffix.lower() not in CATALOGUE_EXTENSIONS:
        raise ValueError(f"Invalid YAML catalogue file name: {yaml_path!r}.")

    yaml_dir = _yaml_directory()
    target = yaml_dir / name

    # Resolve symlinks on both ends so a link inside the catalogue directory
    # cannot silently escape it.
    base_real = yaml_dir.resolve()
    target_real = target.resolve()
    if not target_real.is_relative_to(base_real):
        raise ValueError(
            f"Invalid YAML catalogue path: {yaml_path!r} points outside "
            f"the catalogue directory."
        )

    # The target must be exactly the kind of entry the dropdown offers: a
    # regular, non-symlink file. A missing file is left to fail at the read
    # below with a clear error.
    if target.is_symlink():
        raise ValueError(f"Invalid YAML catalogue file name: {yaml_path!r}.")
    if target.exists() and not _is_catalogue_entry(target):
        raise ValueError(f"Invalid YAML catalogue file name: {yaml_path!r}.")
    return target


def _catalogue_files():
    """Deterministic list of catalogue filenames directly in the catalogue dir.

    Returns only regular (non-symlink) ``.yaml``/``.yml`` files, sorted. An
    empty list is returned when the catalogue directory does not exist, so the
    node degrades gracefully instead of crashing.
    """
    yaml_dir = _yaml_directory()
    if not yaml_dir.is_dir():
        return []
    return sorted(
        entry.name for entry in yaml_dir.iterdir() if _is_catalogue_entry(entry)
    )


def validate_expression(value):
    if not isinstance(value, dict):
        raise ValueError("Each expression must be a dictionary.")
    for field in ("expression", "prompt"):
        if field not in value or not isinstance(value[field], str):
            raise ValueError(f"Each expression requires a string '{field}' field.")
        if not value[field].strip():
            raise ValueError(f"Each expression's '{field}' must be nonempty and not whitespace.")
    return value


class YAMLExpressionLoader:
    """Read a YAML expression catalogue and emit its prompts as a list plus a seed."""

    CATEGORY = "OpalFruit/YAML"
    FUNCTION = "load"
    RETURN_TYPES = (EXPRESSION_TYPE, "INT")
    RETURN_NAMES = ("expressions", "seed")
    OUTPUT_IS_LIST = (True, False)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "yaml_path": (
                    _catalogue_files(),
                    {"tooltip": "A YAML expression catalogue from the input/yaml directory."},
                )
            }
        }

    @classmethod
    def IS_CHANGED(cls, yaml_path):
        try:
            path = _resolve_catalogue_path(yaml_path)
            data = path.read_bytes()
        except (OSError, ValueError):
            return float("nan")
        return hashlib.sha256(data).hexdigest()

    def load(self, yaml_path):
        path = _resolve_catalogue_path(yaml_path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f"Cannot read YAML catalogue '{path.name}': {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("YAML catalogue must be a top-level dictionary.")
        seed = data.get("seed")
        if type(seed) is not int:
            raise ValueError("YAML catalogue requires an integer 'seed'.")
        if seed < 0:
            raise ValueError("YAML catalogue 'seed' must not be negative.")
        expressions = data.get("expressions")
        if not isinstance(expressions, list) or not expressions:
            raise ValueError("YAML catalogue requires a nonempty 'expressions' list.")
        seen = set()
        for value in expressions:
            entry = validate_expression(value)
            name = entry["expression"]
            key = name.casefold()
            if key in seen:
                raise ValueError(f"Duplicate expression name: {name!r}.")
            seen.add(key)
        return expressions, seed


class YAMLExpressionExtractor:
    """Split one catalogue entry into its expression and prompt strings."""

    CATEGORY = "OpalFruit/YAML"
    FUNCTION = "extract"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("expression", "prompt")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"expression": (EXPRESSION_TYPE,)}}

    def extract(self, expression):
        entry = validate_expression(expression)
        return entry["expression"], entry["prompt"]
