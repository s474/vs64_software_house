"""Swarm placeholder shapes and the shape index (shared by make_sprites.py and check_sprites.py).

Order in the sheet = sprite number n (pointer $C0 + n). See README.md.
Each shape is a 24x21 grid of bools, row 0 at the top.
"""

import math

W, H = 24, 21

# index -> (name, colour number from the design's colour table)
SHAPES = [
    ("player", 3),            # cyan
    ("player_shot", 3),       # cyan
    ("enemy_shot", 10),       # light red
    ("enemy_a_1", 4),         # purple
    ("enemy_a_2", 4),
    ("enemy_b_1", 7),         # yellow
    ("enemy_b_2", 7),
    ("enemy_c_1", 13),        # light green
    ("enemy_c_2", 13),
    ("explosion_1", 8),       # orange (in game: orange for enemies, white for the player)
    ("explosion_2", 8),
    ("explosion_3", 8),
    ("explosion_4", 8),
]

# Art areas (inclusive columns, rows) and hit boxes, from design.md "Hit boxes".
PLAYER_ART, PLAYER_BOX = (4, 19, 4, 20), (6, 17, 6, 20)
ENEMY_ART, ENEMY_BOX = (2, 21, 1, 19), (4, 19, 3, 17)
PSHOT_BOX = (11, 12, 0, 7)
ESHOT_BOX = (11, 12, 14, 20)

# Half shapes (left half, mirrored to make the right half).
PLAYER = [  # 16 wide x 17 tall, placed at column 4, row 4
    ".......#", ".......#", "......##", "......##", ".....###", ".....###",
    "....####", "....####", "#...####", "#..#####", "##.#####", "########",
    "########", "########", "###.####", "##..####", "##...###",
]

# 20 wide x 19 tall, placed at column 2, row 1. Same outline in both frames.
ENEMIES = {
    "a": [  # moth: wings up, then wings down
        [
            "..........", "#.......##", "##......##", "###....###", "####..####",
            "##########", ".#########", "..########", "...#######", "....######",
            "...#######", "..###.####", ".###...###", ".##.....##", "........##",
            "........##", ".......###", "..........", "..........",
        ],
        [
            "..........", "........##", "........##", "...#######", "..########",
            ".#########", "##########", "##########", "###..#####", "###...####",
            "####.#####", "####..####", "###...####", "##....####", "#.....####",
            "#.....####", "#.......##", "..........", "..........",
        ],
    ],
    "b": [  # squid: dome, tentacles swing left then right
        [
            "..........", ".....#####", "...#######", "..########", ".#########",
            ".#########", "##########", "##########", "##.###.###", "##########",
            ".#########", "##..##..##", "##..##..#.", ".##..##...", ".##..##...",
            "##..##....", "##..##....", "..........", "..........",
        ],
        [
            "..........", ".....#####", "...#######", "..########", ".#########",
            ".#########", "##########", "##########", "##.###.###", "##########",
            ".#########", "##..##..##", ".##..##..#", "..##..##..", "..##..##..",
            ".##..##...", "##..##....", "..........", "..........",
        ],
    ],
    "c": [  # saucer: wide, antenna, legs stepping
        [
            "..........", "..#.......", "...#......", "....#...##", ".....#####",
            "..########", ".#########", "##########", "##.##.####", "##########",
            ".#########", "..########", ".#..##..#.", "#...#..#..", "#...#..#..",
            "##..#..##.", "##........", "..........", "..........",
        ],
        [
            "..........", "..#.......", "...#......", "....#...##", ".....#####",
            "..########", ".#########", "##########", "##.##.####", "##########",
            ".#########", "..########", "..#.##.#..", ".#..#..#..", "#...#..#..",
            "#..##..##.", "##........", "..........", "..........",
        ],
    ],
}


def mirror(rows):
    return [r + r[::-1] for r in rows]


def blank():
    return [[False] * W for _ in range(H)]


def stamp(g, rows, col, row):
    for y, r in enumerate(mirror(rows)):
        for x, c in enumerate(r):
            if c == "#":
                g[row + y][col + x] = True
    return g


def rect(g, c0, c1, r0, r1):
    for y in range(r0, r1 + 1):
        for x in range(c0, c1 + 1):
            g[y][x] = True
    return g


def explosion(n):
    g = blank()
    cx, cy = 11.5, 10.0
    if n == 0:  # small plus-shaped flash
        for y in range(H):
            for x in range(W):
                dx, dy = abs(x - cx), abs(y - cy)
                if dx + dy <= 3.5 or (dx <= 0.6 and dy <= 5) or (dy <= 0.6 and dx <= 5.5):
                    g[y][x] = True
    elif n == 1:  # full burst: filled disc with 8 rays
        for y in range(H):
            for x in range(W):
                dx, dy = x - cx, y - cy
                r = math.hypot(dx, dy)
                ang = math.atan2(dy, dx)
                ray = abs(math.sin(4 * ang)) < 0.28 and r < 11
                if r < 6 or ray:
                    g[y][x] = True
    elif n == 2:  # ring that has opened up, with a hollow centre
        for y in range(H):
            for x in range(W):
                dx, dy = x - cx, y - cy
                r = math.hypot(dx, dy * 1.1)
                if 6.5 <= r < 10 and (x + y) % 5 != 0:
                    g[y][x] = True
    else:  # sparks: scattered 2x2 specks
        for (x, y) in [(2, 3), (9, 1), (18, 2), (21, 8), (19, 16), (12, 19), (4, 17),
                       (1, 10), (7, 8), (15, 12), (13, 5), (10, 14)]:
            rect(g, x, x + 1, y, min(y + 1, H - 1))
    return g


def shape(index):
    name = SHAPES[index][0]
    g = blank()
    if name == "player":
        stamp(g, PLAYER, 4, 4)
    elif name == "player_shot":
        rect(g, 11, 12, 0, 7)
    elif name == "enemy_shot":
        rect(g, 11, 12, 14, 20)
    elif name.startswith("enemy_"):
        stamp(g, ENEMIES[name[6]][int(name[8]) - 1], 2, 1)
    else:
        g = explosion(int(name[-1]) - 1)
    return g
