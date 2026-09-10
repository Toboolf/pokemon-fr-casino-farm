# pokemon-frlg-coin-refill

Refill the Celadon Game Corner coin counter in a **Pokémon FireRed / LeafGreen** save, so you
can buy out the prize counters despite the 9,999 coin cap.

Developed and verified against **FRLG+ v1.5.1** under RetroArch + gpSP on macOS, but nothing
in it is specific to that hack, that emulator or that OS — see [Compatibility](#compatibility).

## The problem in one line

The coin counter is capped at **9,999**, the full prize sweep costs **~39,000 coins**, so the
counter has to be refilled several times. The cap is the constraint, not how fast you can win
coins — no run of luck at the slots gets you past 9,999 in one sitting.

## The approach in one line

Edit the coin field directly in the `.srm` battery save between play sessions — 4 bytes, one
section, one slot — and let the game handle every actual purchase.

## Compatibility

| Target | Status |
|---|---|
| FRLG+ v1.5.1 | ✅ Verified end to end |
| Vanilla FireRed / LeafGreen | ✅ Expected to work, untested |
| Other `pokefirered` decomp hacks | ✅ Expected to work, untested |
| Ruby / Sapphire / Emerald | ❌ Not supported |

Every constant in `gen3.py` is the stock FireRed/LeafGreen save layout — FRLG+ works precisely
*because* it is a `pokefirered` decomp hack that did not move any of it. So vanilla FRLG and
most FR-based hacks should work unchanged. That is reasoning, not a test result: the only save
this has been run against is an FRLG+ one.

If the offsets are wrong for your ROM, the tool refuses rather than corrupting anything — the
plausibility gate catches decoded values outside the game's own limits.

Ruby/Sapphire/Emerald are a different layout: Emerald puts money at `0x0490` and the security
key at `0x01F4`, Ruby/Sapphire have no security key at all, and their section 4 is `0xC40`.
Do not point this at one.

**Emulator-agnostic.** A `.srm` is just the raw battery file, and `--save` takes any path, so
mGBA, VBA-M or a real cartridge dump all work. Only the auto-detection is RetroArch-flavoured.

## Status

| Milestone | State |
|---|---|
| M0 — Research + plan | ✅ Done |
| M1 — Read-only inspector | ✅ Done |
| M2 — Coin writer | ✅ Done, validated in-game |
| M3 — Guardrails | ✅ Folded into M2 |
| M4 — Convenience | ⬜ Not needed so far |

**Outcome:** the prize counters were bought out over five refill cycles on 2026-09-10,
plus extra Pokémon and items. The goal the repo exists for is met.

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

## No computer? Use the web version

For anyone on a phone — or without Python — there is a browser version that does the same
thing with no install:

**https://toboolf.github.io/pokemon-frlg-coin-refill/**

Pick your `.srm`, it shows your player name and current coins, and hands back a fixed file.
It runs entirely in the browser: the save is never uploaded and there is no server. The page
is `index.html` in this repo, and its logic is verified byte-for-byte against the Python
implementation.

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

## License

[MIT](LICENSE) — no ROM, save file, or game asset is included or distributed here.
