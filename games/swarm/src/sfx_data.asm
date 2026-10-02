// Swarm's sound effect data for engine/sfx.asm: the game's ten effects, the one copy. Owned by
// the game: the values are the designer's and Simon's to tune by ear. FIRST VERSIONS, the
// design's descriptions (docs/games/swarm/design.md#sound-effects) turned into numbers by the
// raster-engineer; nobody has heard them yet.
//
// Imported by: games/swarm/src (as "sfx_data.asm") and the engine's sfx spike,
// tests/engine/sfx/main.asm (as "games/swarm/src/sfx_data.asm": the repo root is on the include
// path), which is the player for it.
// Hear a change: make run GAME=sfx SRC_DIR=tests/engine/sfx   (joystick in port 2: choose, fire)
//
// The spike relies on: ten effects, numbers 0-9 in this order, with these ten SFX_* labels. An
// effect added or removed changes the spike's list and probe numbers too: tell the
// raster-engineer. Changing values never breaks make test ARGS=sfx (engine/sfx.md, "Where a
// game's effect data lives").
//
// Use: after `#import "engine/sfx.asm"`, write SfxBegin(), import this file, add any effects of
// your own, then SfxEnd() where the tables should stand. The effect numbers are the labels below
// (SFX_PLAYER_SHOT = 0 ... SFX_GAME_OVER = 9), in this order.
//
// Voices are the module's (0-2 = the design's 1-3). Frequencies: value = Hz x 17.0284 (SfxHz).
// An effect's frames add up to the design's "Frames" column: that is how long it holds its voice.
//
// Envelope values were chosen with docs/reference/sid.md fact 15 in mind (measured in VICE: a
// start is up to 33 ms late when the voice's envelope was last stepping at a slow rate):
//   - every release is 0, so a voice is clean again two ticks after an effect ends;
//   - the two shots have every rate 0 and the dive's decay is no slower than its attack: they
//     are never late, alone or on top of each other;
//   - the explosion, the hit and the notes fade by a slow decay to sustain 0. A start on top of
//     one of them is late by 33 ms, and they are themselves late now and then from silence.
//     Whether that can be heard is Simon's call.

// Player shot: a short, high pulse "pew" falling in pitch. 8 frames, 2,165 Hz to 692 Hz.
.label SFX_PLAYER_SHOT = SfxEffect(0, 1, $00, $a0, 8)
        SfxStep(8, $41, $9000, -$0e00)

// Enemy shot: a lower, duller blip. 6 frames, triangle, 601 Hz to 376 Hz.
.label SFX_ENEMY_SHOT = SfxEffect(0, 1, $00, $f0, 8)
        SfxStep(6, $11, $2800, -$0300)

// Dive: a sawtooth swooping down an octave. 30 frames, 722 Hz to 361 Hz.
.label SFX_DIVE = SfxEffect(2, 1, $10, $80, 8)
        SfxStep(30, $21, $3000, -$00d4)

// Enemy explosion: a noise burst, quick decay (decay 8: gone in about 15 frames). 16 frames.
.label SFX_ENEMY_EXPLOSION = SfxEffect(1, 2, $08, $00, 8)
        SfxStep(16, $81, $3000, -$0200)

// Player hit: a long, low rumble falling in pitch, on two voices started together. 60 frames.
// A: noise. B: a low sawtooth under it, 180 Hz to 70 Hz.
.label SFX_PLAYER_HIT_A = SfxEffect(1, 3, $0a, $00, 8)
        SfxStep(60, $81, $1800, -$0050)
.label SFX_PLAYER_HIT_B = SfxEffect(2, 3, $0a, $00, 8)
        SfxStep(60, $21, $0c00, -$0020)

// Wave start: three rising notes, C5 E5 G5. 30 frames. The one-frame gate-off steps re-attack
// each note (measured, sid.md fact 7: about 13 ms into the note, from the level the last one
// had reached; no gap of silence).
.label SFX_WAVE_START = SfxEffect(2, 2, $09, $00, 8)
        SfxStep(9, $41, SfxHz(523.25), 0)
        SfxStep(1, $40, SfxHz(523.25), 0)
        SfxStep(9, $41, SfxHz(659.26), 0)
        SfxStep(1, $40, SfxHz(659.26), 0)
        SfxStep(10, $41, SfxHz(783.99), 0)

// Wave clear: four rising notes, C5 E5 G5 C6. 40 frames.
.label SFX_WAVE_CLEAR = SfxEffect(2, 2, $09, $00, 8)
        SfxStep(9, $41, SfxHz(523.25), 0)
        SfxStep(1, $40, SfxHz(523.25), 0)
        SfxStep(9, $41, SfxHz(659.26), 0)
        SfxStep(1, $40, SfxHz(659.26), 0)
        SfxStep(9, $41, SfxHz(783.99), 0)
        SfxStep(1, $40, SfxHz(783.99), 0)
        SfxStep(10, $41, SfxHz(1046.50), 0)

// Start: one bright note, C6, a narrower pulse. 10 frames.
.label SFX_START = SfxEffect(0, 3, $09, $00, 4)
        SfxStep(10, $41, SfxHz(1046.50), 0)

// Game over: three falling notes, G4 E4 C4. 50 frames.
.label SFX_GAME_OVER = SfxEffect(0, 3, $0a, $00, 8)
        SfxStep(15, $41, SfxHz(392.00), 0)
        SfxStep(1, $40, SfxHz(392.00), 0)
        SfxStep(15, $41, SfxHz(329.63), 0)
        SfxStep(1, $40, SfxHz(329.63), 0)
        SfxStep(18, $41, SfxHz(261.63), 0)
