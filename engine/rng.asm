// engine/rng.asm: 8-bit pseudo-random numbers (M4 stage 1). Design contract: engine/rng.md
//
// API
//   rng_seed   In: A = seed low, X = seed high. Seed 0/0 (which would stop the generator) is
//              replaced by RNG_SEED_DEFAULT.
//   rng_next   Out: A = 0-255. Uses A only: X and Y are preserved.
//
// Algorithm: 16-bit xorshift, shifts 7, 9, 8:
//       s ^= s << 7;  s ^= s >> 9;  s ^= s << 8;      (s = zp_rng_hi:zp_rng_lo, 16 bits)
//   and the byte returned is the new high byte. The step is a bijection on the 65,535 non-zero
//   states and they form ONE cycle, so the sequence repeats after exactly 65,535 calls from any
//   seed, and state 0 is never reached from a non-zero state. Over a period the high byte takes
//   each value 1-255 256 times and 0 255 times (all 65,536 states less the zero state).
//   The 6502 arrangement (two rotates through carry instead of 7 and 9 shifts) is John Metcalf's.
//   The same code is assembled in DEBUG and release (no #if), so the sequence is the same.
//
// Zero page (defined by the game's zp.asm): zp_rng_lo, zp_rng_hi. Main loop only: not IRQ-safe.
//
// Measured (VICE 3.10 x64sc PAL, tests/engine/rng, 2026-10-02):
//   rng_next -> rng_next_end (its rts)   30 raster cycles, every pass (= the instruction count;
//                                        top-border line, no DMA, no IRQ inside)
//   with the caller's jsr and the rts    42
//   Size                                 37 bytes (rng_seed 17, rng_next 20)
//   Period                               65,535 (the spike counts it in VICE; check.py's model agrees)
//   Byte histogram over one period       255-256 of each value
//   Low 5 bits per 256 calls             each value 0-21 times (mean 8): what a random source gives.
//                                        See engine/rng.md for the figures against the contract's limits
// Constraints:
//   - Constant time: no branches in rng_next.
//   - Not for anything that needs unpredictability beyond a game's.
//   - A game that needs a number below n masks to the next power of two and retries.

.errorif zp_rng_lo > $ff, "zp_rng_lo must be in zero page"
.errorif zp_rng_hi > $ff, "zp_rng_hi must be in zero page"

.const RNG_SEED_DEFAULT = $2a6d         // used in place of seed 0/0; any non-zero value would do

// Seed the generator. Any value is accepted; 0/0 is replaced by RNG_SEED_DEFAULT.
// In: A = seed low, X = seed high   Out: nothing   Uses: A
// Cost: 13 + rts 6, or 22 + rts 6 for seed 0/0 (counted; called once a game, not budgeted)
rng_seed:
        sta zp_rng_lo                   // 3
        stx zp_rng_hi                   // 3
        ora zp_rng_hi                   // 3  zero only if both bytes are
        bne !+                          // 3 taken / 2
        lda #<RNG_SEED_DEFAULT          // 2
        sta zp_rng_lo                   // 3
        lda #>RNG_SEED_DEFAULT          // 2
        sta zp_rng_hi                   // 3
!:      rts                             // 6

// Next random byte. Main loop only.
// In:  nothing
// Out: A = 0-255 (= the new zp_rng_hi)
// Uses: A only (X and Y are preserved, so it can be called inside an indexed loop)
// Cost: 30 raster cycles to rng_next_end (measured, every pass: tests/engine/rng, no DMA, no IRQ
//       inside), + rts 6 + the caller's jsr 6 = 42
// TIMING: constant path, no branches: 30 cycles, locked in tests/engine/rng/budget.json.
rng_next:
        lda zp_rng_hi                   // 3
        lsr                             // 2  C = bit 8 of s
        lda zp_rng_lo                   // 3
        ror                             // 2  A = (s << 7) >> 8, C = bit 0 of s
        eor zp_rng_hi                   // 3
        sta zp_rng_hi                   // 3  high byte of s ^= s << 7
        ror                             // 2  A = that >> 1 with bit 0 of s on top: s >> 9, plus bit 7 of the low byte of s << 7
        eor zp_rng_lo                   // 3
        sta zp_rng_lo                   // 3  low byte of s ^= s << 7 and of s ^= s >> 9 (its high byte is 0)
        eor zp_rng_hi                   // 3
        sta zp_rng_hi                   // 3  s ^= s << 8      = 30
rng_next_end:
        rts                             // 6
