"""V3 node wrapper for the PIL-only image contact-sheet engine."""

import os

from pathlib import Path

from comfy_api.latest import io

from .contact_sheet import build_contact_sheet


def _folder_paths():
    """Return ComfyUI's ``folder_paths`` module.

    Imported lazily so that this wrapper stays importable in the host-less CI
    environment. It is required only at execution time, when a relative
    ``image_directory`` must be anchored to the configured output directory.
    """
    import folder_paths

    return folder_paths


def _output_root() -> Path:
    """The canonical absolute directory of ComfyUI's configured output."""
    return Path(_folder_paths().get_output_directory()).expanduser().resolve()


def _resolve_image_directory(image_directory) -> Path:
    """Resolve the ``image_directory`` input to a canonical absolute path.

    Relative paths are anchored to the configured output directory (via
    ``folder_paths.get_output_directory()``), never to the process cwd. A
    relative path that escapes the canonical output root — via ``..``
    traversal or a symbolic link that points outside — is rejected. On
    Windows, a non-absolute path that starts with a separator (root-relative,
    e.g. ``\\subdir`` / ``/subdir``) or references a drive (``C:subdir``,
    ``C:``) would resolve against the *current* drive/cwd; that is ambiguous
    and is rejected rather than guessed.

    Explicitly absolute paths are preserved unchanged (even when they point
    outside the output root) after ``~`` expansion and canonicalisation.

    Raises ``ValueError`` for empty/whitespace-only input, an ambiguous
    Windows root-/drive-relative path, or a relative path escaping the output
    root.
    """
    text = image_directory
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        raise ValueError("Image directory must be a nonempty path.")

    # Expand ``~`` before classifying, so a home path is seen as absolute.
    p = Path(text).expanduser()

    if p.is_absolute():
        # Explicitly absolute (including ``~``-expanded and outside the output
        # root): canonicalise, but do not constrain to the output root.
        return p.resolve()

    if os.name == "nt":
        # A non-absolute Windows path that starts with a separator (drive-
        # relative root, e.g. ``\subdir`` / ``/subdir``) or references a drive
        # (e.g. ``C:subdir``) would resolve against the *current* drive/cwd —
        # ambiguous. Reject it.
        if text.startswith(("\\", "/")):
            raise ValueError(
                f"Cannot resolve root-relative image directory '{text!r}'. "
                "Provide a full absolute path or a relative path."
            )
        if os.path.splitdrive(text)[0]:
            raise ValueError(
                f"Cannot resolve drive-relative image directory '{text!r}'. "
                "Provide a full absolute path or a relative path."
            )

    root = _output_root()
    resolved = (root / p).expanduser().resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"Image directory '{text!r}' resolves outside the configured output "
            f"directory ('{root}')."
        )
    return resolved


class ImageContactSheet(io.ComfyNode):
    """Generate a contact sheet of image thumbnails from a directory of files."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="OpalFruitImageContactSheet",
            display_name="Image Contact Sheet",
            category="OpalFruit/Image",
            description="Generate a contact sheet of image thumbnails from a directory of files.",
            inputs=[
                io.String.Input("image_directory", default=""),
                io.String.Input("filename_pattern", default="*.png"),
                io.Int.Input("columns", default=4, min=1),
                io.Int.Input("thumbnail_width", default=256, min=1),
                io.Boolean.Input("show_labels", default=True),
                io.String.Input("background_colour", default="#808080"),
                io.String.Input("output_filename", default="contact-sheet.png"),
                io.AnyType.Input(
                    "trigger",
                    optional=True,
                    tooltip="Optional dependency. Connect End Loop 'outputs' to run after a Start Loop / End Loop completes. The value is ignored during image processing.",
                ),
            ],
            outputs=[io.String.Output(display_name="output_path")],
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        # Source files may change without any widget values changing.
        return float("nan")

    @classmethod
    def execute(
        cls,
        image_directory,
        filename_pattern="*.png",
        columns=4,
        thumbnail_width=256,
        show_labels=True,
        background_colour="#808080",
        output_filename="contact-sheet.png",
        trigger=None,
    ) -> io.NodeOutput:
        # The trigger is an execution-order dependency only (e.g. End Loop
        # "outputs"). It is intentionally ignored here; image processing is
        # independent of the value it carries.
        directory = _resolve_image_directory(image_directory)
        output = build_contact_sheet(
            str(directory),
            filename_pattern=filename_pattern,
            columns=columns,
            thumbnail_width=thumbnail_width,
            show_labels=show_labels,
            background_colour=background_colour,
            output_filename=output_filename,
        )
        return io.NodeOutput(str(output))
