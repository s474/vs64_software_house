// multiplexer spike: zero page.

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

// Spike (main loop)
.label zp_spike_frame   = $10   // zp_irq_frame at the start of this frame's work
.label zp_spike_idle_lo = $11   // idle-loop iterations this frame
.label zp_spike_idle_hi = $12
.label zp_spike_acc     = $13   // offset accumulator

// Free-CPU minima (engine/README.md#multiplexer-spike-free-cpu-labels): 2 bytes each, little-endian,
// $FFFF at start. In zero page so the class-indexed compare costs no more than an absolute one.
.label zp_spike_idle_min     = $14                      // 4 bytes: normal, stress
.label spike_idle_min_normal = zp_spike_idle_min        // fewest idle iterations in a non-stress frame
.label spike_idle_min_stress = zp_spike_idle_min + 2    // fewest in a stress frame
