from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image


def _install_comfy_api_stub():
    """Install the ``comfy_api`` stand-in only when the real host is absent.

    The V3 wrapper imports ComfyUI's ``comfy_api`` at module level, but that
    module is supplied by the ComfyUI host, not by the project. CI installs
    only the declared dependencies, so the host is absent; ``tests/comfyio_stub.py``
    fabricates a minimal stand-in in that case. When the real host is on the path
    nothing is installed and the real API is used.
    """
    spec = importlib.util.spec_from_file_location(
        "comfyio_stub",
        Path(__file__).resolve().with_name("comfyio_stub.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["comfyio_stub"] = module
    spec.loader.exec_module(module)
    module.install_if_missing()


_install_comfy_api_stub()

from nodes.contact_sheet import LABEL_HEIGHT, build_contact_sheet, filename_label
from nodes.image_contact_sheet import (
    ImageContactSheet,
    _resolve_image_directory,
)


class ImageContactSheetTests(unittest.TestCase):
    """Pure engine behaviour (Pillow only; ComfyUI not required)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def image(self, name, size=(20, 20), colour="red", mode="RGB"):
        path = self.directory / name
        Image.new(mode, size, colour).save(path)
        return path

    def create(self, **kwargs):
        options = {"columns": 2, "thumbnail_width": 20, "show_labels": False}
        options.update(kwargs)
        return build_contact_sheet(str(self.directory), **options)

    def test_sorted_grid_aspect_ratio_and_sources_unchanged(self):
        paths = [
            self.image("c.png", colour="blue"),
            self.image("a.png", size=(40, 20), colour="red"),
            self.image("b.png", size=(20, 40), colour="lime"),
        ]
        original = {path: path.read_bytes() for path in paths}
        output = self.create(background_colour="#808080")
        self.assertTrue(output.is_absolute())
        with Image.open(output) as sheet:
            self.assertEqual(sheet.size, (40, 40))
            self.assertEqual(sheet.getpixel((10, 0)), (128, 128, 128))
            self.assertEqual(sheet.getpixel((10, 10)), (255, 0, 0))
            self.assertEqual(sheet.getpixel((20, 10)), (128, 128, 128))
            self.assertEqual(sheet.getpixel((30, 10)), (0, 255, 0))
            self.assertEqual(sheet.getpixel((10, 30)), (0, 0, 255))
            self.assertEqual(sheet.getpixel((30, 30)), (128, 128, 128))
        self.assertEqual(original, {path: path.read_bytes() for path in paths})

    def test_rgba_alpha_compositing(self):
        self.image("half.png", colour=(255, 0, 0, 128), mode="RGBA")
        self.image("transparent.png", colour=(0, 255, 0, 0), mode="RGBA")
        with Image.open(self.create(background_colour="#0000ff")) as sheet:
            self.assertEqual(sheet.mode, "RGB")
            self.assertEqual(sheet.getpixel((10, 10)), (128, 0, 127))
            self.assertEqual(sheet.getpixel((30, 10)), (0, 0, 255))

    def test_labels_and_configured_column_count(self):
        self.image("happy_00001_.png")
        with Image.open(self.create(columns=4, thumbnail_width=80, show_labels=True)) as sheet:
            self.assertEqual(sheet.size, (320, 104))
            label = sheet.crop((0, 80, 80, 104))
            self.assertGreater(len(label.getcolors()), 1)

    def test_filename_labels(self):
        for name, expected in (
            ("happy_00001_.png", "happy"),
            ("happy_00001.png", "happy"),
            ("a_b_12345_.PNG", "a_b"),
            ("happy.png", "happy"),
            ("version2.png", "version2"),
            ("happy_12_extra.png", "happy_12_extra"),
        ):
            with self.subTest(name=name):
                self.assertEqual(filename_label(name), expected)

    def test_empty_directory_and_excluded_output(self):
        with self.assertRaisesRegex(ValueError, "No source images"):
            self.create()
        self.image("contact-sheet.png")
        with self.assertRaisesRegex(ValueError, "No source images"):
            self.create()
        self.image("source.png")
        for _ in range(2):
            with Image.open(self.create(columns=1)) as sheet:
                self.assertEqual(sheet.size, (20, 20))

    def test_custom_output_and_pattern(self):
        self.image("source.jpg")
        self.image("ignored.png")
        with Image.open(self.create(filename_pattern="*.jpg", output_filename="custom.png")) as sheet:
            self.assertEqual(sheet.size, (40, 20))
            self.assertEqual(Path(sheet.filename).name, "custom.png")

    def test_unreadable_image_is_named_and_nothing_is_written(self):
        bad = self.directory / "broken.png"
        bad.write_bytes(b"not an image")
        with self.assertRaisesRegex(ValueError, "Cannot read image.*broken.png"):
            self.create()
        self.assertFalse((self.directory / "contact-sheet.png").exists())

    def test_invalid_inputs(self):
        self.image("source.png")
        for options in (
            {"columns": 0}, {"columns": True}, {"thumbnail_width": -1},
            {"thumbnail_width": 1.5}, {"background_colour": "not a colour"},
            {"background_colour": "#ffffff00"}, {"output_filename": "../source.png"}, {"output_filename": "sheet.jpg"},
            {"filename_pattern": "../*.png"}, {"filename_pattern": ""},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.create(**options)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            build_contact_sheet(str(self.directory / "missing"))

    def test_output_cannot_overwrite_source_via_link(self):
        source = self.image("source.png")
        output = self.directory / "contact-sheet.png"
        output.symlink_to(source)
        original = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.create()
        output.unlink()
        output.hardlink_to(source)
        with self.assertRaisesRegex(ValueError, "aliases"):
            self.create()
        self.assertEqual(source.read_bytes(), original)

    def _label_ink_in_column(self, sheet, cell_w, col):
        """Absolute x-positions of non-background pixels in column `col`'s label strip."""
        bg = (128, 128, 128)
        px = sheet.load()
        y0, y1 = cell_w, cell_w + LABEL_HEIGHT
        return [x for x in range(col * cell_w, (col + 1) * cell_w)
                for y in range(y0, y1) if px[x, y] != bg]

    def test_label_centred_horizontally_within_cell(self):
        # A short label in a wide cell must be centred, not stuck to the cell's
        # left edge as in the pre-centreing x=4 behaviour.
        self.image("a.png")
        cell_w = 140
        with Image.open(self.create(columns=1, thumbnail_width=cell_w, show_labels=True)) as sheet:
            xs = self._label_ink_in_column(sheet, cell_w, 0)
            self.assertTrue(xs, "expected a label in the strip")
            x_min, x_max = min(xs), max(xs)
            self.assertGreater(x_min, 4, "label should be centred, not at the old left offset")
            left_margin = x_min
            right_margin = cell_w - 1 - x_max
            self.assertLessEqual(abs(left_margin - right_margin), 6, "label should be centred")

    def test_long_label_clamped_to_cell_and_bounded(self):
        # A label wider than the cell must clamp to the cell's left edge and be
        # clipped to the cell, so no ink bleeds past the cell's right edge.
        self.image("a" * 120 + "_00001.png")
        cell_w = 40
        with Image.open(self.create(columns=1, thumbnail_width=cell_w, show_labels=True)) as sheet:
            xs = self._label_ink_in_column(sheet, cell_w, 0)
            self.assertTrue(xs, "expected a label in the strip")
            self.assertLess(min(xs), 6, "over-wide label should clamp to the cell left edge")
            self.assertLessEqual(max(xs), cell_w - 1, "label must not exceed the cell width")
            self.assertGreaterEqual(max(xs), cell_w - 2, "label should fill the cell when clipped")

    def test_multi_column_labels_confined_to_their_cells(self):
        # Long labels in different columns must each stay inside their own cell;
        # no label pixel may fall outside its column's x range.
        for idx in range(3):
            self.image(f"{'a' * 90}{idx:03d}_00001.png")
        cell_w = 40
        with Image.open(self.create(columns=3, thumbnail_width=cell_w, show_labels=True)) as sheet:
            for col in range(3):
                with self.subTest(column=col):
                    xs = self._label_ink_in_column(sheet, cell_w, col)
                    self.assertTrue(xs, "expected a label in each column")
                    for x in xs:
                        self.assertGreaterEqual(x, col * cell_w, "label pixel outside cell")
                        self.assertLess(x, (col + 1) * cell_w, "label pixel outside cell")

    def _label_ink_per_column(self, sheet, cell_w, col):
        bg = (128, 128, 128)
        px = sheet.load()
        y0 = cell_w
        y1 = cell_w + LABEL_HEIGHT
        xs = []
        for x in range(col * cell_w, (col + 1) * cell_w):
            for y in range(y0, y1):
                if px[x, y] != bg:
                    xs.append(x)
        return xs


class ContactSheetNodeTests(unittest.TestCase):
    """V3 node schema and behaviour. Runs against the host's ``comfy_api`` when
    present; under CI (no host) it runs against the minimal stand-in so the
    schema, output-node, fingerprint and trigger contracts are always checked."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.node = ImageContactSheet()

    def test_disk_changes_are_not_cached(self):
        token = self.node.fingerprint_inputs(image_directory=str(self.directory))
        self.assertNotEqual(token, token)
        self.assertTrue(self.node.OUTPUT_NODE)

    def test_trigger_is_optional_any_type(self):
        # The trigger is a connectable-but-optional AnyType socket (io_type "*"
        # — the match-all form used by native loop nodes). It is optional, so the
        # node runs unconnected.
        trigger = next(i for i in ImageContactSheet.GET_SCHEMA().inputs if i.id == "trigger")
        self.assertEqual(trigger.io_type, "*")
        self.assertTrue(trigger.optional)

    def test_execute_ignores_trigger(self):
        # The trigger value is ignored: None vs End-Loop-like values produce an
        # identical sheet.
        datas = []
        for idx, trigger_value in enumerate((None, [42, "foo"], "EndLoop")):
            workdir = Path(self.temporary.name) / f"dir-{idx}"
            workdir.mkdir()
            Image.new("RGB", (20, 20), "red").save(workdir / "a.png")
            Image.new("RGBA", (30, 10), (0, 255, 0, 128)).save(workdir / "b.png")
            output_path = Path(self.node.execute(
                str(workdir),
                output_filename="sheet.png",
                trigger=trigger_value,
            )[0])
            with Image.open(output_path) as sheet:
                datas.append(sheet.convert("RGB").tobytes())
        self.assertEqual(datas[0], datas[1])
        self.assertEqual(datas[0], datas[2])


class ContactSheetPathResolutionTests(unittest.TestCase):
    """Relative-path resolution in the V3 wrapper, anchored to a configured
    output root that is distinct from the process cwd."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # The configured output root: distinct from cwd and from ``outside``.
        self.output_root = self.root / "output"
        self.output_root.mkdir(parents=True, exist_ok=True)
        # A real sibling directory OUTSIDE the output root: used as a
        # legitimate absolute path and as a symlink escape target.
        self.outside = self.root / "outside"
        self.outside.mkdir(parents=True, exist_ok=True)

        fake = types.ModuleType("folder_paths")
        fake.get_output_directory = lambda: str(self.output_root)
        self._fp_patch = patch.dict(sys.modules, {"folder_paths": fake})
        self._fp_patch.start()
        self.addCleanup(self._fp_patch.stop)

        self.node = ImageContactSheet()

    def img(self, directory, name):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), "red").save(directory / name)

    def sheet(self, image_directory, **kwargs):
        """Run the node and return the path of the written sheet."""
        kwargs.setdefault("output_filename", "contact-sheet.png")
        return Path(self.node.execute(str(image_directory), **kwargs)[0])

    def test_root_dot_resolves_to_output_root(self):
        self.img(self.output_root, "a.png")
        out = self.sheet(".")
        self.assertEqual(out, self.output_root / "contact-sheet.png")
        self.assertTrue(out.exists())

    def test_relative_nested_resolves_under_output_root(self):
        self.img(self.output_root / "sub" / "deep", "b.png")
        out = self.sheet("sub/deep")
        self.assertEqual(
            out, self.output_root / "sub" / "deep" / "contact-sheet.png"
        )
        self.assertTrue(out.exists())

    def test_generated_sheet_lands_in_intended_dir_not_cwd(self):
        self.img(self.output_root / "results", "one.png")
        out = self.sheet("results")
        expected = self.output_root / "results" / "contact-sheet.png"
        self.assertEqual(out, expected)
        self.assertTrue(out.exists())
        # It must not have fallen back to the process cwd.
        self.assertNotIn(os.getcwd(), str(expected))

    def test_absolute_outside_output_is_preserved(self):
        self.img(self.outside, "c.png")
        out = self.sheet(str(self.outside))
        self.assertEqual(out, self.outside / "contact-sheet.png")
        self.assertEqual(out, (self.outside / "contact-sheet.png").resolve())
        # The output root itself must remain untouched.
        self.assertFalse(self.output_root.joinpath("contact-sheet.png").exists())

    def test_home_expansion_treated_as_absolute(self):
        result = _resolve_image_directory("~/contact_images")
        expected = Path(os.path.expanduser("~")) / "contact_images"
        self.assertTrue(result.is_absolute())
        self.assertEqual(result.resolve(), expected.resolve())

    def test_empty_and_whitespace_rejected(self):
        for bad in ("", "   ", "\n", "\t"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ValueError, "nonempty"
            ):
                _resolve_image_directory(bad)

    def test_missing_directory_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.sheet("nope/dontexist")

    def test_traversal_escape_rejected(self):
        for bad in ("../..", "sub/../../..", "../"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ValueError, "outside the configured output"
            ):
                _resolve_image_directory(bad)

    def test_symlink_escape_rejected(self):
        link = self.output_root / "leak"
        try:
            os.symlink(self.outside, link)
        except OSError:
            self.skipTest("cannot create symbolic links on this platform")
        def _cleanup():
            if link.is_symlink() or link.exists():
                link.unlink()

        self.addCleanup(_cleanup)
        with self.assertRaisesRegex(
            ValueError, "outside the configured output"
        ):
            _resolve_image_directory("leak")

    def test_windows_root_and_drive_relative_rejected(self):
        # Only *non-absolute* root-/drive-relative values are rejected.
        # An absolute path such as ``D:\\subdir`` is a separate, preserved
        # case (see test_absolute_outside_output_is_preserved).
        if os.name != "nt":
            self.skipTest("Windows-only path semantics")
        for bad in ("\\subdir", "/subdir", "C:subdir", "C:"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ValueError, "Cannot resolve"
            ):
                _resolve_image_directory(bad)


if __name__ == "__main__":
    unittest.main()
