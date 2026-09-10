"""Building modified saves.

Nothing here performs I/O.  Every function takes bytes and returns bytes, so a
write can be fully assembled and verified in memory before the real file is
touched -- a rejected edit never reaches the disk at all.
"""

import struct

from . import gen3


class WriteError(Exception):
    """The requested edit was refused."""


def encode_coins(value, security_key):
    return value ^ (security_key & 0xFFFF)


def set_coins(save, value):
    """Return new save bytes with the live slot's coin counter set to `value`.

    Only the coin field and its section checksum change; the other slot is left
    untouched so it remains the game's own fallback.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise WriteError("coin value must be an integer")
    if value < 0 or value > gen3.COIN_MAX:
        raise WriteError("coin value must be between 0 and %d; got %s"
                         % (gen3.COIN_MAX, value))

    slot = save.live_slot
    if slot is None:
        raise WriteError(
            "neither save slot is intact, so there is no safe slot to edit")
    if not slot.values_plausible:
        raise WriteError(
            "slot %s decodes to values outside the game's limits "
            "(money=%d, coins=%d), so the field offsets are wrong for this ROM"
            % (slot.name, slot.money, slot.coins))

    new = bytearray(save.raw)
    section_id, _, file_offset = slot.locate(gen3.SB1_COINS)
    struct.pack_into("<H", new, file_offset, encode_coins(value, slot.security_key))

    # The checksum must be taken over the section as it now stands.
    section = slot.sections[section_id]
    start = section.file_offset
    data = bytes(new[start:start + gen3.SECTION_DATA_SIZE])
    struct.pack_into("<H", new, start + gen3.OFF_CHECKSUM,
                     gen3.checksum(data, gen3.SECTION_DATA_SIZES[section_id]))
    return bytes(new)


def verify(new_raw, slot_name, expected_coins, expected_money):
    """Re-parse a candidate save and confirm it is exactly what was intended.

    Raises WriteError describing the first problem found.  Callers run this
    before writing, so a failure costs nothing.
    """
    try:
        check = gen3.Save(new_raw)
    except gen3.SaveError as exc:
        raise WriteError("result is not a parseable save: %s" % exc)

    slot = check.slots.get(slot_name)
    if slot is None:
        raise WriteError("slot %s vanished from the result" % slot_name)
    if not slot.is_intact:
        raise WriteError(
            "slot %s is not intact after the edit (bad checksums: %s)"
            % (slot_name, slot.bad_checksum_ids or "none"))
    if check.live_slot is None or check.live_slot.name != slot_name:
        raise WriteError("slot %s would no longer be the slot the game loads"
                         % slot_name)
    if slot.coins != expected_coins:
        raise WriteError("expected %d coins in the result, found %d"
                         % (expected_coins, slot.coins))
    if slot.money != expected_money:
        raise WriteError("money changed unexpectedly: %d -> %d"
                         % (expected_money, slot.money))
    if not slot.values_plausible:
        raise WriteError("result decodes to implausible values")

    for other in check.slots.values():
        if other.name != slot_name and other.is_populated and not other.is_intact:
            raise WriteError("slot %s was damaged by the edit" % other.name)
    return check


def diff_runs(old, new):
    """Group differing bytes into contiguous (offset, old_bytes, new_bytes) runs."""
    runs = []
    length = max(len(old), len(new))
    index = 0
    while index < length:
        if old[index:index + 1] == new[index:index + 1]:
            index += 1
            continue
        start = index
        while index < length and old[index:index + 1] != new[index:index + 1]:
            index += 1
        runs.append((start, bytes(old[start:index]), bytes(new[start:index])))
    return runs
