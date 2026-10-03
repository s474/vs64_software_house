"""Shared helpers for the stage 5 QA scripts (qa_*.py) of Swarm: one VICE, stepped one game frame
at a time, with the stick, the game's labels, a stick-driven bot and a PNG writer.

The generic parts (VICE on a free port, the stick, the frame stop, labels and memory, results of a stop that
doesn't come) are tools/gametest's Rig; Game wraps one and adds Swarm's state readers and the bot. check.py's
own helpers are swarmtest.py (a SwarmRig: the same Rig plus the placing helpers).

Not run by itself. Used by qa_soak.py, qa_play.py and qa_positions.py (same folder), from the repo root:

    uv run --package budget-runner python tests/games/swarm/qa_soak.py ...

Every step stops the machine at game_update_end (after the frame's input and updates, before
mux_update), exactly as check.py does; the stick is changed while stopped and takes effect in the
next frame.
"""

import struct
import sys
import zlib
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice  # noqa: F401  (the QA scripts star-import these)
from gametest import BITS, Rig
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
DEBUG_PRG = REPO / "build/swarm/swarm.prg"
RELEASE_PRG = REPO / "build/swarm-release/swarm.prg"
JOYPORT_IO_SIMULATION = 37
PORT2 = 1
MUX_OFF = 0xFF
GS_PLAY, GS_RESPAWN, GS_DYING, GS_OVER, GS_TITLE = 0, 1, 2, 3, 4
GS_NAMES = ["Play", "Respawn", "Dying", "GameOver", "Title"]
PH_FIGHT, PH_INTRO, PH_CLEAR = 0, 1, 2
ENEMY0, ENEMIES = 6, 18
ENEMY_DEAD, ENEMY_PARKED, ENEMY_WAITING = 0, 1, 2


class Game:
    """One VICE on a game build, stepped one game frame at a time (a gametest.Rig underneath: .rig)."""

    def __init__(self, prg=DEBUG_PRG, warmup=0):
        self.rig = Rig(prg, frame_label="game_update_end", warmup_frames=warmup, debug_labels=("mux_late_count",))
        self.prg = self.rig.prg
        self.v = self.rig.vice
        self.mon, self.sym = self.rig.mon, self.rig.sym
        self.cp = self.rig.frame_stop
        self.frames = 0
        self.debug = self.rig.is_debug
        self.stick = 0

    # ---- memory (by label)
    def mem(self, label, n=1, off=0):
        return self.rig.peeks(label, n, off)

    def peek(self, label, off=0):
        return self.rig.peek(label, off)

    def peek16(self, label):
        return self.rig.peek16(label)

    def poke(self, label, data, off=0):
        self.rig.poke(label, data, off)

    def score(self):
        return int(self.mem("game_score", 3).hex())

    def hiscore(self):
        return int(self.mem("game_hiscore", 3).hex())

    # ---- stepping
    def step(self, pressed=None):
        """Optionally set the stick (list of names or mask), run to the next game_update_end."""
        if pressed is not None:
            self.stick = pressed if isinstance(pressed, int) else sum(BITS[p] for p in pressed)
        self.rig.step(pressed)
        self.frames += 1

    def run(self, n, pressed=None):
        for i in range(n):
            self.step(pressed if i == 0 else None)

    # ---- state
    def gstate(self):
        return self.peek("zp_game_state")

    def player_x(self):
        return self.peek16("zp_player_x_lo")

    def sprites(self):
        n = 24
        xl, xh = self.mem("mux_x_lo", n), self.mem("mux_x_hi", n)
        ys = self.mem("mux_y", n)
        return [(xl[i] + 256 * (xh[i] & 1), ys[i]) for i in range(n)]

    def counters(self):
        if not self.debug:
            return {}
        c = {k: self.peek(k) for k in ("irq_late_count", "mux_late_count", "game_overrun_count",
                                       "mux_pin_drop_count", "mux_pin_excess_count", "mux_max_age")}
        c["flicker_frames"] = self.peek16("game_flicker_frames")
        c["idle_min"] = self.peek16("game_idle_min")
        return c

    def summary(self):
        return (f"f{self.frames} {GS_NAMES[self.gstate()] if self.gstate() < 5 else self.gstate()} "
                f"lives {self.peek('zp_lives')} wave {self.peek('zp_wave'):02x} ph {self.peek('zp_wave_phase')} "
                f"alive {self.peek('zp_enemies_alive')} div {self.peek('zp_divers_active')} score {self.score():06d}")

    # ---- the bot: chases the lowest enemy it can reach, fires always, sidesteps nearby shots
    def bot_stick(self, dodge=True, fire=True, chase=True):
        px, py = self.player_x(), 221
        sp = self.sprites()
        st = list(self.mem("enemy_state", ENEMIES))
        # enemy shots: virtual 1-3
        threat = None
        if dodge:
            for i in (1, 2, 3):
                x, y = sp[i]
                if y != MUX_OFF and 150 <= y <= 215 and abs(x - px) < 22:
                    if threat is None or y > threat[1]:
                        threat = (x, y)
            # divers close to the ship
            for e in range(ENEMIES):
                x, y = sp[ENEMY0 + e]
                if st[e] >= 0x80 and st[e] != 0x83 and y != MUX_OFF and y > 170 and abs(x - px) < 40:
                    if threat is None or y > threat[1]:
                        threat = (x, y)
        m = BITS["fire"] if fire else 0
        if threat is not None:
            x = threat[0]
            if px < 50:
                return m | BITS["right"]
            if px > 290:
                return m | BITS["left"]
            return m | (BITS["left"] if px >= x else BITS["right"])
        if not chase:
            return m
        # target: the lowest visible live enemy (largest Y), ties by nearest X
        best = None
        for e in range(ENEMIES):
            if st[e] in (ENEMY_DEAD, ENEMY_WAITING) or st[e] == 0x83:
                continue
            x, y = sp[ENEMY0 + e]
            if y == MUX_OFF:
                continue
            key = (-y, abs(x - px))
            if best is None or key < best[0]:
                best = (key, x)
        if best is None:
            return m
        tx = best[1]
        if tx - px > 6:
            m |= BITS["right"]
        elif px - tx > 6:
            m |= BITS["left"]
        return m

    def bot_frame(self, **kw):
        self.step(self.bot_stick(**kw))

    # ---- game flow helpers
    def start_game(self, wait_title=20):
        """From the title: wait for the press to be possible, press fire for 1 frame, release; run
        to Play's first frame. Fire is released first so the press is 'new'."""
        self.run(wait_title, [])
        self.step(["fire"])
        self.step([])
        for _ in range(12):
            if self.gstate() == GS_PLAY and self.peek("zp_lives") == 3:
                return
            self.step([])
        raise MeasureError("start_game: no game started")

    # ---- PNG (indexed display -> RGB), no PIL
    def screenshot(self, path):
        d = self.mon.display_get()
        pal = self.mon.palette()
        pixels = d.pixels.ljust(d.width * d.height, b"\x00")
        x0, y0, w, h = d.offset_x - 32, d.offset_y - 36, 384, 272    # the MCP server's "visible" crop (BORDER_LEFT/TOP)
        rows = []
        for y in range(h):
            line = pixels[(y0 + y) * d.width + x0:(y0 + y) * d.width + x0 + w]
            rows.append(b"\x00" + b"".join(bytes(pal[i]) for i in line))
        raw = b"".join(rows)

        def chunk(t, b):
            c = struct.pack(">I", len(b)) + t + b
            return c + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(png)

    def close(self):
        self.rig.close()
