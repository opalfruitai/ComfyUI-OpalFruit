from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import yaml


def _install_comfy_api_stub():
    """Install the ``comfy_api`` stand-in only when the real host is absent.

    The package registration test below loads the root ``__init__.py``, which
    imports the V3 contact-sheet node; that node imports ComfyUI's
    ``comfy_api``. CI installs only the declared dependencies, so the host is
    absent; ``tests/comfyio_stub.py`` fabricates a minimal stand-in in that case.
    When the real host is on the path nothing is installed and the real API is
    used.
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

from nodes.yaml_expressions import (
    YAMLExpressionExtractor,
    YAMLExpressionLoader,
)


class YAMLExpressionTests(unittest.TestCase):
    """Tests run with a fake ``folder_paths`` module that points ``input/`` at
    a per-test temporary directory, so the catalogue lives in ``input/yaml``."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.input_dir = Path(self.temporary.name)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.yaml_dir = self.input_dir / "yaml"
        self.yaml_dir.mkdir(parents=True, exist_ok=True)
        self.loader = YAMLExpressionLoader()
        self.extractor = YAMLExpressionExtractor()
        self.default_name = "expressions.yaml"
        self.entries = [
            {"expression": "happy", "prompt": "A happy portrait"},
            {"expression": "sad", "prompt": "A sad portrait"},
        ]
        self._install_fake_folder_paths()

    def tearDown(self):
        super().tearDown()

    def _install_fake_folder_paths(self):
        """Patch ``folder_paths`` for the duration of the test.

        ``patch.dict`` saves whatever is already in ``sys.modules`` and restores
        it on teardown, so a real ``folder_paths`` module (host present) is
        preserved, while a test-only stand-in is cleanly removed.
        """
        fake = types.ModuleType("folder_paths")
        fake.get_input_directory = lambda: str(self.input_dir)
        self._fp_patch = patch.dict(sys.modules, {"folder_paths": fake})
        self._fp_patch.start()
        self.addCleanup(self._fp_patch.stop)

    def write(self, data, filename=None):
        self.yaml_dir.mkdir(parents=True, exist_ok=True)
        name = filename or self.default_name
        (self.yaml_dir / name).write_text(yaml.safe_dump(data), encoding="utf-8")
        return self.yaml_dir / name

    def catalogue_files(self):
        """The dropdown file list the node would expose."""
        return self.loader.INPUT_TYPES()["required"]["yaml_path"][0]

    def test_valid_catalogue_and_list_contract(self):
        self.write({"seed": 42, "expressions": self.entries})
        entries, seed = self.loader.load(self.default_name)
        self.assertEqual(entries, self.entries)
        self.assertEqual(seed, 42)
        self.assertEqual(self.loader.OUTPUT_IS_LIST, (True, False))
        self.assertEqual(
            self.loader.RETURN_TYPES[0],
            self.extractor.INPUT_TYPES()["required"]["expression"][0],
        )
        self.assertEqual(
            [self.extractor.extract(entry) for entry in entries],
            [("happy", "A happy portrait"), ("sad", "A sad portrait")],
        )
        self.assertFalse(getattr(self.extractor, "INPUT_IS_LIST", False))

    def test_invalid_catalogues(self):
        invalid = [
            None, [], "catalogue", {},
            {"expressions": self.entries},
            {"seed": True, "expressions": self.entries},
            {"seed": 1.5, "expressions": self.entries},
            {"seed": "42", "expressions": self.entries},
            {"seed": 42},
            {"seed": 42, "expressions": []},
            {"seed": 42, "expressions": {}},
            {"seed": 42, "expressions": ["happy"]},
            {"seed": 42, "expressions": [{"expression": "happy"}]},
            {"seed": 42, "expressions": [{"prompt": "portrait"}]},
            {"seed": 42, "expressions": [{"expression": 1, "prompt": "portrait"}]},
            {"seed": 42, "expressions": [{"expression": "happy", "prompt": None}]},
        ]
        for data in invalid:
            with self.subTest(data=data):
                self.write(data)
                with self.assertRaises(ValueError):
                    self.loader.load(self.default_name)

    def test_negative_seed_rejected(self):
        self.write({"seed": -1, "expressions": self.entries})
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            self.loader.load(self.default_name)
        self.write({"seed": 0, "expressions": self.entries})
        _, seed = self.loader.load(self.default_name)
        self.assertEqual(seed, 0)

    def test_empty_or_whitespace_name_and_prompt_rejected(self):
        invalid_entries = [
            {"expression": "", "prompt": "A portrait"},
            {"expression": "  ", "prompt": "A portrait"},
            {"expression": "\t", "prompt": "A portrait"},
            {"expression": "happy", "prompt": ""},
            {"expression": "happy", "prompt": "  "},
        ]
        for entry in invalid_entries:
            with self.subTest(entry=entry):
                self.write({"seed": 42, "expressions": [entry, self.entries[1]]})
                with self.assertRaisesRegex(ValueError, "must be nonempty"):
                    self.loader.load(self.default_name)

    def test_duplicate_names(self):
        self.write({"seed": 42, "expressions": [self.entries[0], self.entries[0]]})
        with self.assertRaisesRegex(ValueError, "Duplicate expression"):
            self.loader.load(self.default_name)

    def test_duplicate_names_case_insensitive(self):
        entries = [
            {"expression": "Happy", "prompt": "one"},
            {"expression": "happy", "prompt": "two"},
            {"expression": "HAPpY", "prompt": "three"},
        ]
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                with self.subTest(i=i, j=j):
                    self.write({"seed": 42, "expressions": [entries[i], entries[j]]})
                    with self.assertRaisesRegex(ValueError, "Duplicate expression"):
                        self.loader.load(self.default_name)

    def test_malformed_yaml_and_missing_file(self):
        # Raw malformed YAML: written byte-for-byte, not through the dump helper,
        # so it stays unparseable.
        for text in ("expressions: [", "!!python/object/apply:os.system ['echo unsafe']"):
            (self.yaml_dir / "bad.yaml").write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Cannot read YAML"):
                self.loader.load("bad.yaml")
        self.write({"seed": 42, "expressions": self.entries})
        (self.yaml_dir / self.default_name).unlink()
        with self.assertRaisesRegex(ValueError, "Cannot read YAML"):
            self.loader.load(self.default_name)

    def test_content_changes_invalidate_cache_even_with_same_metadata(self):
        self.write({"seed": 42, "expressions": self.entries})
        before = self.loader.IS_CHANGED(self.default_name)
        stat = (self.yaml_dir / self.default_name).stat()
        self.write(
            (self.yaml_dir / self.default_name).read_text(encoding="utf-8").replace("happy", "jolly"),
            filename=self.default_name,
        )
        os.utime(self.yaml_dir / self.default_name, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertNotEqual(before, self.loader.IS_CHANGED(self.default_name))
        self.assertEqual(
            self.loader.IS_CHANGED(self.default_name), self.loader.IS_CHANGED(self.default_name)
        )
        (self.yaml_dir / self.default_name).unlink()
        self.assertNotEqual(before, self.loader.IS_CHANGED(self.default_name))

    def test_extractor_rejects_malformed_input(self):
        for value in (None, [], "happy", {}, {"expression": "happy"},
                      {"expression": False, "prompt": "portrait"},
                      {"expression": "happy", "prompt": 5}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.extractor.extract(value)

    # ---------------------------------------------------------------------------
    # File selection (FR-01, FR-02)
    # ---------------------------------------------------------------------------

    def test_discovers_yaml_and_yml_files(self):
        (self.yaml_dir / "b.yml").write_text("seed: 1\n", encoding="utf-8")
        (self.yaml_dir / "a.yaml").write_text("seed: 2\n", encoding="utf-8")
        (self.yaml_dir / "c.YAML").write_text("seed: 3\n", encoding="utf-8")
        self.assertEqual(self.catalogue_files(), ["a.yaml", "b.yml", "c.YAML"])

    def test_excludes_unsupported_files_and_directories(self):
        (self.yaml_dir / "notes.txt").write_text("hi\n", encoding="utf-8")
        (self.yaml_dir / "pic.png").write_bytes(b"\x89PNG")
        (self.yaml_dir / "empty").mkdir()
        (self.yaml_dir / "empty" / "inner.yaml").write_text("seed: 1\n", encoding="utf-8")
        (self.yaml_dir / "valid.yaml").write_text("seed: 1\n", encoding="utf-8")
        self.assertEqual(self.catalogue_files(), ["valid.yaml"])

    def test_ordering_is_alphabetical_and_deterministic(self):
        for name in ("zeta.yaml", "alpha.yml", "mid.yaml", "Beta.yaml"):
            (self.yaml_dir / name).write_text("seed: 1\n", encoding="utf-8")
        self.assertEqual(self.catalogue_files(), sorted(self.catalogue_files()))
        self.assertEqual(self.catalogue_files(), self.catalogue_files())

    def test_missing_and_empty_catalogue_directory(self):
        """The dropdown is empty whether the yaml directory is missing or
        empty. Both cases are genuinely exercised: setUp creates yaml/, so
        the missing case removes it first.
        """
        with self.subTest("missing directory"):
            self.yaml_dir.rmdir()
            self.assertEqual(self.catalogue_files(), [])
        with self.subTest("empty directory"):
            self.yaml_dir.mkdir(parents=True)
            self.assertEqual(self.catalogue_files(), [])

    def test_loads_each_selected_file(self):
        data = {
            "ava.yaml": {"seed": 1, "expressions": [{"expression": "a", "prompt": "p"}]},
            "emily.yml": {"seed": 2, "expressions": [{"expression": "e", "prompt": "q"}]},
            "expressions.yaml": {"seed": 3, "expressions": [{"expression": "x", "prompt": "r"}]},
        }
        for name in data:
            self.yaml_dir.mkdir(parents=True, exist_ok=True)
            (self.yaml_dir / name).write_text(yaml.safe_dump(data[name]), encoding="utf-8")
        with self.subTest(name="ava.yaml"):
            self.assertEqual(self.loader.load("ava.yaml"), (data["ava.yaml"]["expressions"], 1))
        with self.subTest(name="emily.yml"):
            self.assertEqual(self.loader.load("emily.yml"), (data["emily.yml"]["expressions"], 2))
        with self.subTest(name="expressions.yaml"):
            self.assertEqual(self.loader.load("expressions.yaml"), (data["expressions.yaml"]["expressions"], 3))

    def test_workflow_stores_relative_filename_not_absolute(self):
        (self.yaml_dir / "ava.yaml").write_text("seed: 1\n", encoding="utf-8")
        names = self.catalogue_files()
        for name in names:
            self.assertTrue(name.endswith(".yaml") or name.endswith(".yml"))
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)

    def test_consecutive_dots_in_filename_resolve(self):
        """A filename with consecutive dots that is not a traversal component
        (e.g. 'my..file.yaml') is a valid catalogue file: it is listed and loads.
        """
        (self.yaml_dir / "my..file.yaml").write_text(
            yaml.safe_dump({"seed": 5, "expressions": self.entries}),
            encoding="utf-8",
        )
        self.assertIn("my..file.yaml", self.catalogue_files())
        entries, seed = self.loader.load("my..file.yaml")
        self.assertEqual(entries, self.entries)
        self.assertEqual(seed, 5)

    def test_rejects_unsupported_extension_at_resolution(self):
        """Resolution rejects extensions the dropdown never offers, not just
        leaving them out of the list. Case-insensitive .yaml/.yml is accepted.
        """
        (self.yaml_dir / "notes.txt").write_text("hi\n", encoding="utf-8")
        self.assertNotIn("notes.txt", self.catalogue_files())
        with self.assertRaisesRegex(
            ValueError, "Invalid YAML catalogue file name"
        ):
            self.loader.load("notes.txt")
        (self.yaml_dir / "upper.YML").write_text(
            yaml.safe_dump({"seed": 5, "expressions": self.entries}),
            encoding="utf-8",
        )
        self.assertIn("upper.YML", self.catalogue_files())
        self.loader.load("upper.YML")

    # ---------------------------------------------------------------------------
    # Security (FR-03 / security requirements)
    # ---------------------------------------------------------------------------

    def test_rejects_absolute_and_traversal_paths(self):
        self.write({"seed": 1, "expressions": [{"expression": "x", "prompt": "p"}]})
        bad = [
            None, "",
            "/absolute/catalogue.yaml",
            "C:\\Windows\\Catalogue.yaml",
            "../outside.yaml",
            "..\\outside.yaml",
            "../../etc/passwd",
            "subdir/inner.yaml",
            ".\\outer.yaml",
            ".",
            "..",
            "valid.yaml/../../evil.yaml",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, r"(Invalid YAML catalogue|file name is required)"
            ):
                self.loader.load(value)

    def test_rejects_symlink_escaping_catalogue_directory(self):
        secret_dir = Path(self.temporary.name) / "secret"
        secret_dir.mkdir(parents=True, exist_ok=True)
        # A target outside the catalogue directory that is itself a valid YAML file.
        (secret_dir / "secret.yaml").write_text("seed: 999\nexpressions: []\n", encoding="utf-8")
        self.yaml_dir.mkdir(parents=True, exist_ok=True)
        link = self.yaml_dir / "leak.yaml"
        try:
            link.symlink_to(secret_dir / "secret.yaml")
        except OSError:
            self.skipTest("symbolic link creation unsupported on this platform")
        with self.assertRaisesRegex(ValueError, "points outside the catalogue directory"):
            self.loader.load("leak.yaml")
        # The dropdown must not list escaping links.
        self.assertNotIn("leak.yaml", self.catalogue_files())

    def test_rejects_symlink_inside_catalogue_directory(self):
        """A symbolic link that stays inside the directory is rejected at
        resolution (and at discovery), matching the dropdown which excludes all
        symlinks.
        """
        (self.yaml_dir / "target.yaml").write_text(
            yaml.safe_dump({"seed": 7, "expressions": [{"expression": "x", "prompt": "p"}]}),
            encoding="utf-8",
        )
        link = self.yaml_dir / "link.yaml"
        try:
            link.symlink_to("target.yaml")
        except OSError:
            self.skipTest("symbolic link creation unsupported on this platform")
        self.assertNotIn("link.yaml", self.catalogue_files())
        with self.assertRaisesRegex(
            ValueError, "Invalid YAML catalogue file name"
        ):
            self.loader.load("link.yaml")

    def test_rejects_deleted_or_renamed_catalogue(self):
        self.write({"seed": 1, "expressions": [{"expression": "x", "prompt": "p"}]})
        self.loader.load(self.default_name)
        (self.yaml_dir / self.default_name).rename(self.yaml_dir / "renamed.yaml")
        with self.assertRaisesRegex(ValueError, "Cannot read YAML"):
            self.loader.load(self.default_name)
        (self.yaml_dir / "renamed.yaml").unlink()
        with self.assertRaisesRegex(ValueError, "Cannot read YAML"):
            self.loader.load(self.default_name)

    def test_package_registration(self):
        # Registering the package executes the V3 contact-sheet node, which
        # imports ComfyUI's ``comfy_api``. With the host on the path this uses
        # the real API; under CI the test stand-in stands in for it, so this
        # always runs (never skipped).
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "opalfruit_test_package", root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name)
        spec.loader.exec_module(module)
        self.assertEqual(len(module.NODE_CLASS_MAPPINGS), 3)
        self.assertEqual(
            module.NODE_CLASS_MAPPINGS.keys(), module.NODE_DISPLAY_NAME_MAPPINGS.keys()
        )
        for node in module.NODE_CLASS_MAPPINGS.values():
            self.assertTrue(callable(getattr(node(), node.FUNCTION)))
            self.assertIn(node.CATEGORY, ("OpalFruit/YAML", "OpalFruit/Image"))


if __name__ == "__main__":
    unittest.main()
