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


def _needs_regeneration(note, flds, stored_hashes):
    """Check if a note needs regeneration.

    Returns True if:
    - Original field hash changed
    - OR Original field has content but Full field is empty
    """
    nid_str = str(note.id)

    # Get field values
    original = note.get(flds["og"], "").strip()
    full = note.get(flds["fl"], "").strip()

    # If Original is empty, nothing to regenerate
    if not original:
        return False

    # Check if Full field is empty but Original has content
    if not full:
        return True

    # Check if hash changed
    current_hash = _compute_note_hash(note, flds)
    if nid_str not in stored_hashes or stored_hashes[nid_str] != current_hash:
        return True

    return False


def _compute_note_hash(note, flds):
    """Compute hash of note's input fields (Original + Settings)"""
    original = note.get(flds["og"], "")
    settings = note.get(flds["st"], "")
    content = f"{original}|{settings}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def regenerateAllClozes():
    """Regenerate overlapping clozes for notes that need it.

    Regenerates if:
    - Original field hash changed since last regeneration
    - OR Original field has content but Full field is empty
    """

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

    # Process each note - only if changed or Full is empty
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

                # Check if regeneration is needed
                if not _needs_regeneration(note, flds, stored_hashes):
                    skipped += 1
                    continue

                # Regenerate clozes silently
                overlapper = ClozeOverlapper(note, silent=True)
                ret, total = overlapper.add()

                if ret:
                    updated += 1
                    # Update stored hash
                    nid_str = str(nid)
                    current_hash = _compute_note_hash(note, flds)
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


def regenerateSingleNote(note):
    """Regenerate overlapping clozes for a single note if needed.

    Regenerates if:
    - Original field hash changed
    - OR Original field has content but Full field is empty
    """
    flds = config["synced"]["flds"]

    # Check if it's a valid OLC model
    if not checkModel(note.model(), fields=True, notify=False):
        return False

    stored_hashes = _load_hashes()

    # Check if regeneration is needed
    if not _needs_regeneration(note, flds, stored_hashes):
        return False

    # Regenerate clozes silently
    overlapper = ClozeOverlapper(note, silent=True)
    ret, total = overlapper.add()

    if ret:
        # Update stored hash
        nid_str = str(note.id)
        current_hash = _compute_note_hash(note, flds)
        stored_hashes[nid_str] = current_hash
        _save_hashes(stored_hashes)
        print(f"Cloze Overlapper: Regenerated {total} clozes for note {note.id}")
        return True

    return False


def regenerateNoteById(note_id):
    """Regenerate overlapping clozes for a note by its ID"""
    col = mw.col
    if not col:
        return False

    try:
        note = col.getNote(note_id)
        return regenerateSingleNote(note)
    except Exception as e:
        print(f"Cloze Overlapper: Error regenerating note {note_id}: {e}")
        return False


def hookAnkiConnect():
    """Hook into AnkiConnect to detect note updates"""
    try:
        # Try to find the AnkiConnect addon
        ankiconnect_addon = None
        for name in ["2055492159", "ankiconnect"]:
            addon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), name)
            if os.path.exists(addon_dir):
                ankiconnect_addon = addon_dir
                break

        if not ankiconnect_addon:
            print("Cloze Overlapper: AnkiConnect not found, hook-based regeneration disabled")
            return False

        # Import AnkiConnect's module
        import sys
        if ankiconnect_addon not in sys.path:
            sys.path.insert(0, os.path.dirname(ankiconnect_addon))

        # Try to wrap AnkiConnect's updateNoteFields action
        try:
            import importlib
            ac_module_name = os.path.basename(ankiconnect_addon)

            # Get the AnkiConnect web module
            ac_web = importlib.import_module(f"{ac_module_name}.web")

            if hasattr(ac_web, 'AnkiConnect'):
                original_updateNoteFields = getattr(ac_web.AnkiConnect, 'updateNoteFields', None)
                original_updateNote = getattr(ac_web.AnkiConnect, 'updateNote', None)
                original_updateNoteModel = getattr(ac_web.AnkiConnect, 'updateNoteModel', None)

                olc_models = config["synced"].get("olmdls", [OLC_MODEL])

                def wrapped_updateNoteFields(self, note):
                    result = original_updateNoteFields(self, note)
                    try:
                        note_id = note.get('id')
                        if note_id:
                            # Check if it's an OLC model and regenerate
                            col = mw.col
                            if col:
                                anki_note = col.getNote(note_id)
                                model_name = anki_note.model()["name"]
                                if model_name in olc_models:
                                    mw.progress.timer(100, lambda: regenerateNoteById(note_id), False)
                    except Exception as e:
                        print(f"Cloze Overlapper: Error in updateNoteFields hook: {e}")
                    return result

                def wrapped_updateNote(self, note):
                    result = original_updateNote(self, note)
                    try:
                        note_id = note.get('id')
                        if note_id:
                            col = mw.col
                            if col:
                                anki_note = col.getNote(note_id)
                                model_name = anki_note.model()["name"]
                                if model_name in olc_models:
                                    mw.progress.timer(100, lambda: regenerateNoteById(note_id), False)
                    except Exception as e:
                        print(f"Cloze Overlapper: Error in updateNote hook: {e}")
                    return result

                def wrapped_updateNoteModel(self, note):
                    result = original_updateNoteModel(self, note)
                    try:
                        note_id = note.get('id')
                        if note_id:
                            col = mw.col
                            if col:
                                anki_note = col.getNote(note_id)
                                model_name = anki_note.model()["name"]
                                if model_name in olc_models:
                                    mw.progress.timer(100, lambda: regenerateNoteById(note_id), False)
                    except Exception as e:
                        print(f"Cloze Overlapper: Error in updateNoteModel hook: {e}")
                    return result

                if original_updateNoteFields:
                    ac_web.AnkiConnect.updateNoteFields = wrapped_updateNoteFields
                    print("Cloze Overlapper: Hooked into AnkiConnect.updateNoteFields")

                if original_updateNote:
                    ac_web.AnkiConnect.updateNote = wrapped_updateNote
                    print("Cloze Overlapper: Hooked into AnkiConnect.updateNote")

                if original_updateNoteModel:
                    ac_web.AnkiConnect.updateNoteModel = wrapped_updateNoteModel
                    print("Cloze Overlapper: Hooked into AnkiConnect.updateNoteModel")

                return True

        except Exception as e:
            print(f"Cloze Overlapper: Could not hook AnkiConnect actions: {e}")
            return False

    except Exception as e:
        print(f"Cloze Overlapper: Error setting up AnkiConnect hooks: {e}")
        return False


def initializeBatchRegeneration():
    """Initialize batch regeneration on startup and hook into AnkiConnect"""
    from anki.hooks import addHook

    def onProfileLoaded():
        # Run regeneration after a short delay to let Anki fully load
        mw.progress.timer(1000, regenerateAllClozes, False)

        # Try to hook into AnkiConnect for real-time regeneration
        mw.progress.timer(2000, hookAnkiConnect, False)

    addHook("profileLoaded", onProfileLoaded)
