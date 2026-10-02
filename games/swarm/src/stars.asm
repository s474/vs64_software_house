// Swarm: the star field (design.md#screen-layout). 48 stars at fixed cells from the star table
// (tables.asm), drawn once at init and never redrawn. The twinkle: each frame one star, in turn,
// steps its colour through the four COL_STAR_* colours, so each star changes every 48 frames.
// The stars are never in a text cell (the band rule, checked where the table is generated), so
// the colour write can't land on a letter and texts are written without looking at the stars.

// Draw the 48 stars and give each its starting colour step (star number mod 4, so the sky isn't
// all one brightness at the start).
// In:  nothing       Out: zp_star_idx = STAR_COUNT - 1 (the first stars_update twinkles star 0)
// Uses: A, X, Y, zp_star_ptr
// Cost: init only
stars_init:
        ldx #STAR_COUNT - 1
        stx zp_star_idx
!loop:  lda star_lo,x
        sta zp_star_ptr
        lda star_hi,x
        clc
        adc #>SCREEN
        sta zp_star_ptr + 1
        ldy #0
        lda star_glyph,x
        sta (zp_star_ptr),y             // the glyph, a play-area code (0-63)
        lda zp_star_ptr + 1
        clc
        adc #>(COLOUR_RAM - SCREEN)
        sta zp_star_ptr + 1
        txa
        and #3
        sta stars_phase,x
        tay
        lda colour_table + COL_STAR_0,y
        ldy #0
        sta (zp_star_ptr),y
        dex
        bpl !loop-
        rts

// The twinkle: step the next star's colour. One colour RAM write a frame.
// In:  nothing       Out: nothing
// Uses: A, X, Y, zp_star_ptr, zp_star_idx
// Cost: 56-57 raster cycles to stars_update_end (measured: make test ARGS=swarm, 300 passes, max
//       57; budget 60, memory-map.md row 10). Called straight after panel_update, on about lines
//       27-29 of the top border: no badline and no sprite DMA, so the cost is the CPU count and
//       depends only on the star counter. (Stage 2 part B called it last, after the collisions,
//       where it met badlines: 100-129 measured. Don't move it back.)
stars_update:
        ldx zp_star_idx                 // 3
        inx                             // 2
        cpx #STAR_COUNT                 // 2
        bcc !+                          // 3 / 2
        ldx #0                          // 2
!:      stx zp_star_idx                 // 3
        lda star_lo,x                   // 4
        sta zp_star_ptr                 // 3
        lda star_hi,x                   // 4
        ora #>COLOUR_RAM                // 2  the offset's high byte is 0-3 and $D8 has those bits clear
        sta zp_star_ptr + 1             // 3
        inc stars_phase,x               // 7
        lda stars_phase,x               // 4
        and #3                          // 2
        tay                             // 2
        lda colour_table + COL_STAR_0,y // 4
        ldy #0                          // 2
        sta (zp_star_ptr),y             // 6
stars_update_end:
        rts
.errorif (>COLOUR_RAM & 3) != 0, "stars_update ORs the cell offset into the colour RAM address"

// Each star's colour step. Only bits 0-1 are used (the byte counts up and wraps).
stars_phase:    .fill STAR_COUNT, 0
