// engine/input.asm: joystick in port 2 (M4 stage 1). Design contract: engine/input.md
//
// API
//   input_init   Set CIA 1 port A to all inputs and clear the state. Call once, before or after
//                irq_init.
//   input_read   Sample the stick. Main loop, once per frame, first thing after irq_wait_frame.
//                Out: zp_joy = the stick now, zp_joy_pressed = bits that are 1 now and were 0 at
//                the last call, A = zp_joy.
//
// Bits, active high (1 = pressed), in zp_joy and zp_joy_pressed. Bits 5-7 are always 0.
//   JOY_UP $01   JOY_DOWN $02   JOY_LEFT $04   JOY_RIGHT $08   JOY_FIRE $10
//
// Registers owned (nothing else writes them): $DC00 (read only here) and $DC02, which input_init
// sets to $00. The module never touches $DC0D (the IRQ framework's).
// Zero page (defined by the game's zp.asm): zp_joy, zp_joy_pressed. Main loop only: no IRQ may
// read or write either (zp_joy_pressed holds a scratch value for 15 cycles inside input_read).
//
// Measured cost (VICE 3.10 x64sc PAL, tests/engine/input, make test, 2026-10-02). Raster cycles,
// called on a top-border line with no DMA and no IRQ inside it:
//   input_read -> input_read_end (its rts)     28, every pass (= the instruction count)
//   with the caller's jsr and the rts          40
//   Size                                       32 bytes (input_init 10, input_read 22)
// Constraints:
//   - No debounce: one sample a frame, and a state seen in one sample counts.
//   - Call input_read exactly once a frame. Twice in a frame, or less than once a frame, loses
//     edges (the second call sees nothing newly pressed).
//   - Left + right or up + down together are reported as they are.
//   - With $DC02 = $00 the keyboard can't be scanned (port A drives the keyboard columns). A
//     program that wants the keyboard sets $DC02 back to $FF itself, and then owns the problem
//     input_init solves: a 0 in bits 0-4 of the $DC00 output latch reads as a held direction.
//     MEASURED (tests/engine/input/check.py, cases "ddr"): with $DC02 = $FF and the latch = $00,
//     zp_joy reads $1F with the stick idle; with $DC02 = $00 the latch has no effect.
//   - Port 1 ($DC01) is not read and has no effect (measured, same script).

.errorif zp_joy > $ff, "zp_joy must be in zero page"
.errorif zp_joy_pressed > $ff, "zp_joy_pressed must be in zero page"

.const JOY_UP    = $01
.const JOY_DOWN  = $02
.const JOY_LEFT  = $04
.const JOY_RIGHT = $08
.const JOY_FIRE  = $10
.const JOY_MASK  = $1f

.const INPUT_CIA1_PRA  = $dc00          // port A data: joystick port 2 on bits 0-4, active low
.const INPUT_CIA1_DDRA = $dc02          // port A direction: 0 = input

// Set up CIA 1 for reading port 2 and clear the state. Call once, before irq_init or after.
// In: nothing   Out: zp_joy = zp_joy_pressed = 0   Uses: A
// Cost: 16 + rts 6 (counted; called once, not budgeted)
input_init:
        lda #$00                        // 2
        sta INPUT_CIA1_DDRA             // 4  all of port A inputs: the output latch can't mask the stick
        sta zp_joy                      // 3
        sta zp_joy_pressed              // 3
        rts                             // 6

// Sample the joystick. Main loop, once per frame, first thing after irq_wait_frame.
// In:  nothing
// Out: zp_joy = the stick now; zp_joy_pressed = bits that are 1 now and were 0 at the last call;
//      A = zp_joy (Z set when nothing is pressed)
// Uses: A
// Cost: 28 raster cycles to input_read_end (measured, every pass: tests/engine/input, no DMA,
//       no IRQ inside), + rts 6 + the caller's jsr 6 = 40
// TIMING: constant path, no branches, no indexed addressing: 28 cycles, locked in
// tests/engine/input/budget.json.
input_read:
        lda zp_joy                      // 3  the stick at the last call
        eor #$ff                        // 2  1 = was up
        sta zp_joy_pressed              // 3  scratch until the final store
        lda INPUT_CIA1_PRA              // 4  one read: both outputs come from the same sample
        eor #$ff                        // 2  active low -> active high
        and #JOY_MASK                   // 2  bits 5-7 are not the stick
        sta zp_joy                      // 3
        and zp_joy_pressed              // 3  down now and up before
        sta zp_joy_pressed              // 3
        lda zp_joy                      // 3  = 28
input_read_end:
        rts                             // 6
