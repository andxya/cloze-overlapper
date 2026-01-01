# -*- coding: utf-8 -*-

# Cloze Overlapper Add-on for Anki
#
# Copyright (C) 2016-2019  Aristotelis P. <https://glutanimate.com/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the license file that accompanied this program
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License that
# accompanied this program.
#
# If not, please request a copy through one of the means of contact
# listed here: <https://glutanimate.com/contact/>.
#
# Any modifications to this file must keep this entire header intact.

"""
Handles add-on configuration
"""

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import re

from aqt import mw
from anki.utils import stripHTML

from .libaddon.anki.configmanager import ConfigManager

from .consts import *
from . import utils


def parseNoteSettings(html):
    """Return note settings. Fall back to defaults if necessary."""
    options, settings, opts, sets = None, None, None, None
    dflt_set, dflt_opt = config["synced"]["dflts"], config["synced"]["dflto"]
    field = stripHTML(html)

    lines = field.replace(" ", "").split("|")
    if not lines:
        return (dflt_set, dflt_opt)
    settings = lines[0].split(",")
    if len(lines) > 1:
        options = lines[1].split(",")

    if not options and not settings:
        return (dflt_set, dflt_opt)

    if not settings:
        sets = dflt_set
    else:
        sets = []
        for idx, item in enumerate(settings[:3]):
            try:
                sets.append(int(item))
            except ValueError:
                sets.append(None)
        length = len(sets)
        if length == 3 and isinstance(sets[1], int):
            pass
        elif length == 2 and isinstance(sets[0], int):
            sets = [sets[1], sets[0], sets[1]]
        elif length == 1 and isinstance(sets[0], int):
            sets = [dflt_set[0], sets[0], dflt_set[2]]
        else:
            sets = dflt_set

    if not options:
        opts = dflt_opt
    else:
        opts = []
        for i in range(4):
            try:
                if options[i] == "y":
                    opts.append(True)
                else:
                    opts.append(False)
            except IndexError:
                opts.append(dflt_opt[i])

    return (sets, opts)


def createNoteSettings(setopts):
    """Create plain text settings string"""
    set_str = ",".join(str(i) if i is not None else "all" for i in setopts[0])
    opt_str = ",".join("y" if i else "n" for i in setopts[1])
    return set_str + " | " + opt_str


# TODO: refactor lists into dicts
# dflts: before, prompt, after
# dflto: no-context-first, no-context-last, gradual ends, no full cloze
# sched: no-siblings new, no-siblings review, auto-suspend full cloze
# syntax: wrapper_start, wrapper_end, prefix (for overlapping cloze markers)
#   Default: {{o1::text}} format
#   wrapper_start: "{{" - opening characters
#   wrapper_end: "}}" - closing characters  
#   prefix: "o" - prefix before the number (e.g., "o" gives o1, o2, etc.)
config_defaults = {
    "synced": {
        "dflts": [1, 1, 0],
        "dflto": [False, False, True, False],  # gradual build-up/-down enabled by default
        "flds": OLC_FLDS,
        "sched": [
            utils.can_override_scheduler(),
            utils.can_override_scheduler(),
            False
        ],
        "olmdls": [OLC_MODEL],
        "syntax": {
            "wrapper_start": "{{",
            "wrapper_end": "}}",
            "prefix": "o"
        },
        "version": ADDON.VERSION
    }
}

config = ConfigManager(mw, config_dict=config_defaults,
                       conf_key="olcloze")


def migrate_config():
    """Migrate old config values to new defaults.
    
    This handles the field name changes:
    - 'Text' -> 'Original' (fix for broken earlier version)
    - 'Remarks' -> 'Back Extra'
    
    And ensures syntax config exists, and enables gradual build-up/-down.
    """
    needs_save = False
    
    # Migrate field names
    flds = config["synced"].get("flds", {})
    
    # Fix 'og' field: Text -> Original (revert broken change)
    if flds.get("og") == "Text":
        config["synced"]["flds"]["og"] = "Original"
        needs_save = True
    
    # Migrate 'rk' field: Remarks -> Back Extra
    if flds.get("rk") == "Remarks":
        config["synced"]["flds"]["rk"] = "Back Extra"
        needs_save = True
    
    # Ensure syntax config exists with defaults
    if "syntax" not in config["synced"]:
        config["synced"]["syntax"] = {
            "wrapper_start": "{{",
            "wrapper_end": "}}",
            "prefix": "o"
        }
        needs_save = True
    
    # Enable gradual build-up/-down by default (index 2 in dflto)
    dflto = config["synced"].get("dflto", [False, False, False, False])
    if len(dflto) >= 3 and dflto[2] == False:
        config["synced"]["dflto"][2] = True
        needs_save = True
    
    if needs_save:
        config.save()


# Migration will be called from __init__.py after profile is loaded


def get_cloze_regex():
    """Build regex pattern for matching overlapping cloze markers based on config.
    
    Default syntax: {{o1::text}} or {{o1::text::hint}}
    The pattern captures:
      - Group 1: The cloze number
      - Group 2: The full content (text and optional hint)
      - Group 3: The text
      - Group 4: The hint separator and hint (if present)
      - Group 5: The hint (if present)
    """
    syntax = config["synced"].get("syntax", {
        "wrapper_start": "{{",
        "wrapper_end": "}}",
        "prefix": "o"
    })
    
    ws = re.escape(syntax["wrapper_start"])
    we = re.escape(syntax["wrapper_end"])
    prefix = re.escape(syntax["prefix"])
    
    # Pattern: {{o(\d+)::((.*?)(::(.*?))?)?}}
    return r"(?s)" + ws + prefix + r"(\d+)::((.*?)(::(.*?))?)?" + we


def get_syntax_example():
    """Return an example of the current cloze syntax for display."""
    syntax = config["synced"].get("syntax", {
        "wrapper_start": "{{",
        "wrapper_end": "}}",
        "prefix": "o"
    })
    return "{ws}{p}1::text{we}".format(
        ws=syntax["wrapper_start"],
        p=syntax["prefix"],
        we=syntax["wrapper_end"]
    )
