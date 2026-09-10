"""Tests for building and applying save edits."""

import os
import shutil
import struct
import sys
import tempfile
import unittest
from datetime import datetime
from os.path import dirname, abspath, exists

sys.path.insert(0, dirname(dirname(abspath(__file__))))
sys.path.insert(0, dirname(abspath(__file__)))

from frcoins import gen3, store, writer
from test_gen3 import build_save


class SetCoinsTest(unittest.TestCase):
    def test_sets_the_requested_value(self):
        save = gen3.Save(build_save(coins=1372, money=113912))
        result = gen3.Save(writer.set_coins(save, 9999))
        self.assertEqual(result.live_slot.coins, 9999)

    def test_leaves_money_alone(self):
        save = gen3.Save(build_save(coins=1372, money=113912))
        result = gen3.Save(writer.set_coins(save, 9999))
        self.assertEqual(result.live_slot.money, 113912)

    def test_changes_exactly_four_bytes_in_two_runs(self):
        save = gen3.Save(build_save(coins=1372))
        runs = writer.diff_runs(save.raw, writer.set_coins(save, 9999))
        self.assertEqual(len(runs), 2)
        self.assertEqual(sum(len(old) for _, old, _ in runs), 4)

    def test_touches_only_the_coin_field_and_its_checksum(self):
        save = gen3.Save(build_save(coins=1372))
        slot = save.live_slot
        section_id, _, coin_offset = slot.locate(gen3.SB1_COINS)
        checksum_offset = slot.sections[section_id].file_offset + gen3.OFF_CHECKSUM
        offsets = [o for o, _, _ in writer.diff_runs(save.raw,
                                                     writer.set_coins(save, 9999))]
        self.assertEqual(sorted(offsets), sorted([coin_offset, checksum_offset]))

    def test_leaves_the_other_slot_untouched(self):
        save = gen3.Save(build_save(coins=1372, slot_a_index=22, slot_b_index=23))
        new = writer.set_coins(save, 9999)
        base = gen3.SLOT_BASES["A"]
        span = gen3.SECTIONS_PER_SLOT * gen3.SECTION_SIZE
        self.assertEqual(save.raw[base:base + span], new[base:base + span])

    def test_all_checksums_still_validate(self):
        save = gen3.Save(build_save(coins=1372))
        result = gen3.Save(writer.set_coins(save, 9999))
        for slot in result.slots.values():
            self.assertTrue(slot.is_intact)

    def test_round_trip_is_byte_identical(self):
        original = build_save(coins=1372)
        save = gen3.Save(original)
        there = writer.set_coins(save, 9999)
        back = writer.set_coins(gen3.Save(there), 1372)
        self.assertEqual(bytes(original), back)

    def test_works_at_both_ends_of_the_range(self):
        save = gen3.Save(build_save(coins=500))
        for value in (0, gen3.COIN_MAX):
            self.assertEqual(gen3.Save(writer.set_coins(save, value)).live_slot.coins,
                             value)

    def test_survives_every_section_rotation(self):
        for rotation in range(gen3.SECTIONS_PER_SLOT):
            save = gen3.Save(build_save(coins=10, rotation=rotation))
            result = gen3.Save(writer.set_coins(save, 9999))
            self.assertEqual(result.live_slot.coins, 9999,
                             "failed at rotation %d" % rotation)
            self.assertTrue(result.live_slot.is_intact)

    def test_edits_slot_a_when_it_is_the_newer_one(self):
        save = gen3.Save(build_save(coins=7, slot_a_index=99, slot_b_index=2))
        new = writer.set_coins(save, 9999)
        self.assertEqual(gen3.Save(new).slots["A"].coins, 9999)
        base = gen3.SLOT_BASES["B"]
        span = gen3.SECTIONS_PER_SLOT * gen3.SECTION_SIZE
        self.assertEqual(save.raw[base:base + span], new[base:base + span])


class RefusalTest(unittest.TestCase):
    def test_rejects_values_above_the_cap(self):
        save = gen3.Save(build_save())
        with self.assertRaises(writer.WriteError):
            writer.set_coins(save, gen3.COIN_MAX + 1)

    def test_rejects_negative_values(self):
        save = gen3.Save(build_save())
        with self.assertRaises(writer.WriteError):
            writer.set_coins(save, -1)

    def test_rejects_non_integers(self):
        save = gen3.Save(build_save())
        for value in ("9999", 99.5, True, None):
            with self.assertRaises(writer.WriteError):
                writer.set_coins(save, value)

    def test_refuses_when_no_slot_is_intact(self):
        raw = build_save()
        for base in gen3.SLOT_BASES.values():
            struct.pack_into("<H", raw, base + gen3.OFF_CHECKSUM, 0xBAD1)
        with self.assertRaises(writer.WriteError):
            writer.set_coins(gen3.Save(raw), 9999)

    def test_refuses_when_decoded_values_are_implausible(self):
        raw = build_save(money=0)
        # Pin the slot by name: breaking its checksum below would otherwise make
        # live_slot fall back to the other slot mid-setup.
        name = gen3.Save(raw).live_slot.name
        slot = gen3.Save(raw).slots[name]
        start = slot.sections[1].file_offset
        struct.pack_into("<I", raw, start + gen3.SB1_MONEY,
                         0xFFFFFFFF ^ slot.security_key)
        # Re-checksum so the slot stays "intact" and only plausibility can catch it.
        data = bytes(raw[start:start + gen3.SECTION_DATA_SIZE])
        struct.pack_into("<H", raw, start + gen3.OFF_CHECKSUM,
                         gen3.checksum(data, gen3.SECTION_DATA_SIZES[1]))
        save = gen3.Save(raw)
        self.assertEqual(save.live_slot.name, name)
        self.assertEqual(save.live_slot.money, 0xFFFFFFFF)
        with self.assertRaises(writer.WriteError) as caught:
            writer.set_coins(save, 9999)
        self.assertIn("offsets are wrong", str(caught.exception))


class VerifyTest(unittest.TestCase):
    def test_accepts_a_good_edit(self):
        save = gen3.Save(build_save(coins=1372, money=113912))
        new = writer.set_coins(save, 9999)
        writer.verify(new, save.live_slot.name, 9999, 113912)

    def test_catches_a_wrong_coin_value(self):
        save = gen3.Save(build_save(coins=1372, money=113912))
        new = writer.set_coins(save, 9999)
        with self.assertRaises(writer.WriteError):
            writer.verify(new, save.live_slot.name, 1234, 113912)

    def test_catches_money_drift(self):
        save = gen3.Save(build_save(coins=1372, money=113912))
        new = writer.set_coins(save, 9999)
        with self.assertRaises(writer.WriteError):
            writer.verify(new, save.live_slot.name, 9999, 999)

    def test_catches_a_corrupted_result(self):
        save = gen3.Save(build_save())
        new = bytearray(writer.set_coins(save, 9999))
        struct.pack_into("<H", new, save.live_slot.sections[2].file_offset
                         + gen3.OFF_CHECKSUM, 0xBAD1)
        with self.assertRaises(writer.WriteError):
            writer.verify(bytes(new), save.live_slot.name, 9999,
                          save.live_slot.money)

    def test_catches_damage_to_the_other_slot(self):
        save = gen3.Save(build_save(slot_a_index=22, slot_b_index=23))
        new = bytearray(writer.set_coins(save, 9999))
        struct.pack_into("<H", new, gen3.SLOT_BASES["A"] + gen3.OFF_CHECKSUM, 0xBAD1)
        with self.assertRaises(writer.WriteError) as caught:
            writer.verify(bytes(new), "B", 9999, save.live_slot.money)
        self.assertIn("slot A was damaged", str(caught.exception))


class DiffRunsTest(unittest.TestCase):
    def test_groups_contiguous_bytes(self):
        runs = writer.diff_runs(b"\x00\x00\x00\x00", b"\x00\x01\x02\x00")
        self.assertEqual(runs, [(1, b"\x00\x00", b"\x01\x02")])

    def test_separates_distant_changes(self):
        runs = writer.diff_runs(b"\x00" * 6, b"\x01\x00\x00\x00\x00\x01")
        self.assertEqual([offset for offset, _, _ in runs], [0, 5])

    def test_identical_input_yields_nothing(self):
        self.assertEqual(writer.diff_runs(b"abc", b"abc"), [])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "test.srm")
        with open(self.path, "wb") as handle:
            handle.write(b"original")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_backup_copies_the_file(self):
        backup = store.make_backup(self.path)
        self.assertEqual(open(backup, "rb").read(), b"original")

    def test_same_second_backups_do_not_collide(self):
        when = datetime(2026, 9, 10, 2, 52, 4)
        first = store.make_backup(self.path, when)
        second = store.make_backup(self.path, when)
        self.assertNotEqual(first, second)
        self.assertTrue(exists(first) and exists(second))

    def test_backup_never_overwrites(self):
        when = datetime(2026, 9, 10, 2, 52, 4)
        first = store.make_backup(self.path, when)
        with open(self.path, "wb") as handle:
            handle.write(b"changed!")
        store.make_backup(self.path, when)
        self.assertEqual(open(first, "rb").read(), b"original")

    def test_atomic_write_replaces_contents(self):
        store.write_atomic(self.path, b"replaced")
        self.assertEqual(open(self.path, "rb").read(), b"replaced")

    def test_atomic_write_leaves_no_temp_files(self):
        store.write_atomic(self.path, b"replaced")
        self.assertEqual(sorted(os.listdir(self.dir)), ["test.srm"])


if __name__ == "__main__":
    unittest.main()
