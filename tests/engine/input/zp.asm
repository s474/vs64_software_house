// input spike: zero page. Same addresses as Swarm's (docs/games/swarm/memory-map.md#zero-page).

// Engine
.label zp_tmp0        = $02   // main loop scratch (the spike's display code)
.label zp_irq_idx     = $0a   // IRQ: current chain entry
.label zp_irq_frame   = $0b   // shared: IRQ +1 at entry 0, main loop reads
.label zp_joy         = $10   // main loop (engine/input.asm): the stick this frame
.label zp_joy_pressed = $11   // main loop (engine/input.asm): newly pressed this frame
