// Swarm: the divers (design.md "Enemy behaviour", "Dive paths", "Firing", "Choosing a diver",
// "Stage 3 rules" 1-5; memory-map.md row 6). An enemy chosen by the launcher goes through
// WindUp, Dive and Return and is Parked again; up to 3 at once.
//
// DATA. diver_enemy,slot (3 slots) holds the enemy index of each diver, DIVER_FREE if none;
// zp_divers_active counts the slots in use. The enemy's state is enemy_state (ENEMY_WINDUP,
// ENEMY_DIVE, ENEMY_RETURN: bit 7 set, so the formation leaves its X alone and a hit scores the
// diving value); its position is its multiplexer entry. The rest is per enemy, indexed by the
// enemy index like enemy_state, so that one index register serves the whole step:
//   enemy_timer   WindUp: t, the frames done (0 in the launch frame)
//   enemy_seg     Dive: the segment it is in (index into path_dx / path_dy / path_steps; the
//                 mirror choice is which copy of the path the index is in)
//   enemy_left    Dive: steps left in a counted segment
//   enemy_step    Dive: steps taken (1 after the first): what the fire steps are compared with
//   enemy_fire    Dive: index into path_fire of its next fire step (PATH_FIRE_NONE: no more)
//   enemy_shots   Dive: fire steps it may still use
// RULES.
//   - diver_update runs after formation_update (this frame's home X) and before collide_update.
//   - Whoever takes a diver out of the game (a hit) calls diver_free in the same frame: its
//     slot is free at once (Stage 3 rule 5). Arriving home frees the slot here.
//   - At most 2 rng_next calls a frame, both the launcher's; no retry loop.
// AUTOPLAY: nothing differs here (a diver that is hit carries on because collide.asm doesn't
// explode it).

.const DIVER_FREE = $ff                 // diver_enemy entry: no diver (any value with bit 7 set)

// No diver: free the three slots.
// In:  nothing       Out: zp_divers_active = 0
// Uses: A, X
// Cost: a new game only. (formation_init parks the enemies themselves.)
diver_init:
        lda #DIVER_FREE
        ldx #DIVER_SLOTS - 1
!:      sta diver_enemy,x
        dex
        bpl !-
        lda #0
        sta zp_divers_active
        rts

// A diver is out of the game (hit): free its slot.
// In:  A = enemy index 0-17      Out: zp_divers_active - 1 if it was a diver. X, Y preserved
// Uses: A
// Cost: up to 35 cycles + jsr/rts (counted); only on a hit
diver_free:
        .for (var s = 0; s < DIVER_SLOTS; s++) {
                cmp diver_enemy + s
                bne !next+
                lda #DIVER_FREE
                sta diver_enemy + s
                dec zp_divers_active
                rts
!next:
        }
        rts

// The launcher's test of one enemy, X: taken if it is Parked and in one of the wave's rows; the
// first Parked enemy of any other row is remembered in case there is none.
.macro DiverCandidate(found) {
        lda enemy_state,x               // 4
        cmp #ENEMY_PARKED               // 2
        bne !no+                        // 3 / 2
        ldy enemy_row,x
        lda diver_row_bit,y
        and zp_tmp1                     // the wave's rows
        bne found
        bit zp_tmp2                     // not one of them: the fallback, if it is the first
        bpl !no+
        stx zp_tmp2
!no:
}

// The divers' frame: the launcher (in Play only), then each diver by its state.
// In:  zp_game_state, zp_game_frame, zp_pattern, zp_loop, formation_home_x_lo/hi (this frame's)
// Out: the divers' multiplexer entries, enemy shots spawned, zp_launch_timer, zp_divers_active
// Uses: A, X, Y, zp_tmp0-2
// Cost: to diver_update_end, CPU cycles counted: 31 with no diver and no launch due; a diver
//       winding up about 95, one path step about 105 (+ about 150 on a fire step that fires),
//       returning about 120; a launch about 190 + 16 an enemy scanned (up to 18).
//       Measured (raster cycles, IRQs excluded): tests/games/swarm/stage3_costs.txt, the AUTOPLAY
//       build (3 divers, 2 steps every other frame) and the launcher's longest scan on the game
//       build. Budget 1,350 (row 6). It starts in the top border and runs into the first enemy row
diver_update:
        ldx zp_loop                     // 3   one test a frame: do the divers take 2 path steps?
        ldy #0                          // 2
        lda zp_game_frame               // 3
        and diver_extra_mask,x          // 4
        cmp diver_extra_cmp,x           // 4
        bne !+                          // 3 / 2
        dey                             // 2   $FF: yes
!:      sty diver_two                   // 4

        // The launcher. The timer counts down in Play only and stops at 0; at 0 it tries every
        // frame until it can launch.
        lda zp_game_state               // 3
        bne !slots+                     // 3 / 2
        lda zp_launch_timer             // 3
        beq !try+
        dec zp_launch_timer             // 5
        bne !slots+                     // 3
!try:   jsr diver_launch

!slots: .for (var s = 0; s < DIVER_SLOTS; s++) {
                ldx diver_enemy + s             // 4
                bmi !next+                      // 3 / 2   free
                jsr diver_one                   // 6 + the diver + 6
                lda enemy_state,x               // 4
                bmi !next+                      // 3 / 2   still WindUp, Dive or Return
                lda #DIVER_FREE                 // home: Parked again
                sta diver_enemy + s
                dec zp_divers_active
!next:
        }
diver_update_end:
        rts

// The launch timer is at 0: launch a diver if fewer than the wave's maximum are out and an enemy
// is Parked, and reload the timer; otherwise leave it at 0 (diver_update tries again next frame).
// The pick: r in 0-17, then the first Parked enemy of the wave's rows at index r, r + 1, ...
// wrapping at 18; if those rows have none Parked, the first Parked enemy of any row on the way.
// In:  zp_pattern, zp_loop, zp_divers_active, zp_enemies_alive
// Out: the enemy in WindUp with t = 0 and in a diver slot, zp_divers_active + 1, zp_launch_timer
// Uses: A, X, Y, zp_tmp0-2. At most 2 rng_next calls
// Cost: 31 cycles when the maximum are out; a launch about 190 + 15-16 an enemy scanned before
//       the one taken (counted). The longest scan, one survivor 17 places on, is measured on the
//       game build: tests/games/swarm/stage3_costs.txt
diver_launch:
        lda zp_pattern
        asl
        asl
        ora zp_loop
        tay
        lda zp_divers_active
        cmp wave_max_divers,y
        bcc !+
        rts                             // the wave's maximum are out
!:
        jsr rng_next                    // r in 0-17: 5 bits, at most two draws ...
        and #31
        cmp #ENEMY_COUNT
        bcc !r+
        jsr rng_next
        and #31
        cmp #ENEMY_COUNT
        bcc !r+
        sbc #ENEMY_COUNT                // ... then 18-31 becomes 0-13: no third call (C is set)
!r:     tax
        sta zp_tmp0                     // r: where the scan started
        ldy zp_pattern
        lda wave_rows,y
        sta zp_tmp1
        lda #$ff
        sta zp_tmp2                     // no fallback yet
!up:    DiverCandidate(!found+)         // enemies r .. 17: 15 an enemy that isn't Parked
        inx                             // 2
        cpx #ENEMY_COUNT                // 2
        bne !up-                        // 3
        ldx #0
        cpx zp_tmp0
        beq !last+
!low:   DiverCandidate(!found+)         // then 0 .. r - 1: 16 an enemy
        inx
        cpx zp_tmp0
        bne !low-
!last:  ldx zp_tmp2                     // none in the wave's rows: any Parked enemy
        bmi !none+                      // nothing is Parked: try again next frame
!found: ldy #DIVER_SLOTS - 1
!slot:  lda diver_enemy,y
        bmi !take+
        dey
        bpl !slot-
        bmi !none+                      // no free slot (can't happen: fewer than the maximum are out)
!take:  txa
        sta diver_enemy,y
        inc zp_divers_active
        lda #ENEMY_WINDUP               // frame t = 0 of its WindUp is this frame: the slot code
        sta enemy_state,x               // below gives it the wobble and the flash
        lda #0
        sta enemy_timer,x
        lda zp_pattern                  // the next launch: the wave's interval, halved (rounded
        asl                             // down) with 4 or fewer enemies alive
        asl
        ora zp_loop
        tay
        lda wave_interval,y
        ldy zp_enemies_alive
        cpy #LAUNCH_HALVE_ALIVE + 1
        bcs !+
        lsr
!:      sta zp_launch_timer
!none:  rts

// One diver's frame, by its state.
// In:  X = enemy index (state WindUp, Dive or Return)    Out: X preserved
// Uses: A, Y, zp_tmp0-1
// Cost: see diver_update
diver_one:
        lda enemy_state,x               // 4
        cmp #ENEMY_DIVE                 // 2
        beq diver_dive                  // 3
        bcs !+
        jmp diver_windup
!:      jmp diver_return

        // Dive: one path step, or two in the frames diver_update picked (a dive that ends in
        // the first doesn't take the second).
diver_dive:
        bit diver_two                   // 4
        bpl diver_step                  // 3 / 2
        jsr diver_step
        lda enemy_state,x
        cmp #ENEMY_DIVE
        beq diver_step
        rts

// One path step: X + dx (clamped to 0-344), Y + dy; the fire step; then the segment's end: the
// next segment, Return after the last, or the wrap when a steps = 0 segment has reached X 0 or 344.
// In:  X = enemy index (state Dive)       Out: X preserved
// Uses: A, Y, zp_tmp0 (eshot_spawn)
// Cost: 96-112 cycles + jsr/rts by the direction (counted); + about 150 when a shot is fired
diver_step:
        ldy enemy_seg,x                 // 4
        lda path_dx,y                   // 4
        beq !xdone+                     // 2 / 3
        bmi !left+                      // 2 / 3
        clc                             // 2   right
        adc mux_x_lo + SPR_ENEMY,x      // 4
        sta mux_x_lo + SPR_ENEMY,x      // 5
        bcc !+                          // 3 / 2
        inc mux_x_hi + SPR_ENEMY,x
!:      lda mux_x_hi + SPR_ENEMY,x      // 4
        beq !xdone+                     // 3 / 2
        lda mux_x_lo + SPR_ENEMY,x      // 4
        cmp #<(DIVER_X_MAX + 1)         // 2
        bcc !xdone+                     // 3 / 2
        lda #<DIVER_X_MAX               // past 344: clamped
        sta mux_x_lo + SPR_ENEMY,x
        bne !xdone+                     // always
!left:  clc                             // dx is - 1 or - 2 as $FF or $FE: C = 1 means no borrow
        adc mux_x_lo + SPR_ENEMY,x
        sta mux_x_lo + SPR_ENEMY,x
        bcs !xdone+
        dec mux_x_hi + SPR_ENEMY,x
        bpl !xdone+
        lda #0                          // below 0: clamped
        sta mux_x_lo + SPR_ENEMY,x
        sta mux_x_hi + SPR_ENEMY,x
!xdone: lda mux_y + SPR_ENEMY,x         // 4
        clc                             // 2
        adc path_dy,y                   // 4
        sta mux_y + SPR_ENEMY,x         // 5
        inc enemy_step,x                // 7
        ldy enemy_fire,x                // 4   a fire step? Straight after taking it, so a
        lda enemy_step,x                // 4   2-step frame can't skip one
        cmp path_fire,y                 // 4
        bne !nofire+                    // 3 / 2
        inc enemy_fire,x                // used, whether it fires or not: a fire step that
        dec enemy_shots,x               // can't fire is lost
        bne !+
        lda #PATH_FIRE_NONE             // that was this dive's last shot
        sta enemy_fire,x
!:      jsr eshot_spawn                 // fires if in Play, on screen and a slot is free
!nofire:
        ldy enemy_seg,x                 // 4
        lda path_steps,y                // 4
        beq !edge+                      // 2 / 3   an until-the-edge segment
        dec enemy_left,x                // 7
        bne !done+                      // 3 / 2
        iny                             // the next segment
        tya
        sta enemy_seg,x
        lda path_steps,y
        cmp #PATH_END_RETURN
        beq !return+
        sta enemy_left,x
!done:  rts
!return:
        lda #ENEMY_RETURN               // the path's end: Return from here, from the next frame
        sta enemy_state,x
        rts
!edge:  lda mux_x_hi + SPR_ENEMY,x      // X 0 or 344?
        bne !high+
        lda mux_x_lo + SPR_ENEMY,x
        bne !done-
        beq !wrap+                      // always
!high:  lda mux_x_lo + SPR_ENEMY,x
        cmp #<DIVER_X_MAX
        bne !done-
!wrap:  ldy enemy_col,x                 // off screen: to (this frame's home X, 30), under the
        lda formation_home_x_lo,y       // top border, in Return
        sta mux_x_lo + SPR_ENEMY,x
        lda formation_home_x_hi,y
        sta mux_x_hi + SPR_ENEMY,x
        lda #DIVER_WRAP_Y
        sta mux_y + SPR_ENEMY,x
        bne !return-                    // always
.errorif DIVER_X_MIN != 0 || DIVER_X_MAX < 256 || DIVER_X_MAX > 509, "diver_step's clamps: 0 on the left, a 9-bit value above 255 on the right"

        // WindUp, frame t (0 in the launch frame): home X + 1 when t mod 4 is 0 or 1, - 1 when 2
        // or 3; white when t mod 8 is 0-3, its own colour when 4-7. Frame W starts the dive.
diver_windup:
        lda enemy_timer,x               // 4
        ldy zp_loop                     // 3
        cmp windup_frames,y             // 4
        bcs !start+                     // 2
        inc enemy_timer,x               // 7
        sta zp_tmp0                     // 3
        ldy enemy_row,x                 // 4
        and #4                          // 2
        beq !white+                     // 2 / 3
        lda colour_table + COL_ENEMY_A,y        // 4
        jmp !col+                       // 3
!white: lda colour_table + COL_WINDUP_FLASH
!col:   sta mux_col + SPR_ENEMY,x       // 5
        ldy enemy_col,x                 // 4
        lda zp_tmp0                     // 3
        and #2                          // 2
        bne !minus+                     // 2 / 3
        lda formation_home_x_lo,y       // 4
        clc
        adc #1
        sta mux_x_lo + SPR_ENEMY,x
        lda formation_home_x_hi,y
        adc #0
        sta mux_x_hi + SPR_ENEMY,x
        rts
!minus: lda formation_home_x_lo,y
        sec
        sbc #1
        sta mux_x_lo + SPR_ENEMY,x
        lda formation_home_x_hi,y
        sbc #0
        sta mux_x_hi + SPR_ENEMY,x
        rts

        // Frame W: from (this frame's home X, the row's Y), in its own colour, mirrored if the
        // player's X is less than its own (the player's X as it stands, alive or dead). Then
        // step 1 in this same frame.
!start: ldy enemy_row,x
        lda colour_table + COL_ENEMY_A,y
        sta mux_col + SPR_ENEMY,x
        lda path_fire_first,y
        sta enemy_fire,x
        tya
        asl
        sta zp_tmp0                     // row * 2: the path's unmirrored copy
        ldy zp_pattern
        lda wave_shots,y                // shots this dive: the pattern's at loop 0, + 1 a loop
        clc                             // (a path with fewer fire steps runs out of them first)
        adc zp_loop
        sta enemy_shots,x
        ldy enemy_col,x
        lda formation_home_x_lo,y
        sta mux_x_lo + SPR_ENEMY,x
        lda formation_home_x_hi,y
        sta mux_x_hi + SPR_ENEMY,x
        lda zp_player_x_lo              // C = 1: player X >= home X, the path as authored
        cmp formation_home_x_lo,y
        lda zp_player_x_hi
        sbc formation_home_x_hi,y
        ldy zp_tmp0
        bcs !+
        iny                             // the mirrored copy
!:      lda path_first,y
        sta enemy_seg,x
        tay
        lda path_steps,y
        sta enemy_left,x
        lda #0
        sta enemy_step,x
        lda #ENEMY_DIVE
        sta enemy_state,x
        jmp diver_dive                  // step 1 in this same frame

// Return: X toward this frame's home X by at most 2, Y toward the row's Y by at most 2; when
// both match, Parked in this frame (enemy_park; diver_update then frees the slot).
// In:  X = enemy index (state Return)     Out: X preserved
// Uses: A, Y, zp_tmp0-1
// Cost: about 110 cycles + jsr/rts (counted); + enemy_park's 74 on arrival
diver_return:
        lda #0
        sta zp_tmp1                     // axes still short of home after this frame
        ldy enemy_col,x
        sec                             // d = home X - X: 9 bits and a sign
        lda formation_home_x_lo,y
        sbc mux_x_lo + SPR_ENEMY,x
        sta zp_tmp0
        lda formation_home_x_hi,y
        sbc mux_x_hi + SPR_ENEMY,x
        bmi !xleft+
        bne !xfar+                      // d >= 256
        lda zp_tmp0
        beq !xdone+                     // there
        cmp #DIVER_RETURN_SPEED + 1
        bcc !xadd+                      // 1 or 2 away: arrives
!xfar:  inc zp_tmp1
        lda #DIVER_RETURN_SPEED
!xadd:  clc
        adc mux_x_lo + SPR_ENEMY,x
        sta mux_x_lo + SPR_ENEMY,x
        bcc !xdone+
        inc mux_x_hi + SPR_ENEMY,x
        bcs !xdone+                     // always
!xleft: cmp #$ff
        bne !xlfar+                     // d < -256
        lda zp_tmp0
        cmp #256 - DIVER_RETURN_SPEED
        bcs !xsub+                      // - 1 or - 2 away: arrives (A = d)
!xlfar: inc zp_tmp1
        lda #256 - DIVER_RETURN_SPEED
!xsub:  clc                             // X + d, d negative: C = 0 after it means a borrow
        adc mux_x_lo + SPR_ENEMY,x
        sta mux_x_lo + SPR_ENEMY,x
        bcs !xdone+
        dec mux_x_hi + SPR_ENEMY,x
!xdone: ldy enemy_row,x
        lda formation_row_y,y
        sec
        sbc mux_y + SPR_ENEMY,x         // home Y - Y: C = 1 when home is below or level
        beq !ydone+
        bcc !yup+
        cmp #DIVER_RETURN_SPEED + 1
        bcc !yadd+                      // 1 or 2 above home: arrives
        inc zp_tmp1
        lda #DIVER_RETURN_SPEED
        bne !yadd+                      // always
!yup:   cmp #256 - DIVER_RETURN_SPEED
        bcs !yadd+                      // 1 or 2 below home: arrives (A = the difference)
        inc zp_tmp1
        lda #256 - DIVER_RETURN_SPEED
!yadd:  clc
        adc mux_y + SPR_ENEMY,x
        sta mux_y + SPR_ENEMY,x
!ydone: lda zp_tmp1
        bne !out+
        jmp enemy_park                  // X preserved. Home position, colour, shape, state Parked
!out:   rts

// The diver slots: the enemy index of each diver, DIVER_FREE = none.
diver_enemy:    .fill DIVER_SLOTS, DIVER_FREE
diver_two:      .byte 0                 // bit 7: the divers take 2 path steps this frame
// Per-enemy dive data, indexed by enemy index 0-17 (see the top of the file).
enemy_seg:      .fill ENEMY_COUNT, 0
enemy_left:     .fill ENEMY_COUNT, 0
enemy_step:     .fill ENEMY_COUNT, 0
enemy_fire:     .fill ENEMY_COUNT, PATH_FIRE_NONE
enemy_shots:    .fill ENEMY_COUNT, 0
