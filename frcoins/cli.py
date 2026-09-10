"""Command line entry point.

M1 is deliberately read-only: nothing in this package opens a file for writing.
"""

import argparse
import json
import os
import shlex
import sys

from . import gen3, guard, locate, store, writer

PROG = "frcoins"


def _num(value):
    return "{:,}".format(value)


def _slot_row(slot):
    if not slot.is_populated:
        return [slot.name, "-", "empty", "", "", "", ""]

    total = gen3.SECTIONS_PER_SLOT
    present = total - len(slot.missing_ids)
    bad = len(slot.bad_checksum_ids)
    checks = "%d/%d ok" % (total - bad, total) if not bad else "%d/%d BAD" % (bad, total)

    index = str(slot.save_index) if slot.save_index is not None else "?"
    if slot.is_intact:
        return [slot.name, index, "%d/%d" % (present, total), checks,
                slot.player_name, _num(slot.money), _num(slot.coins)]
    # Decoding money/coins from a damaged slot would print noise, so don't.
    return [slot.name, index, "%d/%d" % (present, total), checks, "", "", ""]


def _table(rows, headers, aligns):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells):
        out = []
        for i, cell in enumerate(cells):
            out.append(cell.rjust(widths[i]) if aligns[i] == "r"
                       else cell.ljust(widths[i]))
        return "  ".join(out).rstrip()

    yield line(headers)
    yield "  ".join("-" * w for w in widths)
    for row in rows:
        yield line(row)


def _report(save, show_sections):
    print("Save  %s" % save.path)
    print("      %s bytes" % _num(len(save.raw)))
    if len(save.raw) != gen3.SAVE_FILE_SIZE:
        print("      note: expected %s bytes for a Generation III save"
              % _num(gen3.SAVE_FILE_SIZE))
    print()

    live = save.live_slot
    rows = []
    for name in sorted(save.slots):
        slot = save.slots[name]
        row = _slot_row(slot)
        row[0] = "%s <-" % slot.name if live is slot else slot.name
        rows.append(row)

    headers = ["Slot", "Index", "Sections", "Checksums", "Player", "Money", "Coins"]
    aligns = ["l", "r", "r", "r", "l", "r", "r"]
    for line in _table(rows, headers, aligns):
        print(line)
    print()

    for slot in save.populated_slots:
        if slot.duplicate_ids:
            print("WARNING  slot %s repeats section ID(s) %s"
                  % (slot.name, ", ".join(str(i) for i in sorted(set(slot.duplicate_ids)))))
        if slot.missing_ids:
            print("WARNING  slot %s is missing section ID(s) %s"
                  % (slot.name, ", ".join(str(i) for i in slot.missing_ids)))
        if slot.bad_checksum_ids:
            print("WARNING  slot %s has bad checksums in section(s) %s"
                  % (slot.name, ", ".join(str(i) for i in slot.bad_checksum_ids)))

    if live is None:
        print("ERROR    neither slot is intact; the game would not load this file.")
        return 1

    section_id, within, file_offset = live.locate(gen3.SB1_COINS)
    raw_coins = live.coins ^ (live.security_key & 0xFFFF)
    hours, minutes, seconds = live.play_time
    public, secret = live.trainer_id

    print("Live slot %s  (save index %d - this is the one the game loads)"
          % (live.name, live.save_index))
    print()
    print("  Player        %s (%s)" % (live.player_name, live.gender))
    print("  Trainer ID    %d   secret %d" % (public, secret))
    print("  Play time     %d:%02d:%02d" % (hours, minutes, seconds))
    print("  Security key  0x%08X" % live.security_key)
    print("  Money         %s / %s" % (_num(live.money), _num(gen3.MONEY_MAX)))
    headroom = gen3.COIN_MAX - live.coins
    suffix = "  (%s below the cap)" % _num(headroom) if headroom > 0 else "  (at the cap)"
    print("  Coins         %s / %s%s" % (_num(live.coins), _num(gen3.COIN_MAX), suffix))
    print()
    print("  Coin field    SaveBlock1+0x%04X -> section %d, file offset 0x%05X (raw 0x%04X)"
          % (gen3.SB1_COINS, section_id, file_offset, raw_coins))

    if live.values_plausible:
        print("  Sanity check  decoded values are within the game's own limits: OK")
    else:
        print("  Sanity check  FAILED - decoded values exceed the game's limits.")
        print("                The field offsets or the security key are wrong for")
        print("                this ROM. Do not write to this file.")
        return 1

    if show_sections:
        print()
        print("Sections")
        srows = []
        for name in sorted(save.slots):
            slot = save.slots[name]
            for _, section in sorted(slot.sections.items()):
                computed = section.computed_checksum
                srows.append([
                    slot.name,
                    str(section.section_id),
                    "0x%05X" % section.file_offset,
                    "0x%04X" % (section.checksummed_size or 0),
                    "0x%04X" % section.stored_checksum,
                    "0x%04X" % computed if computed is not None else "?",
                    "ok" if section.checksum_ok else "BAD",
                    "ok" if section.has_signature else "BAD",
                ])
        headers = ["Slot", "ID", "Offset", "Size", "Stored", "Computed", "Cksum", "Sig"]
        for line in _table(srows, headers, ["l", "r", "r", "r", "r", "r", "l", "l"]):
            print("  " + line)

    return 0


def _as_json(save):
    live = save.live_slot
    payload = {
        "path": save.path,
        "size": len(save.raw),
        "live_slot": live.name if live else None,
        "slots": {},
    }
    for name, slot in save.slots.items():
        entry = {
            "populated": slot.is_populated,
            "intact": slot.is_intact,
            "save_index": slot.save_index,
            "missing_section_ids": slot.missing_ids,
            "duplicate_section_ids": sorted(set(slot.duplicate_ids)),
            "bad_checksum_section_ids": slot.bad_checksum_ids,
            "bad_signature_section_ids": slot.bad_signature_ids,
        }
        if slot.is_intact:
            section_id, within, file_offset = slot.locate(gen3.SB1_COINS)
            entry.update({
                "player_name": slot.player_name,
                "gender": slot.gender,
                "trainer_id": slot.trainer_id[0],
                "secret_id": slot.trainer_id[1],
                "play_time": "%d:%02d:%02d" % slot.play_time,
                "security_key": slot.security_key,
                "money": slot.money,
                "coins": slot.coins,
                "coin_file_offset": file_offset,
                "coin_section_id": section_id,
                "values_plausible": slot.values_plausible,
            })
        payload["slots"][name] = entry
    return payload


def _hex_bytes(raw):
    return " ".join("%02X" % b for b in raw)


def _label_runs(slot, runs):
    """Name each changed byte run, and flag anything we did not intend to touch."""
    section_id, _, coin_offset = slot.locate(gen3.SB1_COINS)
    checksum_offset = slot.sections[section_id].file_offset + gen3.OFF_CHECKSUM
    expected = {
        coin_offset: ("coin field (SaveBlock1+0x%04X, section %d)"
                      % (gen3.SB1_COINS, section_id), 2),
        checksum_offset: ("section %d checksum" % section_id, 2),
    }
    labelled, unexpected = [], []
    for offset, old, new in runs:
        label, size = expected.get(offset, (None, None))
        if label is None or len(old) != size:
            unexpected.append(offset)
            label = "UNEXPECTED"
        labelled.append((offset, old, new, label))
    return labelled, unexpected


def _set_coins(save, args):
    try:
        new_raw = writer.set_coins(save, args.value)
    except writer.WriteError as exc:
        print("%s: %s" % (PROG, exc), file=sys.stderr)
        return 1

    slot = save.live_slot
    try:
        writer.verify(new_raw, slot.name, args.value, slot.money)
    except writer.WriteError as exc:
        print("%s: refusing to write - %s" % (PROG, exc), file=sys.stderr)
        return 1

    runs = writer.diff_runs(save.raw, new_raw)
    labelled, unexpected = _label_runs(slot, runs)
    if unexpected:
        print("%s: refusing to write - the edit would change bytes outside the "
              "coin field: %s" % (PROG, ", ".join("0x%05X" % o for o in unexpected)),
              file=sys.stderr)
        return 1

    print("Save  %s" % save.path)
    print("      live slot %s (save index %d), player %s"
          % (slot.name, slot.save_index, slot.player_name))
    print()

    if not runs:
        print("  Coins already %s - nothing to change." % _num(args.value))
        return 0

    print("  Coins   %s -> %s" % (_num(slot.coins), _num(args.value)))
    print("  Money   %s (unchanged)" % _num(slot.money))
    print()
    total = sum(len(old) for _, old, _, _ in labelled)
    print("  Byte changes (%d bytes):" % total)
    for offset, old, new, label in labelled:
        print("    0x%05X  %s -> %s   %s"
              % (offset, _hex_bytes(old), _hex_bytes(new), label))
    print()
    print("  Verified in memory: result reads %s coins, every section checksum "
          "valid," % _num(args.value))
    print("                      money unchanged, and slot %s untouched."
          % ("A" if slot.name == "B" else "B"))
    print()

    if not args.write:
        print("DRY RUN - nothing written. Re-run with --write to apply.")
        return 0

    sys.stdout.flush()   # keep the report above any error we are about to print
    pids = [] if args.force else guard.retroarch_pids()
    if pids:
        print("%s: RetroArch is running (pid %s)."
              % (PROG, ", ".join(str(p) for p in pids)), file=sys.stderr)
        print("         It flushes SRAM every 10 seconds and again on close, so it",
              file=sys.stderr)
        print("         would overwrite this edit. Use Close Content in RetroArch",
              file=sys.stderr)
        print("         (or quit it), then run this again.", file=sys.stderr)
        print("         Pass --force to write anyway.", file=sys.stderr)
        return 1

    try:
        backup = store.make_backup(save.path)
    except OSError as exc:
        print("%s: could not create backup, nothing written: %s" % (PROG, exc),
              file=sys.stderr)
        return 1

    try:
        store.write_atomic(save.path, new_raw)
    except OSError as exc:
        print("%s: write failed: %s" % (PROG, exc), file=sys.stderr)
        print("%s: your save is unchanged; a backup is at %s" % (PROG, backup),
              file=sys.stderr)
        return 1

    print("  Backup   %s" % backup)
    print("  Written  %s bytes" % _num(len(new_raw)))

    # Read back from disk rather than trusting what we just held in memory.
    try:
        confirmed = gen3.Save.load(save.path)
        writer.verify(confirmed.raw, slot.name, args.value, slot.money)
    except (OSError, gen3.SaveError, writer.WriteError) as exc:
        print("%s: WROTE THE FILE BUT IT DID NOT VERIFY: %s" % (PROG, exc),
              file=sys.stderr)
        print("%s: restore it with:\n  cp %s %s"
              % (PROG, shlex.quote(backup), shlex.quote(save.path)), file=sys.stderr)
        return 1

    print("  Re-read from disk: %s coins, all sections valid."
          % _num(confirmed.live_slot.coins))
    print()
    print("Load the save in RetroArch to confirm. To undo:")
    print("  cp %s %s" % (shlex.quote(backup), shlex.quote(save.path)))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Inspect a Pokemon FireRed/LeafGreen (Generation III) save file.")
    sub = parser.add_subparsers(dest="command")

    inspect = sub.add_parser(
        "inspect", help="show slot, money and coin information (read-only)")
    inspect.add_argument("--save", metavar="PATH",
                         help="path to the .srm file (default: auto-detect)")
    inspect.add_argument("--sections", action="store_true",
                         help="also dump the per-section checksum table")
    inspect.add_argument("--json", action="store_true",
                         help="emit machine-readable JSON instead of a report")

    setcoins = sub.add_parser(
        "set-coins",
        help="set the Game Corner coin counter (dry run unless --write)")
    setcoins.add_argument("value", nargs="?", type=int, default=gen3.COIN_MAX,
                          metavar="N",
                          help="coins to set, 0-%d (default: %d)"
                               % (gen3.COIN_MAX, gen3.COIN_MAX))
    setcoins.add_argument("--save", metavar="PATH",
                          help="path to the .srm file (default: auto-detect)")
    setcoins.add_argument("--write", action="store_true",
                          help="actually modify the file (default is a dry run)")
    setcoins.add_argument("--force", action="store_true",
                          help="write even if RetroArch appears to be running")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1

    try:
        path = locate.resolve(args.save)
    except locate.LocateError as exc:
        print("%s: %s" % (PROG, exc), file=sys.stderr)
        return 1

    try:
        save = gen3.Save.load(path)
    except (OSError, gen3.SaveError) as exc:
        print("%s: %s" % (PROG, exc), file=sys.stderr)
        return 1

    if args.command == "set-coins":
        return _set_coins(save, args)

    if args.json:
        print(json.dumps(_as_json(save), indent=2))
        live = save.live_slot
        return 0 if live and live.values_plausible else 1

    return _report(save, args.sections)
