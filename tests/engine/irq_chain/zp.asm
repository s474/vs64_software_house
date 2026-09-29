// irq_chain spike: zero page.

// Engine (engine/README.md#zero-page)
.label zp_irq_idx   = $0a   // IRQ: current chain entry
.label zp_irq_frame = $0b   // shared: IRQ +1 at entry 0, main loop reads

// Spike
.label zp_spike_jit = $0c   // main loop: 3-cycle `bit` target in the jitter loop (value unused)
.label zp_spike_lfsr = $0d  // main loop: LFSR that varies the jitter loop's length
