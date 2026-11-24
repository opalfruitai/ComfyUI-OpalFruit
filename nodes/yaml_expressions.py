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


def _resolve_catalogue_path(yaml_path):
    """Resolve a relative catalogue filename into a safe absolute path inside the
    catalogue directory.

    Raises ``ValueError`` for a missing/empty name, absolute paths, path
    traversal, or symbolic links that point outside the catalogue directory.
    """
    if yaml_path is None:
        raise ValueError("YAML catalogue file name is required.")
    name = str(yaml_path)
    if not name:
        raise ValueError("YAML catalogue file name is required.")
    # Catalogues live directly in the catalogue directory: the workflow-stored
    # value must be a plain filename, never a (relative or absolute) path.
    if "/" in name or "\\" in name or name == "." or ".." in name:
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
    files = [
        entry.name
        for entry in yaml_dir.iterdir()
        if entry.is_file()
        and not entry.is_symlink()
        and entry.suffix.lower() in CATALOGUE_EXTENSIONS
    ]
    return sorted(files)


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
