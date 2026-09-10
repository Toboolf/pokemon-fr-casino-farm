# Save format — verified findings

Everything here was **measured against the actual save file on this machine**, not taken
from a wiki. Where a value came from memory or the web it is marked as unverified.

Source file inspected:
`~/Documents/RetroArch/saves/gpSP/pokefirered_patched.srm` (131,072 bytes)

## 1. Container

FRLG+ 1.5.1 is a [`pokefirered` decomp-based hack](https://www.pokecommunity.com/threads/complete-pokefirered-pok%C3%A9mon-firered-leafgreen.454382/)
of FireRed US v1.0 (ROM header game code `BPRE`, maker `01`, version `0x00`). It keeps the
**stock Generation III save layout** — confirmed empirically below.

| Property | Value |
|---|---|
| File size | `0x20000` (128 KiB flash) |
| Slot A | `0x00000` – `0x0DFFF` |
| Slot B | `0x0E000` – `0x1BFFF` |
| Unused tail | `0x1C000` – `0x1FFFF` (all `0xFF`) |
| Sections per slot | 14 × `0x1000` |
| Section data area | `0x000` – `0xF7F` |

Section footer (last 12 bytes of each `0x1000` block):

| Offset | Size | Field |
|---|---|---|
| `+0xFF4` | u16 | section ID (0–13) |
| `+0xFF6` | u16 | checksum |
| `+0xFF8` | u32 | signature — always `0x08012025` |
| `+0xFFC` | u32 | save index |

**Section IDs rotate.** They are *not* stored in ID order — the current file starts slot A at
ID 6 and slot B at ID 5. Sections must always be located by reading the ID at `+0xFF4`, never
by position. This is the single easiest way to write a tool that silently corrupts a save.

**Which slot is live:** the one whose sections carry the higher save index. Currently slot B
(index 23); slot A is the previous save (index 22). The game falls back to the other slot if
the newest fails validation — which is a free safety net, provided we only ever write one slot.

## 2. Locating money and coins

```
SaveBlock2 = section 0                                    (0xF80 bytes)
SaveBlock1 = sections 1, 2, 3, 4 concatenated in ID order (4 × 0xF80 = 0x3E00 bytes)

securityKey = u32 at SaveBlock2 + 0x0F20
money       = u32 at SaveBlock1 + 0x0290  XOR  securityKey
coins       = u16 at SaveBlock1 + 0x0294  XOR (securityKey & 0xFFFF)
```

FRLG (unlike Ruby/Sapphire) XOR-obfuscates money and coins with a per-save-file
`securityKey`. The key differs between the two slots, so it must be read from the same slot
being edited.

**Both fields land in section 1** (`0x294 < 0xF80`), so a coin edit dirties exactly one
section and one checksum.

### Evidence this is correct

Decoding both slots independently, with each slot's own key:

| Slot | Save index | Player | securityKey | money | coins |
|---|---|---|---|---|---|
| A | 22 | `JOSEKUN` | `0x397D45D5` | 114,912 | **9,999** |
| B | 23 | `JOSEKUN` | `0xF4A73E21` | 113,912 | **1,372** |

Three independent confirmations:

1. Both slots produce in-range values (coins ≤ 9999, money ≤ 999999) from two *different* keys.
2. The player name at `SaveBlock2 + 0x00` decodes through the Gen III character table
   (`0xBB` = `A`) to `JOSEKUN`.
3. The two slots tell the expected story: an older save at the 9,999 cap, and a newer one at
   1,372 after prizes were bought — exactly the situation described.

## 3. Checksum

```
sum = 0
for each u32 in section_data[0 : size(section_id)]:
    sum = (sum + u32) & 0xFFFFFFFF
checksum = ((sum >> 16) + (sum & 0xFFFF)) & 0xFFFF
```

Per-section data sizes for FRLG:

| Section ID | Size | | Section ID | Size |
|---|---|---|---|---|
| 0 | `0xF2C` | | 5–12 | `0xF80` |
| 1–3 | `0xF80` | | 13 | `0x7D0` |
| 4 | `0xF08` | | | |

**All 28 sections across both slots validate against this table.** Note `0xF08` for section 4
— the frequently-copied value `0xC40` is the Ruby/Sapphire/Emerald figure and fails here.

For our purposes only section 1 matters, and its size (`0xF80`) is unambiguous.

## 4. Environment inventory

| Item | Value |
|---|---|
| RetroArch | 1.22.2 (Git 69a4f0ea), `/Applications/RetroArch.app` |
| Core | gpSP (`gpsp_libretro.dylib`) — the only core installed |
| ROM | `~/Documents/RetroArch/roms/pokefirered_patched.gba` (16 MiB, md5 `3ff0d0a6d17bafaaba1724ef202da03d`) |
| Save | `~/Documents/RetroArch/saves/gpSP/pokefirered_patched.srm` |
| `sort_savefiles_enable` | `true` → saves nest under `saves/<corename>/` |
| `autosave_interval` | `10` (seconds) |
| `block_sram_overwrite` | `false` |
| `network_cmd_enable` | `false` |

### gpSP capability limits (from `info/gpsp_libretro.info`)

```
cheats             = "false"
memory_descriptors = "false"
savestate          = "true"   (savestate_features = "deterministic")
```

These two `false` values are what rule out the cheat-code and live-memory approaches — see
[PLAN.md](PLAN.md) §2. The core does export `retro_get_memory_data`, so RetroArch's *built-in*
cheat search may partially function, but nothing about it is advertised as supported.
