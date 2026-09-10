"""Tests for the Generation III save parser.

These build synthetic saves in memory rather than depending on a real save
file, so the checksum algorithm and the section-size table are exercised
independently of any one player's data.
"""

import struct
import sys
import unittest
from os.path import dirname, abspath

sys.path.insert(0, dirname(dirname(abspath(__file__))))

from frcoins import gen3


def encode_string(text, length):
    """Encode ASCII into the Generation III character table, 0xFF padded."""
    reverse = {}
    for byte, char in gen3._CHARSET.items():
        reverse.setdefault(char, byte)
    out = bytearray(0xFF for _ in range(length))
    for i, char in enumerate(text[:length]):
        out[i] = reverse[char]
    return bytes(out)


def build_save(money=12345, coins=678, key=0xDEADBEEF, name="RED",
               slot_a_index=10, slot_b_index=11, rotation=0):
    """Produce a well-formed 128 KiB save with known contents in both slots."""
    blocks = {i: bytearray(gen3.SECTION_DATA_SIZE) for i in range(gen3.SECTIONS_PER_SLOT)}

    sb2 = blocks[gen3.SAVEBLOCK2_SECTION]
    sb2[0:8] = encode_string(name, 8)
    sb2[gen3.SB2_GENDER] = 0
    struct.pack_into("<HH", sb2, gen3.SB2_TRAINER_ID, 1234, 5678)
    struct.pack_into("<H", sb2, gen3.SB2_PLAYTIME_HOURS, 3)
    sb2[gen3.SB2_PLAYTIME_MINUTES] = 4
    sb2[gen3.SB2_PLAYTIME_SECONDS] = 5
    struct.pack_into("<I", sb2, gen3.SB2_SECURITY_KEY, key)

    # money and coins live in SaveBlock1, which starts at section 1.
    sb1_first = blocks[gen3.SAVEBLOCK1_SECTIONS[0]]
    struct.pack_into("<I", sb1_first, gen3.SB1_MONEY, money ^ key)
    struct.pack_into("<H", sb1_first, gen3.SB1_COINS, coins ^ (key & 0xFFFF))

    raw = bytearray(b"\xFF" * gen3.SAVE_FILE_SIZE)
    for base, index in ((gen3.SLOT_BASES["A"], slot_a_index),
                        (gen3.SLOT_BASES["B"], slot_b_index)):
        write_slot(raw, base, index, blocks, rotation)
    return raw


def write_slot(raw, base, save_index, blocks, rotation=0):
    """Lay 14 sections into a slot, rotating which ID lands first."""
    for position in range(gen3.SECTIONS_PER_SLOT):
        section_id = (rotation + position) % gen3.SECTIONS_PER_SLOT
        offset = base + position * gen3.SECTION_SIZE
        data = bytes(blocks[section_id])
        raw[offset:offset + gen3.SECTION_DATA_SIZE] = data
        struct.pack_into("<H", raw, offset + gen3.OFF_SECTION_ID, section_id)
        struct.pack_into("<H", raw, offset + gen3.OFF_CHECKSUM,
                         gen3.checksum(data, gen3.SECTION_DATA_SIZES[section_id]))
        struct.pack_into("<I", raw, offset + gen3.OFF_SIGNATURE, gen3.SIGNATURE)
        struct.pack_into("<I", raw, offset + gen3.OFF_SAVE_INDEX, save_index)


class ChecksumTest(unittest.TestCase):
    def test_folds_carry_into_low_word(self):
        data = struct.pack("<II", 0xFFFFFFFF, 0x00000001) + bytes(8)
        # 0xFFFFFFFF + 1 wraps to 0, so only the fold of zero remains.
        self.assertEqual(gen3.checksum(data, 16), 0)

    def test_sums_only_the_requested_length(self):
        data = bytearray(32)
        struct.pack_into("<I", data, 16, 0x1111)
        self.assertEqual(gen3.checksum(data, 16), 0)
        self.assertEqual(gen3.checksum(data, 32), 0x1111)

    def test_section_four_is_0xf08_not_0xc40(self):
        """The FRLG size for section 4; the Ruby/Sapphire 0xC40 is wrong here."""
        self.assertEqual(gen3.SECTION_DATA_SIZES[4], 0xF08)
        data = bytearray(gen3.SECTION_DATA_SIZE)
        struct.pack_into("<I", data, 0xF04, 0x99)   # last word inside the range
        self.assertEqual(gen3.checksum(data, 0xF08), 0x99)
        data = bytearray(gen3.SECTION_DATA_SIZE)
        struct.pack_into("<I", data, 0xF08, 0x99)   # first word outside it
        self.assertEqual(gen3.checksum(data, 0xF08), 0)


class ParseTest(unittest.TestCase):
    def test_reads_money_and_coins(self):
        save = gen3.Save(build_save(money=113912, coins=1372, key=0xF4A73E21))
        live = save.live_slot
        self.assertEqual(live.money, 113912)
        self.assertEqual(live.coins, 1372)
        self.assertEqual(live.security_key, 0xF4A73E21)

    def test_decodes_header_fields(self):
        live = gen3.Save(build_save(name="JOSEKUN")).live_slot
        self.assertEqual(live.player_name, "JOSEKUN")
        self.assertEqual(live.gender, "male")
        self.assertEqual(live.trainer_id, (1234, 5678))
        self.assertEqual(live.play_time, (3, 4, 5))

    def test_zero_and_maximum_values_round_trip(self):
        for money, coins in ((0, 0), (gen3.MONEY_MAX, gen3.COIN_MAX)):
            live = gen3.Save(build_save(money=money, coins=coins)).live_slot
            self.assertEqual((live.money, live.coins), (money, coins))
            self.assertTrue(live.values_plausible)

    def test_all_sections_validate(self):
        save = gen3.Save(build_save())
        for slot in save.slots.values():
            self.assertTrue(slot.is_intact, "slot %s not intact" % slot.name)
            self.assertEqual(slot.bad_checksum_ids, [])

    def test_rejects_undersized_file(self):
        with self.assertRaises(gen3.SaveError):
            gen3.Save(bytearray(0x1000))


class RotationTest(unittest.TestCase):
    """Section IDs are not stored in order; parsing must not assume they are."""

    def test_every_rotation_yields_the_same_values(self):
        for rotation in range(gen3.SECTIONS_PER_SLOT):
            save = gen3.Save(build_save(money=4242, coins=777, rotation=rotation))
            live = save.live_slot
            self.assertEqual((live.money, live.coins), (4242, 777),
                             "failed at rotation %d" % rotation)

    def test_coin_field_tracks_the_rotated_section(self):
        for rotation in (0, 5, 9):
            save = gen3.Save(build_save(rotation=rotation))
            live = save.live_slot
            section_id, within, file_offset = live.locate(gen3.SB1_COINS)
            self.assertEqual(section_id, 1)
            self.assertEqual(within, gen3.SB1_COINS)
            self.assertEqual(file_offset,
                             live.sections[1].file_offset + gen3.SB1_COINS)

    def test_money_and_coins_share_section_one(self):
        live = gen3.Save(build_save()).live_slot
        self.assertEqual(live.locate(gen3.SB1_MONEY)[0], 1)
        self.assertEqual(live.locate(gen3.SB1_COINS)[0], 1)


class SlotSelectionTest(unittest.TestCase):
    def test_picks_the_higher_save_index(self):
        save = gen3.Save(build_save(slot_a_index=22, slot_b_index=23))
        self.assertEqual(save.live_slot.name, "B")
        save = gen3.Save(build_save(slot_a_index=24, slot_b_index=23))
        self.assertEqual(save.live_slot.name, "A")

    def test_falls_back_when_the_newer_slot_is_damaged(self):
        raw = build_save(slot_a_index=22, slot_b_index=23)
        struct.pack_into("<H", raw, gen3.SLOT_BASES["B"] + gen3.OFF_CHECKSUM, 0xBAD1)
        save = gen3.Save(raw)
        self.assertFalse(save.slots["B"].is_intact)
        self.assertEqual(save.live_slot.name, "A")

    def test_detects_a_broken_signature(self):
        raw = build_save()
        struct.pack_into("<I", raw, gen3.SLOT_BASES["A"] + gen3.OFF_SIGNATURE, 0)
        save = gen3.Save(raw)
        self.assertFalse(save.slots["A"].is_intact)
        self.assertIn(0, save.slots["A"].bad_signature_ids)

    def test_no_live_slot_when_both_are_damaged(self):
        raw = build_save()
        for base in gen3.SLOT_BASES.values():
            struct.pack_into("<H", raw, base + gen3.OFF_CHECKSUM, 0xBAD1)
        self.assertIsNone(gen3.Save(raw).live_slot)

    def test_blank_slot_is_not_populated(self):
        raw = build_save()
        base = gen3.SLOT_BASES["B"]
        raw[base:base + gen3.SECTIONS_PER_SLOT * gen3.SECTION_SIZE] = \
            b"\xFF" * (gen3.SECTIONS_PER_SLOT * gen3.SECTION_SIZE)
        save = gen3.Save(raw)
        self.assertFalse(save.slots["B"].is_populated)
        self.assertEqual(save.live_slot.name, "A")


class PlausibilityTest(unittest.TestCase):
    """The gate that would catch a hack having moved these fields."""

    def test_flags_out_of_range_coins(self):
        raw = build_save(coins=0)
        live = gen3.Save(raw).live_slot
        section = live.sections[1]
        struct.pack_into("<H", raw, section.file_offset + gen3.SB1_COINS,
                         0xFFFF ^ (live.security_key & 0xFFFF))
        live = gen3.Save(raw).slots[live.name]
        self.assertEqual(live.coins, 0xFFFF)
        self.assertFalse(live.values_plausible)

    def test_flags_out_of_range_money(self):
        raw = build_save(money=0)
        live = gen3.Save(raw).live_slot
        section = live.sections[1]
        struct.pack_into("<I", raw, section.file_offset + gen3.SB1_MONEY,
                         0xFFFFFFFF ^ live.security_key)
        live = gen3.Save(raw).slots[live.name]
        self.assertFalse(live.values_plausible)


class StringTest(unittest.TestCase):
    def test_stops_at_the_terminator(self):
        self.assertEqual(gen3.decode_string(b"\xC4\xC9\xCD\xBF\xFF\xC5"), "JOSE")

    def test_unmapped_bytes_become_question_marks(self):
        self.assertEqual(gen3.decode_string(b"\xC4\x01\xFF"), "J?")

    def test_empty_name(self):
        self.assertEqual(gen3.decode_string(b"\xFF" * 8), "")


if __name__ == "__main__":
    unittest.main()
