// collision spike (M4 stage 2): proves engine/collision.asm against its contract, engine/collision.md.
//
// The multiplexer with 24 sprites laid out as Swarm: 0 player, 1-3 enemy shots, 4-5 player shots,
// 6-23 enemies (6 + row * 6 + column; rows at Y 56 / 96 / 136, X = 34 + fx + 36 * column). Each
// sprite's shape IS its hit box (design.md#hit-boxes), so what overlaps on screen is what hits.
// A sprite that hits or is hit is drawn WHITE in the next frame, and the border is RED for that
// frame (set in the $FB entry).
//
// Three phases, cycling every 256 frames (spike_t):
//   M  frames 0-223: moving. The formation drifts 1 px a frame; enemies 18, 20 and 22 are
//      "divers" (bouncing in X, falling 2-3 lines a frame from Y 30 to 221 and wrapping); the
//      player sweeps 24-318 at 3 px a frame; the two player shots climb 8 lines a frame from the
//      player's X; each enemy shot falls 2 lines a frame from its diver.
//   W  frames 224-239: the contract's worst mix of 42 tests, static (spike_w_*): shot 4 in row
//      0's Y band (6 full tests, 12 rejects), shot 5 in row 1's with enemies 18, 20, 22 in it
//      too (9 full, 9 rejects), the player against 3 enemy shots and enemies 19, 21, 23 at the
//      bottom (6 full). Every full test but four misses on the longest path; the four hits are
//      shot 4 on enemy 6 (touching by one pixel), shot 5 on enemy 12, enemy shot 1 and enemy 19
//      on the player.
//
//   B  frames 240-255: phase W's layout stays on screen, with no tests (the hit arrays keep
//      phase W's results), so the frame's work ends early and the border passes below run
//      with nothing else between line 252 and the next frame's tick. (With the tests and the reference test in the frame
//      the work ends near line 290: measured.)
//
// Each frame of phases M and W (main loop):
//   spike_move                      positions (all 24 written afresh every frame)
//   spike_collide -> spike_collide_end   the game's 42 tests through the module:
//                                   2 x (collision_begin + collision_range 23..6, with
//                                   collision_next after each hit), the player: collision_begin
//                                   + collision_range 3..1, collision_begin + 3 x collision_one
//                                   on spike_ptgt. A hit is recorded with two stores (9 cycles,
//                                   inside the span): spike_hits0 / spike_hits1 / spike_hitsp.
//   spike_colour, mux_update
//   spike_ref                       the spike's own reference test of the same 42 pairs, slow and
//                                   simple (edges compared, 16-bit X, from spike_boxes: the box
//                                   numbers as typed, not ColPair's bytes): a result that differs
//                                   from the module's adds 1 to spike_mismatch_count
//   spike_frame_done                check.py reads the positions and the hit arrays here
// Each frame of phase B: spike_move, mux_update, spike_frame_done, then, after the $FB entry and
//   only if the raster is still on lines 251-255 (else spike_border_skips + 1), the border passes:
//     spike_mix    -> spike_mix_end      the 42 tests of phase W again (the same macro as
//                                        spike_collide, hits into scratch arrays): the worst mix
//                                        with no DMA
//   then the 18 enemies and sprite 4 are overwritten with a fixed layout (spike_move rewrites
//   them next frame) for the four single paths:
//     spike_begin  -> spike_begin_end    jsr collision_begin .. back (the whole call)
//     spike_reject -> spike_reject_end   jsr collision_range, 18 targets rejected on Y
//     spike_full   -> spike_full_end     jsr collision_range, 18 targets pass Y, miss on X (longest path)
//     spike_one    -> spike_one_end      jsr collision_one, a hit
//   From line 252 into the first lines of the next frame: no badline, no sprite DMA (MUX_Y_MAX = 221, shown to line 242), no IRQ.
//   A pass with the wrong outcome adds 1 to spike_border_bad.
//
// Scene harness (tests/engine/collision/check.py): with spike_cmd != 0 at spike_frame the main
// loop runs spike_scene instead of the demo: collision_begin(spike_sc_a, spike_sc_pair),
// collision_one on every target 23..0, then collision_range(spike_sc_last, spike_sc_first) and
// collision_next until C = 0, on whatever positions the script wrote into the multiplexer's
// arrays. Results: spike_sc_flags, spike_sc_n, spike_sc_list, spike_sc_one.
//
// Chain: mux_irq_top, and one fixed entry at $FB.
//
// Build:  make GAME=collision SRC_DIR=tests/engine/collision
// Budget: make test ARGS=collision            (tests/engine/collision/budget.json)
// Model:  uv run --package budget-runner python tests/engine/collision/check.py
// Screenshot: screenshots/collision-spike.png

BasicUpstart2(start)

#import "zp.asm"

.const MUX_SCREEN = $0400
.const MUX_Y_MAX  = 221                 // Swarm's (panel line 243 - 22)

.const VIC_CTRL1      = $d011
.const VIC_RASTER     = $d012
.const VIC_BORDER     = $d020
.const VIC_BACKGROUND = $d021
.const SCREEN         = $0400
.const COLOUR_RAM     = $d800

.const SPRITE_DATA = $3000                 // the engine ends near $2100, the spike near $2a00
.const SPIKE_PTR0  = SPRITE_DATA / 64
.const SHAPE_PLAYER = SPIKE_PTR0
.const SHAPE_ENEMY  = SPIKE_PTR0 + 1
.const SHAPE_PSHOT  = SPIKE_PTR0 + 2
.const SHAPE_ESHOT  = SPIKE_PTR0 + 3

.const SPIKE_W_START = 224              // spike_t 224-239: phase W
.const SPIKE_B_START = 240              // spike_t 240-255: phase B
.const PLAYER_Y      = MUX_Y_MAX
.const ROW_STATUS    = SCREEN + 24 * 40

// Hit boxes: x0, x1, y0, y1 (docs/games/swarm/design.md#hit-boxes), typed once, used by
// col_pairs (through ColPair), the reference test's spike_boxes and the sprite shapes.
.const BOX_PLAYER = List().add(6, 17, 6, 20)
.const BOX_ENEMY  = List().add(4, 19, 3, 17)
.const BOX_PSHOT  = List().add(11, 12, 0, 7)
.const BOX_ESHOT  = List().add(11, 12, 14, 20)

.macro SpikeColPair(a, b) {
        ColPair(a.get(0), a.get(1), a.get(2), a.get(3), b.get(0), b.get(1), b.get(2), b.get(3))
}
.macro SpikeRefPair(a, b) {             // 8 bytes: ax0, ax1, ay0, ay1, bx0, bx1, by0, by1
        .byte a.get(0), a.get(1), a.get(2), a.get(3), b.get(0), b.get(1), b.get(2), b.get(3)
}
.macro SpikeShape(box) {                // a sprite whose set pixels are exactly the box
        .for (var r = 0; r < 21; r++) {
            .for (var b = 0; b < 3; b++) {
                .var v = 0
                .for (var c = 0; c < 8; c++) {
                    .var px = b * 8 + c
                    .if (r >= box.get(2) && r <= box.get(3) && px >= box.get(0) && px <= box.get(1)) .eval v = v | ($80 >> c)
                }
                .byte v
            }
        }
        .byte 0
}

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

// One of the game's scans: A against targets last..first, every hit recorded.
.macro SpikeScan(a, pair, last, first, hits, hitsp) {
        ldx #a
        ldy #pair
        jsr collision_begin
        ldx #last
        lda #first
        jsr collision_range
        bcc done
hit:    lda #1
        sta hits,x                      // the target
        sta hitsp + a                   // and A
        jsr collision_next
        bcs hit
done:
}

// The game's 42 tests: two player shots against the 18 enemies, the player against the 3 enemy
// shots and the 3 divers in spike_ptgt. Hits go to the three arrays given.
.macro SpikeTests(hits0, hits1, hitsp) {
        SpikeScan(4, 0, 23, 6, hits0, hitsp)    // player shot 0 against the 18 enemies
        SpikeScan(5, 0, 23, 6, hits1, hitsp)    // player shot 1
        SpikeScan(0, 1, 3, 1, hitsp, hitsp)     // the player against the 3 enemy shots
        ldx #0                                  // the player against the 3 divers
        ldy #2
        jsr collision_begin
        .for (var k = 0; k < 3; k++) {
            ldx spike_ptgt + k
            jsr collision_one
            bcc !+
            lda #1
            sta hitsp,x
            sta hitsp
!:
        }
}

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/multiplexer.asm"
#import "engine/collision.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)
        IrqNormal($fb, spike_irq_bottom)
        IrqChainEnd()

* = * "Spike"
// The game's table: pair 0 player shot against enemy, 1 player against enemy shot, 2 player
// against enemy (engine/collision.md#data-the-game-provides).
col_pairs:
        SpikeColPair(BOX_PSHOT, BOX_ENEMY)
        SpikeColPair(BOX_PLAYER, BOX_ESHOT)
        SpikeColPair(BOX_PLAYER, BOX_ENEMY)
col_pairs_end:

start:
        lda #BLACK
        sta VIC_BORDER
        sta VIC_BACKGROUND
        lda #0
        sta $d017
        sta $d01d
        sta $d01b
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
        inx
        bne !-
        SpikeText(ROW_STATUS, "COLLISION  HIT $      BAD $    OVR $")
        jsr mux_init
        ldx #MUX_COUNT - 1
!:      lda spike_shape,x
        sta mux_ptr,x
        lda spike_base_col,x
        sta mux_col,x
        lda spike_flags0,x
        sta mux_flags,x
        lda #0
        sta spike_hits0,x
        sta spike_hits1,x
        sta spike_hitsp,x
        dex
        bpl !-
        jsr spike_move                  // valid positions before the first mux_update
        jsr irq_init
        jsr irq_wait_frame

// The frame: zp_irq_frame has just ticked.
spike_main:
        lda zp_irq_frame
        sta zp_spike_frame
        lda #0
        sta spike_fb
spike_frame:
        lda spike_cmd                   // check.py's scene harness?
        beq spike_demo
spike_scene_go:
        lda #0
        sta spike_cmd
        jsr spike_scene
spike_scene_done:
        lda spike_cmd                   // check.py reads the results here and may queue another
        bne spike_scene_go
        jsr irq_wait_frame
        jmp spike_main

spike_demo:
        jsr spike_move
        lda spike_t
        cmp #SPIKE_B_START
        bcc spike_tests
        jsr mux_update                  // phase B: the static layout stays up, no tests
        jsr spike_status                // (the status row is redrawn here, where there is time)
        jmp spike_frame_done
spike_tests:
        lda #0                          // clear every hit byte the scans can set
        .for (var i = 6; i < 24; i++) {
            sta spike_hits0 + i
            sta spike_hits1 + i
        }
        .for (var i = 0; i < 6; i++) {
            sta spike_hitsp + i
            sta spike_hitsp + 18 + i
        }

// The game's 42 tests. Not a subroutine: the span is spike_collide to spike_collide_end.
spike_collide:
        SpikeTests(spike_hits0, spike_hits1, spike_hitsp)
spike_collide_end:

        jsr spike_colour
        jsr mux_update
        jsr spike_ref
spike_frame_done:
        lda zp_irq_frame                // work finished inside the frame?
        cmp zp_spike_frame
        beq spike_wait_fb
        inc spike_overrun_count         // no: count it (saturating) and start the next frame now
        bne !+
        dec spike_overrun_count
!:      jmp spike_main

// Phase B only: wait for the $FB entry, then run the border passes if the raster is still on
// lines 251-255 (it always is: a phase B frame's work is spike_move and mux_update).
spike_wait_fb:
        lda spike_t
        cmp #SPIKE_B_START
        bcc spike_tick
spike_wait_flag:
        lda spike_fb
        beq spike_wait_flag
        lda VIC_CTRL1
        bmi spike_border_skip           // line 256 or later
        lda VIC_RASTER
        cmp #$fb
        bcc spike_border_skip           // already in the next frame's top border
        jsr spike_border
        inc spike_border_runs
        bne spike_tick
        inc spike_border_runs + 1
        jmp spike_tick
spike_border_skip:
        inc spike_border_skips
        bne spike_tick
        inc spike_border_skips + 1
spike_tick:
        jsr irq_wait_frame
        jmp spike_main

// ------------------------------------------------------------------------------------------
// The five locked paths, in the lower border. First the 42 tests again on phase W's layout
// (the same macro as spike_collide, its hits into scratch arrays): the worst mix with no DMA.
// Then sprite 4 and the 18 enemies are overwritten in the multiplexer's arrays (mux_update has
// already read them; spike_move rewrites them) for the four single paths.
// In: nothing   Out: nothing   Uses: A, X, Y
// Cost: about 3,900 cycles, from line 252 into the first lines of the next frame (measured:
//       tests/engine/collision/measure.py)
spike_border:
spike_mix:
        SpikeTests(spike_bh0, spike_bh1, spike_bhp)
spike_mix_end:
        ldx #23
!loop:  lda #180                        // enemies: X 180, Y 200
        sta mux_x_lo,x
        lda #0
        sta mux_x_hi,x
        lda #200
        sta mux_y,x
        dex
        cpx #6
        bcs !loop-
        lda #100                        // sprite 4 (A): X 100, Y 100
        sta mux_x_lo + 4
        sta mux_y + 4
        lda #0
        sta mux_x_hi + 4
        ldx #4
        ldy #0
spike_begin:
        jsr collision_begin
spike_begin_end:
        ldx #23
        lda #6
spike_reject:
        jsr collision_range             // 100 + 4 - 200 = 160: 18 rejects on Y
spike_reject_end:
        bcc !+
        inc spike_border_bad
!:      ldx #23
        lda #100                        // enemies to Y 100: all pass Y. X: 255 + 111 - 199 = 167,
!loop:  sta mux_y,x                     // high byte 0, low byte below 256 - 17: the longest miss
        dex
        cpx #6
        bcs !loop-
        ldx #23
        lda #6
spike_full:
        jsr collision_range
spike_full_end:
        bcc !+
        inc spike_border_bad
!:      lda #100                        // enemy 6 to X 100: box 104-119 over the shot's 111-112
        sta mux_x_lo + 6
        ldx #6
spike_one:
        jsr collision_one
spike_one_end:
        bcs !+
        inc spike_border_bad
!:      cpx #6                          // X preserved
        beq !+
        inc spike_border_bad
!:      rts

// ------------------------------------------------------------------------------------------
// Scene harness for check.py: the module's four routines on the positions now in the arrays.
// In: spike_sc_a, spike_sc_pair, spike_sc_first, spike_sc_last
// Out: spike_sc_flags bit 0: collision_begin changed X or Y; spike_sc_one[t] bit 0: collision_one's
//      carry for target t, bit 7: it changed X; spike_sc_n, spike_sc_list: the targets
//      collision_range and collision_next returned, in order (at most 25 are stored)
// Uses: A, X, Y, zp_sc_x
spike_scene:
        lda #0
        sta spike_sc_flags
        sta spike_sc_n
        ldx spike_sc_a
        ldy spike_sc_pair
        jsr collision_begin
        cpx spike_sc_a
        bne scene_bad
        cpy spike_sc_pair
        beq scene_ones
scene_bad:
        inc spike_sc_flags
scene_ones:
        ldx #MUX_COUNT - 1
scene_one:
        stx zp_sc_x
        jsr collision_one
        lda #0
        rol                             // A = carry
        cpx zp_sc_x
        beq !+
        ora #$80
        ldx zp_sc_x
!:      sta spike_sc_one,x
        dex
        bpl scene_one
        ldx spike_sc_last
        lda spike_sc_first
        jsr collision_range
scene_hits:
        bcc scene_done
        ldy spike_sc_n
        txa
        sta spike_sc_list,y
        iny
        sty spike_sc_n
        cpy #MUX_COUNT + 1              // more hits than sprites: stop (a runaway)
        bcs scene_done
        jsr collision_next
        jmp scene_hits
scene_done:
        rts

// ------------------------------------------------------------------------------------------
// Positions for this frame: all 24 sprites, from the spike's own state. Uses A, X, Y.
spike_move:
        inc spike_t
        lda spike_t
        cmp #SPIKE_W_START
        bcc move_m
        ldx #MUX_COUNT - 1              // phase W: the static worst mix
!:      lda spike_w_xlo,x
        sta mux_x_lo,x
        lda spike_w_xhi,x
        sta mux_x_hi,x
        lda spike_w_y,x
        sta mux_y,x
        dex
        bpl !-
        lda #19
        sta spike_ptgt
        lda #21
        sta spike_ptgt + 1
        lda #23
        sta spike_ptgt + 2
        rts
move_m:
        lda #18
        sta spike_ptgt
        lda #20
        sta spike_ptgt + 1
        lda #22
        sta spike_ptgt + 2
        lda spike_fx                    // formation drift: 0 -> 96 -> 0
        clc
        adc spike_fdir
        sta spike_fx
        bne !+
        lda #1
        sta spike_fdir
!:      lda spike_fx
        cmp #96
        bne !+
        lda #$ff
        sta spike_fdir
!:      ldx #23                         // the 18 enemies, parked
move_enemy:
        lda spike_colx - 6,x
        clc
        adc spike_fx
        sta mux_x_lo,x
        lda #0
        rol
        sta mux_x_hi,x
        lda spike_rowy - 6,x
        sta mux_y,x
        dex
        cpx #6
        bcs move_enemy
        ldx #3                          // player and the three divers: X
!:      jsr spike_bounce
        dex
        bpl !-
        lda spike_mv_lo                 // player: sprite 0
        sta mux_x_lo
        lda spike_mv_hi
        sta mux_x_hi
        lda #PLAYER_Y
        sta mux_y
        .for (var k = 0; k < 3; k++) {  // divers: sprites 18, 20, 22
            lda spike_dvy + k
            clc
            adc spike_dvs + k
            cmp #MUX_Y_MAX + 1
            bcc !+
            lda #MUX_Y_MIN
!:          sta spike_dvy + k
            sta mux_y + 18 + k * 2
            lda spike_mv_lo + 1 + k
            sta mux_x_lo + 18 + k * 2
            lda spike_mv_hi + 1 + k
            sta mux_x_hi + 18 + k * 2
        }
        .for (var k = 0; k < 2; k++) {  // player shots: sprites 4, 5
            lda spike_psy + k
            sec
            sbc #8
            cmp #46
            bcs !+
            lda spike_mv_lo             // respawn at the player
            sta spike_psxl + k
            lda spike_mv_hi
            sta spike_psxh + k
            lda #213
!:          sta spike_psy + k
            sta mux_y + 4 + k
            lda spike_psxl + k
            sta mux_x_lo + 4 + k
            lda spike_psxh + k
            sta mux_x_hi + 4 + k
        }
        .for (var k = 0; k < 3; k++) {  // enemy shots: sprites 1-3, each from its diver
            lda spike_esy + k
            clc
            adc #2
            cmp #MUX_Y_MAX + 1
            bcc !+
            lda spike_mv_lo + 1 + k
            sta spike_esxl + k
            lda spike_mv_hi + 1 + k
            sta spike_esxh + k
            lda spike_dvy + k
!:          sta spike_esy + k
            sta mux_y + 1 + k
            lda spike_esxl + k
            sta mux_x_lo + 1 + k
            lda spike_esxh + k
            sta mux_x_hi + 1 + k
        }
        rts

// Move mover X one step and turn it round at 24 / 318. In: X = mover (0 player, 1-3 divers)
// Out: nothing   Uses: A (X preserved)
spike_bounce:
        lda spike_mv_dir,x
        bmi bounce_left
        lda spike_mv_lo,x
        clc
        adc spike_mv_step,x
        sta spike_mv_lo,x
        lda spike_mv_hi,x
        adc #0
        sta spike_mv_hi,x
        beq bounce_done
        lda spike_mv_lo,x
        cmp #<318
        bcc bounce_done
        lda #$80
        sta spike_mv_dir,x
bounce_done:
        rts
bounce_left:
        lda spike_mv_lo,x
        sec
        sbc spike_mv_step,x
        sta spike_mv_lo,x
        lda spike_mv_hi,x
        sbc #0
        sta spike_mv_hi,x
        bne bounce_done
        lda spike_mv_lo,x
        cmp #27                         // steps are at most 3: never below 24
        bcs bounce_done
        lda #0
        sta spike_mv_dir,x
        rts

// ------------------------------------------------------------------------------------------
// Colours for the next frame: WHITE for a sprite that hit or was hit, its own colour otherwise;
// and the border colour the $FB entry sets. Uses A, X.
spike_colour:
        ldx #MUX_COUNT - 1
colour_loop:
        lda spike_hits0,x
        ora spike_hits1,x
        ora spike_hitsp,x
        bne !+                          // 1 = WHITE
        lda spike_base_col,x
!:      sta mux_col,x
        dex
        bpl colour_loop
        lda spike_hitsp
        ora spike_hitsp + 4
        ora spike_hitsp + 5
        beq !+
        inc spike_hit_frames
        bne !red+
        inc spike_hit_frames + 1
!red:   lda #RED
!:      sta spike_border_col            // BLACK = 0
        rts

// Status row, redrawn in phase B frames only (16 frames in 256). Uses A, X.
spike_status:
        SpikeHex(spike_hit_frames + 1, ROW_STATUS + 16)
        SpikeHex(spike_hit_frames, ROW_STATUS + 18)
        SpikeHex(spike_mismatch_count, ROW_STATUS + 27)
        SpikeHex(spike_overrun_count, ROW_STATUS + 36)
        rts

// ------------------------------------------------------------------------------------------
// Reference test of the frame's 42 pairs, compared with what the module reported.
// Uses A, X, Y, zp_ref_*, zp_ra_*, zp_rb.
spike_ref:
        ldx #0                          // shot 4 against enemies 6-23
        lda #6
        ldy #23
        jsr spike_ref_scan
        ldx #1                          // shot 5
        lda #6
        ldy #23
        jsr spike_ref_scan
        ldx #2                          // player against enemy shots 1-3
        lda #1
        ldy #3
        jsr spike_ref_scan
        .for (var k = 0; k < 3; k++) {  // player against each diver
            ldx #3
            lda spike_ptgt + k
            tay
            jsr spike_ref_scan
        }
        rts

// One scan of the reference test: box edges compared one by one, X in 16 bits. No overlap if
// A's last line is above B's first, B's last above A's first, A's last column left of B's
// first, or B's last left of A's first; a hidden sprite never overlaps. A is never among
// the targets of the spike's four scans (spike_scan_a against the callers in spike_ref).
// (8-bit lines are exact here: MUX_Y_MAX + 20 <= 255.)
// In:  X = scan (0-3: spike_scan_* give A, the box row and the module's hit array),
//      A = lowest target, Y = highest target
// Out: spike_mismatch_count + 1 (saturating) for each target whose result differs
// Uses: A, X, Y, zp_ref_*, zp_ra_*, zp_rb
// Cost: about 37 cycles a target rejected on Y, 115 a target compared on X (counted)
.errorif MUX_Y_MAX + 21 > 255, "spike_ref_scan: 8-bit box lines need MUX_Y_MAX <= 234"
spike_ref_scan:
        sec
        sbc #1
        sta zp_ref_lo                   // lowest target - 1 ($FF for 0)
        sty zp_sc_x                     // the highest target, for a moment
        lda spike_scan_hits_lo,x
        sta zp_ref_hits
        lda spike_scan_hits_hi,x
        sta zp_ref_hits + 1
        lda spike_scan_a,x
        tay                             // Y = A
        lda spike_scan_box,x
        tax                             // X = offset of the pair's row in spike_boxes
        lda mux_y,y
        clc
        adc spike_boxes + 2,x
        sta zp_ra_top
        lda mux_y,y
        sec
        adc spike_boxes + 3,x
        sta zp_ra_bot                   // A's last line + 1
        lda mux_y,y
        cmp #MUX_OFF
        bne !+
        lda #0                          // a hidden A: every target's first line is "below" it
        sta zp_ra_bot
!:
        lda mux_x_lo,y
        clc
        adc spike_boxes,x
        sta zp_ra_l
        lda mux_x_hi,y
        adc #0
        sta zp_ra_l + 1
        lda mux_x_lo,y
        clc
        adc spike_boxes + 1,x
        sta zp_ra_r
        lda mux_x_hi,y
        adc #0
        sta zp_ra_r + 1
        ldy zp_sc_x
ref_loop:
        lda mux_y,y
        cmp #MUX_OFF
        beq ref_no
        adc spike_boxes + 6,x           // B's first line (C = 0 after the compare)
        cmp zp_ra_bot                   // zp_ra_bot = A's last line + 1
        bcs ref_no                      // A's last line is above it
        lda mux_y,y
        clc
        adc spike_boxes + 7,x           // B's last line
        cmp zp_ra_top
        bcc ref_no                      // above A's first
        lda mux_x_lo,y
        clc
        adc spike_boxes + 4,x           // B's first column
        sta zp_rb
        lda mux_x_hi,y
        adc #0
        sta zp_rb + 1
        lda zp_ra_r
        cmp zp_rb
        lda zp_ra_r + 1
        sbc zp_rb + 1
        bcc ref_no                      // A's last column is left of it
        lda mux_x_lo,y
        clc
        adc spike_boxes + 5,x           // B's last column
        sta zp_rb
        lda mux_x_hi,y
        adc #0
        sta zp_rb + 1
        lda zp_rb
        cmp zp_ra_l
        lda zp_rb + 1
        sbc zp_ra_l + 1
        bcc ref_no                      // left of A's first
        lda #1
        bne ref_cmp
ref_no: lda #0
ref_cmp:
        cmp (zp_ref_hits),y
        beq ref_ok
        inc spike_mismatch_count
        bne ref_ok
        dec spike_mismatch_count
ref_ok: dey
        cpy zp_ref_lo                   // zp_ref_lo = lowest target - 1
        bne ref_loop
        rts

// Chain entry 1, line $FB: next frame's border colour, and the main loop's cue for the border passes.
spike_irq_bottom:
        lda spike_border_col
        sta VIC_BORDER
        lda #1
        sta spike_fb
        IrqDone()

// ------------------------------------------------------------------------------------------
// Data
spike_boxes:                            // the reference test's copy: one 8-byte row a pair
        SpikeRefPair(BOX_PSHOT, BOX_ENEMY)
        SpikeRefPair(BOX_PLAYER, BOX_ESHOT)
        SpikeRefPair(BOX_PLAYER, BOX_ENEMY)
spike_scan_a:       .byte 4, 5, 0, 0
spike_scan_box:     .byte 0, 0, 8, 16
spike_scan_hits_lo: .byte <spike_hits0, <spike_hits1, <spike_hitsp, <spike_hitsp
spike_scan_hits_hi: .byte >spike_hits0, >spike_hits1, >spike_hitsp, >spike_hitsp

// What the module reported this frame, a byte a sprite (1 = hit):
spike_hits0:    .fill MUX_COUNT, 0      // [6-23]: enemies hit by player shot 0 (sprite 4)
spike_hits1:    .fill MUX_COUNT, 0      // [6-23]: enemies hit by player shot 1 (sprite 5)
spike_hitsp:    .fill MUX_COUNT, 0      // [1-3]: enemy shots that hit the player; [spike_ptgt]: divers
                                        // that hit the player; [0], [4], [5]: that sprite hit something
spike_bh0:      .fill MUX_COUNT, 0      // scratch: the border copy of the 42 tests writes here
spike_bh1:      .fill MUX_COUNT, 0
spike_bhp:      .fill MUX_COUNT, 0
spike_ptgt:     .byte 18, 20, 22        // the three "divers" the player is tested against this frame

spike_mismatch_count:   .byte 0         // module != reference test (saturating)
spike_overrun_count:    .byte 0         // frames whose work didn't finish before the next tick
spike_border_bad:       .byte 0         // border passes with the wrong outcome
spike_border_runs:      .word 0         // frames in which the border passes ran
spike_border_skips:     .word 0         // frames in which the work ended after line 255
spike_hit_frames:       .word 0         // frames with at least one hit
spike_border_col:       .byte 0
spike_fb:               .byte 0         // shared: the $FB entry sets 1, the main loop clears
spike_t:                .byte 0         // frame in the 256-frame cycle

// Scene harness: 5 bytes in, 50 out, each block contiguous (check.py reads and writes them whole).
spike_cmd:      .byte 0                 // != 0: run spike_scene (cleared when taken)
spike_sc_a:     .byte 0
spike_sc_pair:  .byte 0
spike_sc_first: .byte 0
spike_sc_last:  .byte 0
spike_sc_flags: .byte 0
spike_sc_n:     .byte 0
spike_sc_list:  .fill MUX_COUNT + 1, 0
spike_sc_one:   .fill MUX_COUNT, 0

// Motion state
spike_fx:       .byte 48
spike_fdir:     .byte 1
spike_mv_lo:    .byte 171, 60, <280, 150       // X of the player and the three divers
spike_mv_hi:    .byte 0, 0, >280, 0
spike_mv_dir:   .byte 0, 0, $80, 0
spike_mv_step:  .byte 3, 1, 2, 1
spike_dvy:      .byte 136, 100, 180            // divers' Y and lines a frame
spike_dvs:      .byte 2, 3, 2
spike_psy:      .byte 213, 133                 // player shots
spike_psxl:     .byte 171, 120
spike_psxh:     .byte 0, 0
spike_esy:      .byte 150, 180, 210            // enemy shots
spike_esxl:     .byte 60, 200, 150
spike_esxh:     .byte 0, 0, 0

spike_colx:     .fill 18, 34 + 36 * mod(i, 6)   // [sprite - 6]: column X before the drift (34-214)
spike_rowy:     .fill 18, 56 + 40 * floor(i / 6)

// Phase W: the contract's worst mix (engine/collision.md#cycle-budget), by sprite.
.const W_X = List().add(160, 160, 200, 230, 74, 74,   82, 118, 154, 190, 226, 262,   82, 118, 154, 190, 226, 262,   100, 150, 172, 200, 300, 240)
.const W_Y = List().add(221, 210, 214, 218, 60, 100,  56, 56, 56, 56, 56, 56,        96, 96, 96, 96, 96, 96,        90, 210, 100, 214, 104, 218)
spike_w_xlo:    .fill MUX_COUNT, <W_X.get(i)
spike_w_xhi:    .fill MUX_COUNT, >W_X.get(i)
spike_w_y:      .fill MUX_COUNT, W_Y.get(i)

spike_shape:    .byte SHAPE_PLAYER, SHAPE_ESHOT, SHAPE_ESHOT, SHAPE_ESHOT, SHAPE_PSHOT, SHAPE_PSHOT
                .fill 18, SHAPE_ENEMY
spike_base_col: .byte LIGHT_BLUE, YELLOW, YELLOW, YELLOW, LIGHT_GREEN, LIGHT_GREEN
                .fill 6, GREEN
                .fill 6, PURPLE
                .fill 6, ORANGE
spike_flags0:   .byte $80, $80, $80, $80        // player and enemy shots pinned, as Swarm
                .fill 20, 0
spike_hex_chars:
        .text "0123456789ABCDEF"

.errorif * > SPRITE_DATA, "spike code runs into the sprite data"

* = SPRITE_DATA "Sprites"
        SpikeShape(BOX_PLAYER)
        SpikeShape(BOX_ENEMY)
        SpikeShape(BOX_PSHOT)
        SpikeShape(BOX_ESHOT)
