"""Generation III save file parsing (read-only).

Covers the FireRed/LeafGreen container used by FRLG+ 1.5.1.  Every constant in
this module was verified byte-for-byte against a real save rather than copied
from a wiki -- see docs/SAVE-FORMAT.md for the evidence and the two traps this
module exists to encapsulate:

  * Section IDs rotate.  Sections must be located by the ID stored at +0xFF4,
    never by their position in the file.
  * Section 4's checksummed length is 0xF08 in FRLG.  The widely copied 0xC40
    is the Ruby/Sapphire figure and does not validate here.
"""

import struct

SAVE_FILE_SIZE = 0x20000
SIGNATURE = 0x08012025

SECTION_SIZE = 0x1000
SECTION_DATA_SIZE = 0xF80
SECTIONS_PER_SLOT = 14

OFF_SECTION_ID = 0xFF4
OFF_CHECKSUM = 0xFF6
OFF_SIGNATURE = 0xFF8
OFF_SAVE_INDEX = 0xFFC

SLOT_BASES = {"A": 0x00000, "B": 0x0E000}

# Bytes of each section that participate in its checksum, by section ID (FRLG).
SECTION_DATA_SIZES = {
    0: 0xF2C,
    1: 0xF80, 2: 0xF80, 3: 0xF80,
    4: 0xF08,
    5: 0xF80, 6: 0xF80, 7: 0xF80, 8: 0xF80,
    9: 0xF80, 10: 0xF80, 11: 0xF80, 12: 0xF80,
    13: 0x7D0,
}

# SaveBlock1 is sections 1..4 concatenated in ID order; SaveBlock2 is section 0.
SAVEBLOCK1_SECTIONS = (1, 2, 3, 4)
SAVEBLOCK2_SECTION = 0

# Offsets within SaveBlock2.
SB2_PLAYER_NAME = 0x00
SB2_PLAYER_NAME_LEN = 8
SB2_GENDER = 0x08
SB2_TRAINER_ID = 0x0A
SB2_PLAYTIME_HOURS = 0x0E
SB2_PLAYTIME_MINUTES = 0x10
SB2_PLAYTIME_SECONDS = 0x11
SB2_SECURITY_KEY = 0x0F20

# Offsets within SaveBlock1.  Both are XOR-obfuscated with the security key.
SB1_MONEY = 0x0290
SB1_COINS = 0x0294

COIN_MAX = 9999
MONEY_MAX = 999999


class SaveError(Exception):
    """The file could not be parsed as a Generation III save."""


def checksum(data, size):
    """Fold a 32-bit sum of the first `size` bytes into the stored 16-bit value."""
    total = 0
    for offset in range(0, size, 4):
        total = (total + struct.unpack_from("<I", data, offset)[0]) & 0xFFFFFFFF
    return ((total >> 16) + (total & 0xFFFF)) & 0xFFFF


# Generation III western character table.  Only the printable range used by
# player names is mapped; anything else decodes to '?'.
_CHARSET = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB8: ",",
            0xBA: "/", 0xB5: "M", 0xB6: "F"}
for _i in range(10):
    _CHARSET[0xA1 + _i] = chr(ord("0") + _i)
for _i in range(26):
    _CHARSET[0xBB + _i] = chr(ord("A") + _i)
    _CHARSET[0xD5 + _i] = chr(ord("a") + _i)


def decode_string(raw):
    """Decode a Generation III text field up to its 0xFF terminator."""
    out = []
    for byte in raw:
        if byte == 0xFF:
            break
        out.append(_CHARSET.get(byte, "?"))
    return "".join(out)


class Section:
    """One 0x1000 block: 0xF80 bytes of payload followed by a 12-byte footer."""

    def __init__(self, raw, file_offset):
        self.file_offset = file_offset
        self.data = raw[file_offset:file_offset + SECTION_DATA_SIZE]
        footer = file_offset
        self.section_id = struct.unpack_from("<H", raw, footer + OFF_SECTION_ID)[0]
        self.stored_checksum = struct.unpack_from("<H", raw, footer + OFF_CHECKSUM)[0]
        self.signature = struct.unpack_from("<I", raw, footer + OFF_SIGNATURE)[0]
        self.save_index = struct.unpack_from("<I", raw, footer + OFF_SAVE_INDEX)[0]

    @property
    def has_signature(self):
        return self.signature == SIGNATURE

    @property
    def checksummed_size(self):
        return SECTION_DATA_SIZES.get(self.section_id)

    @property
    def computed_checksum(self):
        size = self.checksummed_size
        if size is None:
            return None
        return checksum(self.data, size)

    @property
    def checksum_ok(self):
        return self.computed_checksum == self.stored_checksum


class Slot:
    """One of the two 14-section save slots.  The game keeps the newer of them."""

    def __init__(self, name, raw, base):
        self.name = name
        self.base = base
        self.sections = {}
        self.duplicate_ids = []
        for index in range(SECTIONS_PER_SLOT):
            section = Section(raw, base + index * SECTION_SIZE)
            if section.section_id in self.sections:
                self.duplicate_ids.append(section.section_id)
            self.sections[section.section_id] = section

    @property
    def is_populated(self):
        """True if this slot has ever been written (a fresh file has one blank slot)."""
        return any(s.has_signature for s in self.sections.values())

    @property
    def missing_ids(self):
        return [i for i in range(SECTIONS_PER_SLOT) if i not in self.sections]

    @property
    def bad_signature_ids(self):
        return sorted(i for i, s in self.sections.items() if not s.has_signature)

    @property
    def bad_checksum_ids(self):
        return sorted(i for i, s in self.sections.items() if not s.checksum_ok)

    @property
    def is_intact(self):
        return not (self.missing_ids or self.duplicate_ids
                    or self.bad_signature_ids or self.bad_checksum_ids)

    @property
    def save_index(self):
        if 0 not in self.sections:
            return None
        return self.sections[0].save_index

    @property
    def saveblock2(self):
        return self.sections[SAVEBLOCK2_SECTION].data

    @property
    def saveblock1(self):
        return b"".join(self.sections[i].data for i in SAVEBLOCK1_SECTIONS)

    def locate(self, sb1_offset):
        """Map a SaveBlock1 offset to (section_id, offset_in_section, file_offset)."""
        section_id = SAVEBLOCK1_SECTIONS[sb1_offset // SECTION_DATA_SIZE]
        within = sb1_offset % SECTION_DATA_SIZE
        return section_id, within, self.sections[section_id].file_offset + within

    @property
    def security_key(self):
        return struct.unpack_from("<I", self.saveblock2, SB2_SECURITY_KEY)[0]

    @property
    def money(self):
        raw = struct.unpack_from("<I", self.saveblock1, SB1_MONEY)[0]
        return raw ^ self.security_key

    @property
    def coins(self):
        raw = struct.unpack_from("<H", self.saveblock1, SB1_COINS)[0]
        return raw ^ (self.security_key & 0xFFFF)

    @property
    def player_name(self):
        return decode_string(self.saveblock2[SB2_PLAYER_NAME:
                                             SB2_PLAYER_NAME + SB2_PLAYER_NAME_LEN])

    @property
    def gender(self):
        return "female" if self.saveblock2[SB2_GENDER] else "male"

    @property
    def trainer_id(self):
        public, secret = struct.unpack_from("<HH", self.saveblock2, SB2_TRAINER_ID)
        return public, secret

    @property
    def play_time(self):
        hours = struct.unpack_from("<H", self.saveblock2, SB2_PLAYTIME_HOURS)[0]
        return hours, self.saveblock2[SB2_PLAYTIME_MINUTES], \
            self.saveblock2[SB2_PLAYTIME_SECONDS]

    @property
    def values_plausible(self):
        """Sanity gate: decoded values must fall inside the game's own limits.

        If the hack had moved these fields, or the key were read from the wrong
        place, this is what would catch it.
        """
        return self.coins <= COIN_MAX and self.money <= MONEY_MAX


class Save:
    """A 128 KiB Generation III battery file (RetroArch writes these as .srm)."""

    def __init__(self, raw, path=None):
        if len(raw) < SLOT_BASES["B"] + SECTIONS_PER_SLOT * SECTION_SIZE:
            raise SaveError(
                "file is %d bytes; a Generation III save needs at least %d"
                % (len(raw), SLOT_BASES["B"] + SECTIONS_PER_SLOT * SECTION_SIZE))
        self.raw = raw
        self.path = path
        self.slots = {name: Slot(name, raw, base) for name, base in SLOT_BASES.items()}

    @classmethod
    def load(cls, path):
        with open(path, "rb") as handle:
            return cls(handle.read(), path=path)

    @property
    def populated_slots(self):
        return [s for s in self.slots.values() if s.is_populated]

    @property
    def live_slot(self):
        """The slot the game will load: highest save index among intact slots.

        The game falls back to the other slot when the newer one fails to
        validate, so an intact slot always outranks a damaged newer one.
        """
        usable = [s for s in self.populated_slots if s.is_intact]
        if not usable:
            return None
        return max(usable, key=lambda s: s.save_index)
