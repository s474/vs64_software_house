// multiplexer_edge probe: zero page.

// Scratch (main loop only; mux_update uses zp_tmp0-zp_tmp3)
.label zp_tmp0      = $02
.label zp_tmp1      = $03
.label zp_tmp2      = $04
.label zp_tmp3      = $05

// Engine (engine/README.md#zero-page)
.label zp_irq_idx   = $0a   // IRQ: current chain entry
.label zp_irq_frame = $0b   // shared: IRQ +1 at entry 0, main loop reads
.label zp_mux_front = $0c   // shared: IRQ writes on swap, main reads while ready = 0
.label zp_mux_ready = $0d   // shared: main sets 1, IRQ clears on swap
.label zp_mux_slot  = $0e   // IRQ: next slot the zone IRQ writes
.label zp_mux_end   = $0f   // IRQ: end of the front buffer

// Probe (main loop only)
.label zp_edge_lfsr  = $10  // LFSR that varies the idle loop's length (IRQ jitter generator)
.label zp_edge_jit   = $11  // 3-cycle `bit` target in the idle loop (value unused)
.label zp_edge_frame = $12  // zp_irq_frame when this frame's work started
