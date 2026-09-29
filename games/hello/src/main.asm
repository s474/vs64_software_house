// hello — M0 smoke test.
// Raster IRQ splits the border: red band from line $80 to $b0, light blue elsewhere.
// Proves the toolchain end to end: assemble, BASIC autostart, IRQ setup, VICE run.

.const BORDER    = $d020
.const RASTER    = $d012
.const CTRL1     = $d011
.const IRQ_STAT  = $d019
.const IRQ_MASK  = $d01a
.const CIA1_ICR  = $dc0d
.const CIA2_ICR  = $dd0d

.const BAND_TOP    = $80
.const BAND_BOTTOM = $b0

BasicUpstart2(start)

start:
        sei
        lda #$7f                // disable CIA timer IRQs/NMIs
        sta CIA1_ICR
        sta CIA2_ICR
        lda CIA1_ICR            // ack anything pending
        lda CIA2_ICR

        lda #$35                // RAM everywhere except I/O; we own the vectors
        sta $01

        lda #<nmi_rti           // RESTORE triggers an NMI; with the KERNAL out it must land somewhere
        sta $fffa
        lda #>nmi_rti
        sta $fffb

        lda #<irq_top
        sta $fffe
        lda #>irq_top
        sta $ffff

        lda #BAND_TOP
        sta RASTER
        lda CTRL1
        and #$7f                // raster compare bit 8 = 0
        sta CTRL1

        lda #$01                // enable raster IRQ
        sta IRQ_MASK
        asl IRQ_STAT            // ack any pending VIC IRQ
        cli

        jmp *                   // all work happens in the IRQs

nmi_rti:
        rti

irq_top:
        pha
        lda #RED
        sta BORDER
        lda #<irq_bottom
        sta $fffe
        lda #>irq_bottom
        sta $ffff
        lda #BAND_BOTTOM
        sta RASTER
        asl IRQ_STAT
        pla
        rti

irq_bottom:
        pha
        lda #LIGHT_BLUE
        sta BORDER
        lda #<irq_top
        sta $fffe
        lda #>irq_top
        sta $ffff
        lda #BAND_TOP
        sta RASTER
        asl IRQ_STAT
        pla
        rti
