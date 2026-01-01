# -*- coding: utf-8 -*-

# Cloze Overlapper Add-on for Anki
#
# Batch regeneration of overlapping clozes

"""
Batch operations for regenerating overlapping clozes
"""

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import hashlib
import json
import os

from aqt import mw
from aqt.utils import showInfo, tooltip
from aqt.qt import QApplication

from .overlapper import ClozeOverlapper
from .template import checkModel
from .config import config
from .consts import OLC_MODEL


def _get_hash_file_path():
    """Get path to the hash cache file"""
    addon_dir = os.path.dirname(__file__)
    data_dir = os.path.join(addon_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "note_hashes.json")


def _load_hashes():
    """Load stored note hashes from disk"""
    path = _get_hash_file_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_hashes(hashes):
    """Save note hashes to disk"""
    path = _get_hash_file_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hashes, f)
    except IOError as e:
        print(f"Error saving hash cache: {e}")


def _compute_note_hash(note, flds):
    """Compute hash of note's input fields (Original + Settings)"""
    original = note.get(flds["og"], "")
    settings = note.get(flds["st"], "")
    content = f"{original}|{settings}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def regenerateAllClozes():
    """Regenerate overlapping clozes only for notes that changed"""

    col = mw.col
    if not col:
        return

    # Get all note type names that are OLC models
    olc_models = config["synced"].get("olmdls", [OLC_MODEL])
    flds = config["synced"]["flds"]

    # Find all notes using OLC note types
    note_ids = []
    for model_name in olc_models:
        model = col.models.byName(model_name)
        if model:
            # Search for notes with this model
            nids = col.findNotes(f'"note:{model_name}"')
            note_ids.extend(nids)

    if not note_ids:
        return

    # Load stored hashes
    stored_hashes = _load_hashes()

    # Process each note - only if changed
    updated = 0
    skipped = 0
    errors = 0

    mw.progress.start(max=len(note_ids), label="Checking overlapping clozes...")

    try:
        for i, nid in enumerate(note_ids):
            try:
                note = col.getNote(nid)

                # Check if it's a valid OLC model
                if not checkModel(note.model(), fields=True, notify=False):
                    continue

                # Compute current hash
                nid_str = str(nid)
                current_hash = _compute_note_hash(note, flds)

                # Skip if hash unchanged
                if nid_str in stored_hashes and stored_hashes[nid_str] == current_hash:
                    skipped += 1
                    continue

                # Regenerate clozes silently
                overlapper = ClozeOverlapper(note, silent=True)
                ret, total = overlapper.add()

                if ret:
                    updated += 1
                    # Update stored hash
                    stored_hashes[nid_str] = current_hash

            except Exception as e:
                errors += 1
                print(f"Error regenerating note {nid}: {e}")

            mw.progress.update(value=i + 1)
            QApplication.processEvents()

    finally:
        mw.progress.finish()
        # Save updated hashes
        _save_hashes(stored_hashes)

    if updated > 0 or errors > 0:
        tooltip(f"Regenerated {updated} cloze notes ({skipped} unchanged)" +
                (f" ({errors} errors)" if errors else ""), period=3000)


def initializeBatchRegeneration():
    """Initialize batch regeneration to run on startup"""
    from anki.hooks import addHook
    
    def onProfileLoaded():
        # Run regeneration after a short delay to let Anki fully load
        mw.progress.timer(1000, regenerateAllClozes, False)
    
    addHook("profileLoaded", onProfileLoaded)
