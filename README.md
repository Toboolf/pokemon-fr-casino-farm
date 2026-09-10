# pokemon-fr-casino-farm

Tooling to buy out the Celadon Game Corner prize counters in **Pokémon FireRed & LeafGreen+
(FRLG+) v1.5.1**, running under **RetroArch 1.22.2 + gpSP** on macOS.

## The problem in one line

The coin counter is capped at **9,999**, the full prize sweep costs **~39,000 coins**, so the
counter has to be refilled several times. It is a *cap* problem, not a *farming rate* problem.

## The approach in one line

Edit the coin field directly in RetroArch's `.srm` save file between play sessions — 4 bytes,
one section, one slot — and let the game handle every actual purchase.

## Status

| Milestone | State |
|---|---|
| M0 — Research + plan | ✅ Done |
| M1 — Read-only inspector | ✅ Done |
| M2 — Coin writer | ✅ Done (incl. the M3 running-emulator guard) |
| M3 — Remaining guardrails | ⬜ Not started |
| M4 — Convenience | ⬜ Not started |

## The refill loop

```
1. In game    save at the Game Corner
2. RetroArch  Close Content        <- not pause; RetroArch would overwrite the edit
3. Terminal   python3 -m frcoins set-coins --write
4. RetroArch  load content -> Continue
5. In game    spend down at the prize counters
   repeat, roughly 4 times
```

Step 2 is the one that bites if skipped, so the tool refuses to write while RetroArch
is running rather than letting the edit be silently overwritten.

## Usage

Requires Python 3 and nothing else — no dependencies, no install step.

```
python3 -m frcoins inspect              # auto-detects the RetroArch .srm
python3 -m frcoins inspect --sections   # + per-section checksum table
python3 -m frcoins inspect --json       # machine-readable
python3 -m frcoins inspect --save PATH  # explicit file

python3 -m frcoins set-coins            # dry run: show what would change
python3 -m frcoins set-coins --write    # apply it (9999 by default)
python3 -m frcoins set-coins 500 --write
```

`set-coins` is a **dry run unless you pass `--write`**. It refuses to write when
RetroArch is running (override with `--force`), when the value is outside 0-9999, when
neither slot is intact, when the decoded values look implausible, or when the edit would
touch any byte outside the coin field and its checksum. The whole edit is assembled and
verified in memory first, so a rejected edit never reaches the disk.

Every write makes a timestamped `.bak` next to the save first, and the undo command is
printed on success.

The save is auto-detected from the usual RetroArch directories; if more than one
`.srm` turns up, the tool lists them and asks you to pick with `--save`. You can also
set `FRCOINS_SAVE`.

Sample output:

```
Slot  Index  Sections  Checksums  Player     Money  Coins
----  -----  --------  ---------  -------  -------  -----
A        22     14/14   14/14 ok  JOSEKUN  114,912  9,999
B <-     23     14/14   14/14 ok  JOSEKUN  113,912  1,372

Live slot B  (save index 23 - this is the one the game loads)

  Coins         1,372 / 9,999  (8,627 below the cap)
  Coin field    SaveBlock1+0x0294 -> section 1, file offset 0x18294 (raw 0x3B7D)
  Sanity check  decoded values are within the game's own limits: OK
```

Exit code is non-zero if neither slot is intact, or if the decoded values fall outside
the game's own limits — the latter is the signal that the offsets are wrong for your ROM
and that M2 must not write to the file.

## Tests

```
python3 -m unittest discover -s tests
```

49 tests, stdlib `unittest`. They build synthetic saves in memory, so the checksum
algorithm, the section-size table, slot selection and the write path are all covered
without depending on anyone's real save file.

## Layout

```
frcoins/gen3.py    save format: sections, checksums, slot selection, field decoding
frcoins/writer.py  building and verifying edits -- pure bytes in, bytes out
frcoins/store.py   timestamped backups and crash-safe atomic writes
frcoins/guard.py   refusing to run while RetroArch holds the save
frcoins/locate.py  finding RetroArch's .srm
frcoins/cli.py     argparse front end
tests/             synthetic-save tests
```

## Docs

- **[docs/PLAN.md](docs/PLAN.md)** — approaches considered and rejected, the chosen design,
  milestones, risks, open questions.
- **[docs/SAVE-FORMAT.md](docs/SAVE-FORMAT.md)** — the Gen III save layout as *measured on this
  machine*: slot selection, security key, coin/money offsets, the checksum algorithm and its
  per-section sizes, plus the RetroArch/gpSP environment inventory.

## Key facts

```
save file   ~/Documents/RetroArch/saves/gpSP/pokefirered_patched.srm   (131072 bytes)
live slot   the one with the higher save index at +0xFFC
key         u32 @ SaveBlock2 + 0x0F20            (SaveBlock2 = section 0)
coins       u16 @ SaveBlock1 + 0x0294  XOR key   (SaveBlock1 = sections 1..4)
money       u32 @ SaveBlock1 + 0x0290  XOR key
checksum    section 1, folded u32 sum over 0xF80 bytes, stored at +0xFF6
```

gpSP declares `cheats = "false"` and `memory_descriptors = "false"`, which is why cheat codes
and live memory writes are off the table. See [docs/PLAN.md §2](docs/PLAN.md).

## Safety

Never edit the `.srm` while RetroArch has the content loaded — it flushes SRAM from memory
every 10 seconds and on close, and will overwrite the edit. Close Content first. Always back up.

ROMs and save files are gitignored and must never be committed.
