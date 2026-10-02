// rng spike (M4 stage 1): proves engine/rng.asm against its contract, engine/rng.md.
//
// 1. Zero seed: rng_seed with A = X = 0, then 256 calls. spike_zero_ok = 1 if they aren't all
//    the same value. spike_zero_state (2) = the state rng_seed set (RNG_SEED_DEFAULT).
// 2. Statistics over one whole period from SPIKE_SEED, with the screen off (no badlines):
//      spike_period (2)      calls until the state is SPIKE_SEED again. 0 = more than 65,535
//      spike_hist_min/max (2 each)  fewest / most times any byte value came out in the period
//      spike_low5_min/max    over every complete block of 256 consecutive calls (255 blocks: the
//                            period is 255 x 256 + 255, and the last 255 calls are not a block),
//                            the fewest / most times any value of (output & $1f) came out
//      spike_bit_min/max     over the same 255 blocks and each of bits 0-4 of the output (1,275
//                            cells): the fewest / most calls in a block in which a bit was 1.
//                            Model: 103 / 157 (engine/rng.md#low-bit-limits)
//      spike_blocks          complete blocks seen (255)
//      spike_done            1 when all of the above are final (stays 0 if the period overflowed)
//    About 135 cycles a call with the block ends and the frame IRQ (90 before the five bit
//    counters): spike_done = 1 at frame 450 after entry (measured: check.py --finish-frame;
//    budget.json and check.py warm up for 600).
// 3. Then the screen comes back on with the results in hex, and the main loop calls rng_next
//    once a frame straight after irq_wait_frame for the profile check: lines $11-$12, top border,
//    no DMA, the frame's only IRQ already over.
//
// Chain: entry 0 only, line $10 (so the budget runner has its IRQ labels).
//
// Build:  make GAME=rng SRC_DIR=tests/engine/rng
// Budget: make test ARGS=rng            (tests/engine/rng/budget.json)
// Model:  uv run --package budget-runner python tests/engine/rng/check.py
// Screenshot: screenshots/rng-spike-stage2.png

BasicUpstart2(start)

#import "zp.asm"

.const VIC_CTRL1      = $d011
.const VIC_BORDER     = $d020
.const VIC_BACKGROUND = $d021
.const SCREEN         = $0400
.const COLOUR_RAM     = $d800

.const SPIKE_SEED = $1234

.const ROW_TITLE  = SCREEN + 1 * 40 + 4
.const ROW_PERIOD = SCREEN + 4 * 40 + 4
.const ROW_HIST   = SCREEN + 6 * 40 + 4
.const ROW_LOW5   = SCREEN + 8 * 40 + 4
.const ROW_BLOCKS = SCREEN + 9 * 40 + 4
.const ROW_BITS   = SCREEN + 10 * 40 + 4
.const ROW_ZERO   = SCREEN + 12 * 40 + 4
.const ROW_DONE   = SCREEN + 14 * 40 + 4
.const COL_VALUE  = 24

.encoding "screencode_upper"

.macro SpikeText(addr, text) {
        ldx #text.size() - 1
!:      lda data,x
        sta addr,x
        dex
        bpl !-
        jmp done
data:   .text text
done:
}

.macro SpikeHex(value, addr) {
        lda value
        lsr
        lsr
        lsr
        lsr
        tax
        lda spike_hex_chars,x
        sta addr
        lda value
        and #$0f
        tax
        lda spike_hex_chars,x
        sta addr + 1
}

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/rng.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal($10, spike_h0)
        IrqChainEnd()

* = * "Spike"
start:
        lda #BLACK
        sta VIC_BORDER
        sta VIC_BACKGROUND
        lda #$0b                        // screen off (bit 7 clear): no badlines while counting
        sta VIC_CTRL1
        ldx #0
!:      lda #' '
        sta SCREEN,x
        sta SCREEN + $100,x
        sta SCREEN + $200,x
        sta SCREEN + $2e8,x
        lda #LIGHT_GREY
        sta COLOUR_RAM,x
        sta COLOUR_RAM + $100,x
        sta COLOUR_RAM + $200,x
        sta COLOUR_RAM + $2e8,x
        lda #0
        sta spike_hist_lo,x
        sta spike_hist_hi,x
        inx
        bne !-
        jsr irq_init

        // 1. Zero seed.
        lda #0
        tax
        jsr rng_seed
        lda zp_rng_lo
        sta spike_zero_state
        lda zp_rng_hi
        sta spike_zero_state + 1
        jsr rng_next
        sta zp_spike_1st
        lda #0
        sta zp_spike_or
        ldy #255                        // 255 more calls: 256 in all
!:      jsr rng_next
        eor zp_spike_1st
        ora zp_spike_or
        sta zp_spike_or
        dey
        bne !-
        lda zp_spike_or
        beq !+
        lda #1
        sta spike_zero_ok
!:
        // 2. One whole period.
        lda #<SPIKE_SEED
        ldx #>SPIKE_SEED
        jsr rng_seed
        lda #0
        sta zp_spike_blk                // 256 calls to the first block end
spike_call:
        jsr rng_next                    // 42
        tax                             // 2
        inc spike_hist_lo,x             // 7
        bne !+                          // 3
        inc spike_hist_hi,x
!:      and #$1f                        // 2
        tax                             // 2
        inc spike_low5,x                // 7
        // Ones in each of bits 0-4 (A = output & $1f): 5 or 10 a bit, 37.5 on average.
        lsr                             // 2   bit 0 to carry
        bcc !+                          // 3 / 2
        inc spike_bits                  // 6
!:      lsr                             //     bit 1
        bcc !+
        inc spike_bits + 1
!:      lsr                             //     bit 2
        bcc !+
        inc spike_bits + 2
!:      lsr                             //     bit 3
        bcc !+
        inc spike_bits + 3
!:      lsr                             //     bit 4
        bcc !+
        inc spike_bits + 4
!:
        inc spike_period                // 6
        bne !+                          // 3
        inc spike_period + 1
        beq spike_idle                  // more than 65,535 calls: give up, spike_done stays 0
!:      dec zp_spike_blk                // 5
        bne !+                          // 3
        jsr spike_block_end
!:      lda zp_rng_lo                   // 3
        cmp #<SPIKE_SEED                // 2
        bne spike_call                  // 3   = 90 + 37.5 a call
        lda zp_rng_hi
        cmp #>SPIKE_SEED
        bne spike_call

        // Fewest and most of any byte value (16-bit counts).
        ldx #0
!loop:  lda spike_hist_lo,x
        cmp spike_hist_min
        lda spike_hist_hi,x
        sbc spike_hist_min + 1
        bcs !+
        lda spike_hist_lo,x
        sta spike_hist_min
        lda spike_hist_hi,x
        sta spike_hist_min + 1
!:      lda spike_hist_max
        cmp spike_hist_lo,x
        lda spike_hist_max + 1
        sbc spike_hist_hi,x
        bcs !+
        lda spike_hist_lo,x
        sta spike_hist_max
        lda spike_hist_hi,x
        sta spike_hist_max + 1
!:      inx
        bne !loop-
        lda #1
        sta spike_done

spike_idle:
        // 3. Results, then one call a frame.
        SpikeText(ROW_TITLE,  "ENGINE/RNG.ASM  XORSHIFT 7,9,8")
        SpikeText(ROW_PERIOD, "PERIOD                 $")
        SpikeText(ROW_HIST,   "BYTE COUNT MIN/MAX     $")
        SpikeText(ROW_LOW5,   "LOW 5 BITS MIN/MAX     $")
        SpikeText(ROW_BLOCKS, "  IN BLOCKS OF 256     $")
        SpikeText(ROW_BITS,   "BIT 0-4 ONES MIN/MAX   $")
        SpikeText(ROW_ZERO,   "ZERO SEED OK           $")
        SpikeText(ROW_DONE,   "DONE                   $")
        SpikeHex(spike_period + 1,   ROW_PERIOD + COL_VALUE)
        SpikeHex(spike_period,       ROW_PERIOD + COL_VALUE + 2)
        SpikeHex(spike_hist_min + 1, ROW_HIST + COL_VALUE)
        SpikeHex(spike_hist_min,     ROW_HIST + COL_VALUE + 2)
        SpikeHex(spike_hist_max + 1, ROW_HIST + COL_VALUE + 5)
        SpikeHex(spike_hist_max,     ROW_HIST + COL_VALUE + 7)
        SpikeHex(spike_low5_min,     ROW_LOW5 + COL_VALUE)
        SpikeHex(spike_low5_max,     ROW_LOW5 + COL_VALUE + 3)
        SpikeHex(spike_blocks,       ROW_BLOCKS + COL_VALUE)
        SpikeHex(spike_bit_min,      ROW_BITS + COL_VALUE)
        SpikeHex(spike_bit_max,      ROW_BITS + COL_VALUE + 3)
        SpikeHex(spike_zero_ok,      ROW_ZERO + COL_VALUE)
        SpikeHex(spike_done,         ROW_DONE + COL_VALUE)
        lda #$1b                        // screen on
        sta VIC_CTRL1
spike_main:
        jsr irq_wait_frame
        jsr rng_next                    // lines $11-$12: no DMA, no IRQ inside
        sta spike_last
        jmp spike_main

// End of a block of 256 calls: fold the 32 value counts and the 5 bit counts into their mins and
// maxes, and clear them. A bit that was 1 in all 256 calls has wrapped its count to 0 (reads as
// a min of 0, which fails the budget check: no 16-bit count needed).
// In: nothing   Out: nothing   Uses: A, X
spike_block_end:
        ldx #31
!loop:  lda spike_low5,x
        cmp spike_low5_min
        bcs !+
        sta spike_low5_min
!:      cmp spike_low5_max
        bcc !+
        sta spike_low5_max
!:      lda #0
        sta spike_low5,x
        dex
        bpl !loop-
        ldx #4
!loop:  lda spike_bits,x
        cmp spike_bit_min
        bcs !+
        sta spike_bit_min
!:      cmp spike_bit_max
        bcc !+
        sta spike_bit_max
!:      lda #0
        sta spike_bits,x
        dex
        bpl !loop-
        inc spike_blocks
        rts

spike_h0:
        IrqDone()

spike_period:   .word 0
spike_done:     .byte 0
spike_hist_min: .word $ffff
spike_hist_max: .word 0
spike_low5_min: .byte $ff
spike_low5_max: .byte 0
spike_bit_min:  .byte $ff                // fewest ones in a block for any of bits 0-4
spike_bit_max:  .byte 0                  // most
spike_blocks:   .byte 0
spike_zero_ok:  .byte 0
spike_zero_state: .word 0               // the state rng_seed left for seed 0/0 (RNG_SEED_DEFAULT)
spike_last:     .byte 0                 // the byte from this frame's call
spike_low5:     .fill 32, 0
spike_bits:     .fill 5, 0              // ones in this block for bits 0-4
spike_hex_chars:
        .text "0123456789ABCDEF"

.align $100
spike_hist_lo:  .fill 256, 0
spike_hist_hi:  .fill 256, 0
