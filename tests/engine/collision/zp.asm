// collision spike: zero page. The engine's addresses are Swarm's (docs/games/swarm/memory-map.md#zero-page).
// engine/collision.asm itself uses none.

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

// Spike (main loop only)
.label zp_spike_frame = $10 // zp_irq_frame at the start of this frame's work
.label zp_ref_lo      = $11 // reference test: lowest target of the scan - 1
.label zp_ra_top      = $14 // reference test: A's box, first line
.label zp_ra_bot      = $15 // reference test: A's box, last line + 1 (0 for a hidden A)
.label zp_ra_l        = $16 // reference test: A's box, first and last column (2 bytes each)
.label zp_ra_r        = $18
.label zp_rb          = $1a // reference test: one edge of B's box (2 bytes)
.label zp_ref_hits    = $1c // reference test: the hit array the module's result is in (2 bytes)
.label zp_sc_x        = $1e // scene harness: the target being tested
