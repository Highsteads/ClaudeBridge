#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_config_xml.py
# Description: Dialog-XML guards. A plugin never parses its own ConfigUI/Devices/Actions
#              XML — the Indigo CLIENT does, at the moment a user opens the dialog — so
#              none of these faults can be caught by a plugin restart, by the event log,
#              by ruff, or by any other test. They are only visible to a human opening
#              the dialog, which is why they go unnoticed for months.
# Author:      CliveS & Claude Opus 5
# Date:        07-09-2026
# Version:     1.0

import collections
import glob
import os
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_xml_files():
    """The dialog XML, whether this test sits inside the bundle or in a tests/ dir.

    Found by glob rather than by a hard-coded path, so the file drops into any repo
    unchanged — the same approach test_version_consistency.py uses to find the bundle.
    """
    here = sorted(glob.glob(os.path.join(HERE, "*.xml")))
    if here:
        return here
    d = HERE
    for _ in range(4):                       # walk up looking for the bundle
        found = sorted(glob.glob(os.path.join(
            d, "*.indigoPlugin", "Contents", "Server Plugin", "*.xml")))
        if found:
            return found
        d = os.path.dirname(d)
    return []


XML_FILES = _find_xml_files()

# Indigo right-aligns every control's <Label> and places the control immediately to its
# right (official-plugin-xml.md: "each of those Label elements is right aligned and the
# actual control is left aligned directly to the right of the label"), so the WIDEST label
# sets the control column for the whole dialog — and the dialog window has a hard maximum
# width (MEASURED 07-09-2026: System Events refused to set one wider than 1041 pt, from
# both 1200 and 2000). A 231-character label put every control at x=1425, i.e. 384 pt off
# the right edge of the window, with no horizontal scrollbar and no way to widen it.
MAX_CONTROL_LABEL_CHARS = 100

# A <Description> is drawn on ONE line at its natural width and NEVER wraps, so the longest
# one in a dialog sets the content width for every row in it. MEASURED 07-09-2026 by
# shortening a single 403-character Description and reopening the dialog: the window went
# 1041 -> 741 and the widest text frame 2890 -> 712. At 2890 every line of help text was
# clipped by 1849 pt. A type="label" field DOES wrap, so a paragraph belongs there.
MAX_DESCRIPTION_CHARS = 100


def _dialog_scopes(root, filename):
    """Every scope in which Field ids must be unique: the root for PluginConfig.xml,
    each <ConfigUI> elsewhere. Ids only need to be unique within one dialog."""
    if os.path.basename(filename) == "PluginConfig.xml":
        return [("<root>", root)]
    scopes = [(f"ConfigUI[{i}]", cfg) for i, cfg in enumerate(root.iter("ConfigUI"))]
    return scopes or [("<root>", root)]


def _label_text(field):
    label = field.find("Label")
    return (label.text or "").strip() if label is not None else ""


class TestDialogXml(unittest.TestCase):

    def test_there_are_xml_files_to_check(self):
        # A glob that silently matches nothing would make every test below pass.
        self.assertTrue(XML_FILES, "no XML files found — the check is not checking")

    def test_every_xml_file_parses(self):
        for path in XML_FILES:
            with self.subTest(file=os.path.basename(path)):
                ET.parse(path)

    def test_every_field_has_an_id(self):
        for path in XML_FILES:
            root = ET.parse(path).getroot()
            for field in root.iter("Field"):
                self.assertTrue(
                    field.get("id"),
                    f"{os.path.basename(path)}: a Field with no id")

    def test_field_ids_unique_within_each_dialog(self):
        """A duplicate id makes the Indigo client refuse to build the dialog at all —
        it does not open, and nothing is logged plugin-side."""
        for path in XML_FILES:
            root = ET.parse(path).getroot()
            for name, scope in _dialog_scopes(root, path):
                ids = [f.get("id") for f in scope.iter("Field") if f.get("id")]
                dupes = [i for i, n in collections.Counter(ids).items() if n > 1]
                self.assertEqual(
                    dupes, [],
                    f"{os.path.basename(path)} {name}: duplicate Field ids {dupes}")

    def test_visible_bindings_point_at_a_field_in_the_same_dialog(self):
        """A visibleBindingId naming a field that isn't there hides the row for good,
        silently — the mirror of the duplicate-id fault, and harder to notice."""
        for path in XML_FILES:
            root = ET.parse(path).getroot()
            for name, scope in _dialog_scopes(root, path):
                ids = {f.get("id") for f in scope.iter("Field")}
                for field in scope.iter("Field"):
                    binding = field.get("visibleBindingId")
                    if binding:
                        self.assertIn(
                            binding, ids,
                            f"{os.path.basename(path)} {name}: {field.get('id')} binds to "
                            f"'{binding}', which is not a field in this dialog")


class TestDialogWidth(unittest.TestCase):
    """Two independent ways to stretch a dialog past a window that cannot be widened."""

    def _control_labels(self):
        found = []
        for path in XML_FILES:
            root = ET.parse(path).getroot()
            for field in root.iter("Field"):
                if field.get("type") in ("label", "separator"):
                    continue
                found.append((os.path.basename(path), field.get("id"), _label_text(field)))
        return found

    def _descriptions(self):
        found = []
        for path in XML_FILES:
            root = ET.parse(path).getroot()
            for field in root.iter("Field"):
                desc = field.find("Description")
                if desc is not None:
                    found.append((os.path.basename(path), field.get("id"),
                                  (desc.text or "").strip()))
        return found

    def test_there_are_control_labels_to_check(self):
        """A scan that matches nothing passes every assertion after it.

        The bar is "found something", not a size: a small plugin can legitimately
        have five settings, and an arbitrary threshold fails it for being small.
        """
        self.assertTrue(
            self._control_labels(),
            "no control-bearing fields found — the width checks are not checking")

    def test_no_control_label_is_a_paragraph(self):
        too_long = [(f, i, len(t)) for f, i, t in self._control_labels()
                    if len(t) > MAX_CONTROL_LABEL_CHARS]
        self.assertEqual(
            too_long, [],
            "These control Labels are long enough to push the control column off the "
            'dialog — move the prose into a type="label" field below the control:\n'
            + "\n".join(f"  {f} {i}: {n} chars" for f, i, n in too_long))

    def test_no_description_is_a_paragraph(self):
        too_long = [(f, i, len(t)) for f, i, t in self._descriptions()
                    if len(t) > MAX_DESCRIPTION_CHARS]
        self.assertEqual(
            too_long, [],
            "A <Description> never wraps, so these stretch every row of their dialog "
            'past the window — move the prose into a type="label" field below the '
            "control:\n"
            + "\n".join(f"  {f} {i}: {n} chars" for f, i, n in too_long))


if __name__ == "__main__":
    unittest.main()
