# Plan — Game Corner coin farming for FRLG+ 1.5.1

## 1. The actual problem

The goal is not "more coins per hour". The coin counter is a **u16 hard-capped at 9,999**, and
the full FireRed prize sweep costs roughly **~39,000 coins**. No farming rate solves that; the
cap does not move. What is actually needed is a way to **refill the counter to 9,999 several
times**, spending it down in between.

So the deliverable is a *refill tool*, not a *farming bot*. That reframing collapses a
multi-hour automation problem into a two-byte write.

Sizing, for reference (vanilla FireRed figures — see §7):

| Group | Coins |
|---|---|
| Pokémon prizes (Abra 180, Clefairy 500, Dratini 2,800, Scyther 5,500, Porygon 9,999) | 18,979 |
| TM prizes | ~20,000 |
| **Total** | **~39,000 → 4 fills** |

You are currently at 1,372 coins / ₽113,912, so realistically **4 more fills** finishes it.

## 2. Approaches considered

| # | Approach | Verdict |
|---|---|---|
| 1 | Bot the slot machines with synthetic input | ❌ Rejected |
| 2 | RetroArch cheat codes (GameShark/AR) | ❌ Blocked by the core |
| 3 | Live RAM writes via RetroArch's Network Control Interface | ❌ Blocked by the core |
| 4 | Swap gpSP → mGBA to unlock 2 and 3 | 🟡 Plan B |
| 5 | Buy coins with money instead | ❌ Doesn't address the cap |
| 6 | Write the prize items straight into the save | ❌ Rejected on blast radius |
| 7 | **Edit the coin field in the `.srm` between sessions** | ✅ **Chosen** |

**1 — Slot botting.** Even at max payout this is hours of wall-clock time, and it needs
macOS-level synthetic keystrokes plus screen reading to know when to act. gpSP exposes no input
API. High effort, high fragility, and it still cannot exceed 9,999 in one sitting — it would
have to be re-run per fill anyway.

**2 — Cheat codes.** `gpsp_libretro.info` declares `cheats = "false"`. The core does not
implement the libretro cheat interface for RetroArch's frontend, so no AR/GameShark code will
apply. ([Community reports](https://gbatemp.net/threads/using-gameshark-in-retroarch.512977/)
also describe GameShark on RetroArch as broadly unworkable.)

**3 — Live memory writes.** `WRITE_CORE_MEMORY` over the
[Network Control Interface](https://docs.libretro.com/development/retroarch/network-control-interface/)
resolves addresses through the core's *system memory map*. gpSP declares
`memory_descriptors = "false"`, so it advertises no map and the command has nothing to write
through. (`network_cmd_enable` is also currently `false`, but that's the lesser problem.)

**4 — Switch to mGBA.** This is the real Plan B and it is cheap insurance: mGBA supports
cheats, memory descriptors and RetroAchievements, and would make 2 and 3 work. It is *not* the
first choice because it changes the emulator under a run in progress and invalidates gpSP save
states. Worth noting: **`.srm` is core-independent**, so the chosen approach keeps working
either way, and switching cores later costs nothing.

**5 — Money.** The prize counter costs coins, and the desk sells 50 coins per ₽1,000. Money is
therefore never the binding constraint — the 9,999 ceiling is. Irrelevant once we can set coins
directly, though the tool gets money top-up for free since the field is 4 bytes away.

**6 — Injecting the prizes directly.** Tempting, but bad. Item IDs may have been remapped by
the hack; the Pokémon prizes need correct PID/IVs/OT/met-location data that the game generates
properly and a tool would have to fake; and it touches far more of the save. Let the game do
the work it already knows how to do.

**7 — Editing coins in the `.srm`. Chosen.** Smallest possible change: two bytes of payload
plus a two-byte checksum, inside a single section, in a single slot, with the other slot left
intact as a fallback. The game performs every real operation — purchase, Pokémon generation,
bag updates — so the resulting save is indistinguishable from legitimate play. And the format
is not guesswork: it has been fully verified against this exact file
(see [SAVE-FORMAT.md](SAVE-FORMAT.md)).

## 3. How it works

```
locate slot with highest save index
  └─ read securityKey  from section 0 (SaveBlock2) + 0x0F20
  └─ read/write coins  at  section 1 (SaveBlock1) + 0x0294, XOR (key & 0xFFFF)
  └─ recompute section 1 checksum over 0xF80 bytes, store at +0xFF6
```

Confirmed in [SAVE-FORMAT.md](SAVE-FORMAT.md): the whole edit touches **one section, one
slot** — 4 bytes total.

## 4. The operational loop

RetroArch keeps SRAM in memory and flushes to `.srm` on a 10-second autosave timer and again on
content close. **Editing the file while content is loaded will be overwritten.** So:

1. In game: save at the Game Corner (in-game save → writes SRAM).
2. RetroArch: **Close Content** — pausing is not enough.
3. Run the refill tool.
4. Load content → Continue.
5. Spend down at the prize counters.
6. Repeat (~4 times).

Roughly a minute of overhead per fill. Note step 2 is the one that bites if skipped, which is
why it becomes an enforced guardrail in M3.

## 5. Milestones

**M0 — Project scaffolding.** ✅ This document, the verified format spec, `.gitignore`.

**M1 — Read-only inspector.** `inspect` subcommand: parse the file, print the slot table (ID,
save index, checksum valid/invalid), the security key, and decoded money + coins for both
slots. Writes nothing.
*Acceptance:* reported coins match what the game shows on screen.

**M2 — The writer.** `set-coins <n>` (default 9999): timestamped backup first, edit newest
slot only, recompute the section-1 checksum, then **re-open and re-parse the written file** to
confirm it reads back correctly before declaring success.
*Acceptance:* game boots with no "save file is corrupted" message and shows 9,999 coins.

**M3 — Guardrails.** Refuse to run while a RetroArch process is live; refuse values above
9,999; refuse to write if any section checksum fails *before* the edit (that means something is
already wrong — don't compound it); `--dry-run` as the default with an explicit `--write`.

**M4 — Convenience.** `--money`, `restore` from backup, and a prize checklist so the sweep can
be tracked across fills.

Suggested implementation language: **Python 3 stdlib only** — it is already on the machine, the
entire format is `struct.unpack_from`, and zero dependencies means this still runs in two years.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Corrupting the save | Mandatory timestamped backup; write one slot only, so the previous save survives as the game's own fallback; verify by re-parsing after write |
| FRLG+ moved the offsets | Already disproven empirically (§ SAVE-FORMAT §2), and M1 re-validates plausibility on every run |
| RetroArch overwrites the edit | M3 refuses to run while RetroArch is up |
| Section-4 size myth (`0xC40`) | Verified as `0xF08` here; irrelevant to coins but will matter if the tool ever grows |
| Rotating section IDs | Always locate sections by the ID at `+0xFF4`, never by position |

## 7. Open questions

1. **FRLG+'s actual prize list.** Two sources disagree on the vanilla FireRed TM prizes — one
   gives TM13/23/24/30/35 (~20,000 coins), another lists a set that appears to belong to
   Emerald's Mauville Game Corner. Since this is a romhack, **the in-game prize menu is the only
   authoritative source**. This does not block anything: with a refill tool the exact total
   stops mattering — just top up whenever you run low.
2. Do you want money top-up in the tool as well, or coins only?
3. Confirm the emulator stays gpSP (Plan B mGBA remains available and costs nothing later).
