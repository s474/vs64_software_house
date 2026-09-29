// png2sprites end-to-end test: sprites converted from demo.hires.png and demo.mc.png by
// tools/png2sprites (via make) are loaded with LoadBinary and shown on the real VIC-II.
// Sprites 0-1: hires ring and arrow. Sprites 2-4: multicolour blobs. All doubled in size.
// Build: make GAME=spr_png SRC_DIR=tests/tools/png2sprites/src

#import "build/spr_png/demo.mc.inc"     // DEMO_MC_COUNT / _MC1 / _MC2 constants
#import "build/spr_png/demo.hires.inc"  // DEMO_HIRES_COUNT

.const SCREEN   = $0400
.const VIC      = $d000

BasicUpstart2(start)

start:
        sei
        lda #0
        sta $d020
        sta $d021
        // sprite pointers: data at $2000 => block $80
        ldx #DEMO_HIRES_COUNT + DEMO_MC_COUNT - 1
!p:     txa
        clc
        adc #$80
        sta SCREEN + $3f8,x
        dex
        bpl !p-

        // colours: hires from the .col file, multicolour individual from its .col
        ldx #DEMO_HIRES_COUNT - 1
!c:     lda hires_col,x
        sta VIC + $27,x
        dex
        bpl !c-
        ldx #DEMO_MC_COUNT - 1
!c2:    lda mc_col,x
        sta VIC + $27 + DEMO_HIRES_COUNT,x
        dex
        bpl !c2-
        lda #DEMO_MC_MC1
        sta VIC + $25
        lda #DEMO_MC_MC2
        sta VIC + $26

        // positions: one row, spaced 56 apart
        ldx #0
        ldy #0
!x:     lda xpos,x
        sta VIC,y
        lda #120
        sta VIC + 1,y
        iny
        iny
        inx
        cpx #5
        bne !x-

        lda #%00011100          // sprites 2-4 multicolour
        sta VIC + $1c
        lda #%00011111
        sta VIC + $17           // double height
        sta VIC + $1d           // double width
        sta VIC + $15           // enable
        jmp *

xpos:   .byte 50, 110, 170, 210, 250

hires_col: .import binary "build/spr_png/demo.hires.col"
mc_col:    .import binary "build/spr_png/demo.mc.col"

* = $2000 "Sprites"
        .import binary "build/spr_png/demo.hires.bin"
        .import binary "build/spr_png/demo.mc.bin"
