// rng spike: zero page. Same addresses as Swarm's (docs/games/swarm/memory-map.md#zero-page).

// Engine
.label zp_irq_idx   = $0a   // IRQ: current chain entry
.label zp_irq_frame = $0b   // shared: IRQ +1 at entry 0, main loop reads
.label zp_rng_lo    = $12   // main loop (engine/rng.asm): generator state
.label zp_rng_hi    = $13

// Spike (main loop only)
.label zp_spike_blk = $18   // calls left in the current block of 256 (0 = 256)
.label zp_spike_or  = $19   // zero-seed test: OR of (output ^ first output)
.label zp_spike_1st = $1a   // zero-seed test: first output
