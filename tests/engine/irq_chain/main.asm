// irq_chain spike (M3 stage 1): four chain entries change the border colour at four lines,
// screen on (badlines active), no sprites. Proves engine/irq.asm: chaining, the frame tick,
// the stable entry, and the costs in tests/engine/irq_chain/budget.json.
//
//   Entry  Line        Kind    Handler   Border
//   0      $20 (32)    normal  spike_h0  white   top border, frame entry
//   1      $69 (105)   normal  spike_h1  red     display area; 105 and 106 (where its exit ends) are not badlines
//   2      $B1 (177)   STABLE  spike_h2  cyan    triggers at $AF; 175-178 are not badlines (171, 179 are)
//   3      $FA (250)   normal  spike_h3  purple  last display line, below the last badline (243)
//
// Lines: every handler's exit (60 cycles) runs into the next line, so that line mustn't be a
// badline either, or irq_exit's measured cost includes 43 cycles of DMA. The README's first
// layout ($6A, $B2) did exactly that: irq_exit measured 102-103 after h1 and h2 (badlines 107
// and 179), 60 after h0. Moved up one line each (engine/README.md#irq_chain).
//
// The main loop generates worst-case IRQ jitter: 7-cycle `inc abs,x` mixed with 2-, 3- and
// 5-cycle instructions, with taken branches right before each `inc abs,x` (a taken branch can
// delay the IRQ by one more instruction). An 8-bit LFSR picks one of two path lengths (30 or
// 37 cycles) each pass, so the loop's phase does a random walk and the IRQs land on every
// phase. A fixed-length loop doesn't: the IRQs' own durations feed back into the phase, and a
// 25-cycle loop locked into 5 phases at h0 over 1,000 frames.
//
// Build: make GAME=irq_chain SRC_DIR=tests/engine/irq_chain
// Measure: cd mcp/vice && uv run python ../../tests/engine/irq_chain/measure.py [frames]
// Screenshot: screenshots/irq-chain-bands.png (vice_screenshot area="full")

BasicUpstart2(start)

#import "zp.asm"

.const VIC_BORDER = $d020

* = $0810 "Engine"
#import "engine/irq.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal($20, spike_h0)
        IrqNormal($69, spike_h1)
        IrqStable($b1, spike_h2)
        IrqNormal($fa, spike_h3)
        IrqChainEnd()

* = * "Spike"
start:
        jsr irq_init
        jsr irq_wait_frame              // proves the frame tick reaches the main loop
        sta spike_frame_seen
        lda #$01
        sta zp_spike_lfsr               // any non-zero seed
        ldx #0

// TIMING: jitter generator, 30 cycles per pass (LFSR carry clear) or 37 (carry set),
// +3 every 256 passes (bne not taken, jmp).
spike_main:
!loop:  inc spike_scratch,x             // 7
        asl zp_spike_lfsr               // 5  Galois LFSR, x^8+x^4+x^3+x^2+1: period 255
        bcc !+                          // 3 taken (then inc) / 2
        lda zp_spike_lfsr               // 3
        eor #$1d                        // 2
        sta zp_spike_lfsr               // 3
!:      inc spike_scratch,x             // 7
        bit zp_spike_jit                // 3
        inx                             // 2
        bne !loop-                      // 3 taken (then inc)
        jmp !loop-                      // 3

// Handlers: the border colour is each one's first store.
spike_h0:
        lda #WHITE                      // 2
        sta VIC_BORDER                  // 4
        IrqDone()

spike_h1:
        lda #RED
        sta VIC_BORDER
        IrqDone()

spike_h2:
        lda #CYAN
        sta VIC_BORDER
        IrqDone()

spike_h3:
        lda #PURPLE
        sta VIC_BORDER
        IrqDone()

spike_frame_seen:
        .byte 0

.align $100
spike_scratch:                          // inc abs,x target: page-aligned, always 7 cycles
        .fill 256, 0
