# -*- coding: utf-8 -*-

# Cloze Overlapper Add-on for Anki
#
# Copyright (C)  2016-2019 Aristotelis P. <https://glutanimate.com/>
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
Adds overlapping clozes
"""

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from .libaddon.platform import ANKI20

import re
from operator import itemgetter
from itertools import groupby

if ANKI20:
    from BeautifulSoup import BeautifulSoup
else:
    from bs4 import BeautifulSoup

from .config import config, parseNoteSettings, createNoteSettings, get_cloze_regex
from .generator import ClozeGenerator
from .utils import warnUser, showTT


class ClozeOverlapper(object):
    """Reads note, calls ClozeGenerator, writes results back to note"""

    def __init__(self, note, markup=False, silent=False, parent=None):
        self.note = note
        self.model = self.note.model()
        self.flds = config["synced"]["flds"]
        self.markup = markup
        self.silent = silent
        self.parent = parent
        # Build regex pattern from config
        self.creg = get_cloze_regex()

    def showTT(self, title, text, period=3000):
        showTT(title, text, period, parent=self.parent)

    def add(self):
        """Add overlapping clozes to note, or pass through regular clozes"""
        original = self.note[self.flds["og"]]
        if not original:
            self.showTT(
                "Reminder",
                "Please enter some text in the '%s' field" % self.flds["og"])
            return False, None

        # Check for regular Anki clozes {{c1::...}}
        anki_cloze_re = r"(?s)\{\{c(\d+)::((.*?)(::(.*?))?)?\}\}"
        anki_matches = re.findall(anki_cloze_re, original)
        
        # Check for overlapping clozes
        oc_matches = re.findall(self.creg, original)
        
        # Error if both types are present
        if anki_matches and oc_matches:
            self.showTT("Error",
                        "Cannot mix regular clozes {{c1::}} with overlapping clozes.<br>"
                        "Please use only one type per note.")
            return False, None
        
        if anki_matches:
            # Regular cloze mode - just copy Original to Full field
            # The Text1-20 fields are not used in this mode
            self.handleRegularCloze(original)
            if not self.silent:
                self.showTT("Info", "Regular cloze mode - using Full field", period=1000)
            return True, len(anki_matches)

        # Overlapping cloze mode - original behavior
        if oc_matches:
            # Check if there's only one unique cloze number
            unique_cloze_nums = set(m[0] for m in oc_matches)
            if len(unique_cloze_nums) == 1:
                # Single overlapping cloze - convert to regular cloze in Text1
                self.handleSingleOverlappingCloze(original, oc_matches)
                if not self.silent:
                    self.showTT("Info", "Single cloze mode - using Text1 field", period=1000)
                return True, 1

            custom = True
            formstr = re.sub(self.creg, "{{\\1}}", original)
            items, keys = self.getClozeItems(oc_matches)
        else:
            custom = False
            formstr = None
            items, keys = self.getLineItems(original)

        if not items:
            self.showTT("Warning",
                        "Could not find any items to cloze.<br>Please check your input.",)
            return False, None
        if len(items) < 1:
            self.showTT("Reminder",
                        "Please enter at least 1 item to cloze.")
            return False, None

        setopts = parseNoteSettings(self.note[self.flds["st"]])
        maxfields = self.getMaxFields(self.model, self.flds["tx"])
        if not maxfields:
            return False, None

        gen = ClozeGenerator(setopts, maxfields)
        fields, full, total = gen.generate(items, formstr, keys)

        if fields is None:
            self.showTT("Warning", "This would generate <b>%d</b> overlapping clozes,<br>"
                        "The note type can only handle a maximum of <b>%d</b> with<br>"
                        "the current number of %s fields" % (total, maxfields, self.flds["tx"]))
            return False, None
        if fields == 0:
            self.showTT("Warning", "This would generate no overlapping clozes at all<br>"
                        "Please check your cloze-generation settings")
            return False, None

        self.updateNote(fields, full, setopts, custom)

        if not self.silent:
            self.showTT("Info", "Generated %d overlapping clozes" %
                        total, period=1000)
        return True, total

    def handleRegularCloze(self, original):
        """Handle regular Anki clozes - content stays in Original field"""
        note = self.note

        # Clear all Text1-20 fields so they don't interfere
        maxfields = self.getMaxFields(self.model, self.flds["tx"])
        if maxfields:
            for idx in range(maxfields):
                name = self.flds["tx"] + str(idx + 1)
                if name in note:
                    note[name] = ""

        # Clear Full field so it doesn't show duplicate content
        note[self.flds["fl"]] = ""

        # Clear settings since they don't apply to regular clozes
        note[self.flds["st"]] = ""

        # Original field already contains the cloze content - leave it as is
        # The template will render {{cloze:Original}} to display the clozes

        if note.id != 0:
            note.flush()

    def handleSingleOverlappingCloze(self, original, oc_matches):
        """Handle single overlapping cloze - convert to regular cloze in Text1 only.

        When there's only one overlapping cloze (e.g., {{o1::text}}), we don't need
        the full overlapping cloze machinery. Instead, just convert it to {{c1::text}}
        and put it in Text1.
        """
        note = self.note

        # Convert {{o1::text}} to {{c1::text}} in the original content
        converted = re.sub(self.creg, r"{{c\1::\2}}", original)

        # Put converted content in Text1
        text1_field = self.flds["tx"] + "1"
        if text1_field in note:
            note[text1_field] = converted

        # Clear Text2-20 fields
        maxfields = self.getMaxFields(self.model, self.flds["tx"])
        if maxfields:
            for idx in range(1, maxfields):  # Start from 1 (Text2) since Text1 is used
                name = self.flds["tx"] + str(idx + 1)
                if name in note:
                    note[name] = ""

        # Clear Full field (not needed for single cloze)
        note[self.flds["fl"]] = ""

        # Set a sensible Settings field: "1,1,0 | n,n,n,y"
        # (before=1, prompt=1, after=0, no special options, no full cloze)
        note[self.flds["st"]] = "single"

        if note.id != 0:
            note.flush()

    def getClozeItems(self, matches):
        """Returns a list of items that were clozed by the user"""
        matches.sort(key=lambda x: int(x[0]))
        groups = groupby(matches, itemgetter(0))
        items = []
        keys = []
        for key, data in groups:
            phrases = tuple(item[1] for item in data)
            keys.append(key)
            if len(phrases) == 1:
                items.append(phrases[0])
            else:
                items.append(phrases)
        return items, keys

    def getLineItems(self, html):
        """Detects HTML list markups and returns a list of plaintext lines"""
        if ANKI20:  # do not supply parser to avoid AttributeError
            soup = BeautifulSoup(html)
        else:
            soup = BeautifulSoup(html, "html.parser")
        text = soup.getText("\n")  # will need to be updated for bs4
        if soup.findAll("ol"):
            self.markup = "ol"
        elif soup.findAll("ul"):
            self.markup = "ul"
        else:
            self.markup = "div"
        # remove empty lines:
        lines = re.sub(r"^(&nbsp;)+$", "", text,
                       flags=re.MULTILINE).splitlines()
        items = [line for line in lines if line.strip() != '']
        return items, None

    @staticmethod
    def getMaxFields(model, prefix):
        """Determine number of text fields available for cloze sequences"""
        m = model
        fields = [f['name'] for f in m['flds'] if f['name'].startswith(prefix)]
        last = 0
        for f in fields:
            # check for non-continuous cloze fields
            if not f.startswith(prefix):
                continue
            try:
                cur = int(f.replace(prefix, ""))
            except ValueError:
                break
            if cur != last + 1:
                break
            last = cur
        expected = len(fields)
        actual = last
        if not expected or not actual:
            warnUser("Note Type", "Cloze fields not configured properly")
            return False
        elif expected != actual:
            warnUser("Note Type", "Cloze fields are not continuous."
                     "<br>(breaking off after %i fields)" % actual)
            return False
        return actual

    def updateNote(self, fields, full, setopts, custom):
        """Write changes to note"""
        note = self.note
        options = setopts[1]
        for idx, field in enumerate(fields):
            name = self.flds["tx"] + str(idx+1)
            if name not in note:
                print("Missing field. Should never happen.")
                continue
            note[name] = field if custom else self.processField(field)

        if options[3]:  # no full clozes
            full = ""
        else:
            full = full if custom else self.processField(full)
        note[self.flds["fl"]] = full
        note[self.flds["st"]] = createNoteSettings(setopts)
        if note.id != 0:
            note.flush()

    def processField(self, field):
        """Convert field contents back to HTML based on previous markup"""
        markup = self.markup
        if markup == "div":
            tag_start, tag_end = "", ""
            tag_items = "<div>{0}</div>"
        else:
            tag_start = '<{0}>'.format(markup)
            tag_end = '</{0}>'.format(markup)
            tag_items = "<li>{0}</li>"
        lines = "".join(tag_items.format(line) for line in field)
        return tag_start + lines + tag_end
