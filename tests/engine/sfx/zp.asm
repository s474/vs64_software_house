// sfx spike: zero page. The engine's addresses are Swarm's (docs/games/swarm/memory-map.md#zero-page).
// engine/sfx.asm itself uses none.

// Scratch (main loop only: the spike's display code)
.label zp_tmp0        = $02
.label zp_tmp1        = $03
.label zp_tmp2        = $04
.label zp_tmp3        = $05

// Engine
.label zp_irq_idx     = $0a   // IRQ: current chain entry
.label zp_irq_frame   = $0b   // shared: IRQ +1 at entry 0, main loop reads
.label zp_joy         = $10   // main loop (engine/input.asm): the stick this frame
.label zp_joy_pressed = $11   // main loop (engine/input.asm): newly pressed this frame
