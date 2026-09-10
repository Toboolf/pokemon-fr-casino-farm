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
| M1 — Read-only inspector | ⬜ Not started |
| M2 — Coin writer | ⬜ Not started |
| M3 — Guardrails | ⬜ Not started |
| M4 — Convenience | ⬜ Not started |

No code has been written yet — this repo currently holds the investigation and the plan.

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
