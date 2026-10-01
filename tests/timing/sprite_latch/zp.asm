// sprite_latch probe: zero page.

// Engine (engine/README.md#zero-page): the probe uses engine/irq.asm for its stable raster.
.label zp_irq_idx   = $0a   // IRQ: current chain entry
.label zp_irq_frame = $0b   // shared: IRQ +1 at entry 0 (unused here)
