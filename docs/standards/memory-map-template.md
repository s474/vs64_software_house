# <Title>: memory map and raster timeline

Copy to `docs/games/<title>/memory-map.md` and keep it current. The Technical Director owns it.

## Configuration

| Setting | Value | Why |
|---|---|---|
| `$01` | `$35` | BASIC and KERNAL out, I/O in |
| VIC bank (`$DD00`) | 3 (`$C000–$FFFF`) | |
| `$D018` | | Screen at …, charset at … |
| Video standard | PAL | |

## Memory layout

| Range | Contents | Size | Owner |
|---|---|---|---|
| `$0002–$00FF` | Zero page (see below) | | |
| `$0800–` | Code | | |
| | Tables | | |
| | Music | | |
| `$C000–$C3FF` | Screen 0 | 1 KB | |
| `$C400–$C7FF` | Screen 1 | 1 KB | |
| `$C800–$CFFF` | Charset | 2 KB | |
| `$D000–$DFFF` | Sprites (RAM under I/O) | 4 KB = 64 sprites | |
| `$FFFA–$FFFF` | NMI/RESET/IRQ vectors | 6 B | IRQ framework |

Free: …

## Zero page

| Range | Name(s) | Owner | Notes |
|---|---|---|---|
| `$02–$09` | `zp_tmp0`–`zp_tmp7` | Anyone (not IRQs) | Scratch |
| | `zp_irq_*` | IRQ handlers | |

## Raster timeline (PAL, 312 lines)

| Line | Handler | Job | Measured worst case | Budget until next handler |
|---|---|---|---|---|
| `$F8` | `irq_bottom` | Music, sprite sort, game logic | … cycles | Lines `$F8`–`$137`+`$00`–`$2F`: … cycles |
| `$30` | `irq_top` | … | | |

## Frame budget

| Item | Cycles per frame |
|---|---|
| Available (PAL) | 19,656 |
| Badlines | −1,075 |
| Sprite DMA (N bands × 21 lines × 19) | |
| Music player (measured) | |
| … | |
| **Headroom** | |
