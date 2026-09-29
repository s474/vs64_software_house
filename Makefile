# C64 Software House build.
#   make                 build games/$(GAME) -> build/$(GAME)/$(GAME).prg
#   make run             build and autostart in VICE
#   make crunch          Exomizer self-extracting build -> $(GAME)-sfx.prg
#   make d64             disk image containing the crunched build
#   make clean
# Pick a game with GAME=<name> (default: hello). For programs outside games/, also set
# SRC_DIR, e.g. make GAME=badline SRC_DIR=tests/timing/badline BUILD=release drops the DEBUG
# define (matching VS64's "build" setting). Tool paths can be overridden from
# the environment, e.g. KICKASS_JAR=~/tools/KickAss.jar make

GAME        ?= hello
BUILD       ?= debug

JAVA        ?= /opt/homebrew/opt/openjdk/bin/java
KICKASS_JAR ?= /Applications/KickAssembler/KickAss.jar
X64         ?= x64sc
C1541       ?= c1541
EXOMIZER    ?= exomizer

SRC_DIR   ?= games/$(GAME)/src
OUT_DIR   := build/$(GAME)
MAIN      := $(SRC_DIR)/main.asm
PRG       := $(OUT_DIR)/$(GAME).prg
SFX       := $(OUT_DIR)/$(GAME)-sfx.prg
D64       := $(OUT_DIR)/$(GAME).d64
# Sprite sheets in SRC_DIR are converted by tools/png2sprites: NAME.hires.png (24x21 cells) and
# NAME.mc.png (12x21 multicolour cells) become build/<game>/NAME.{hires,mc}.bin, plus .col (one
# colour byte per sprite) and .inc (KickAssembler constants). The source loads them with
# LoadBinary("build/<game>/NAME.mc.bin"); constants are NAME_MC_COUNT/_MC1/_MC2 and
# NAME_HIRES_COUNT. See tools/png2sprites/README.md.
PNG2SPRITES := cd tools/png2sprites && uv run --quiet png2sprites
SPRITE_PNGS := $(wildcard $(SRC_DIR)/*.hires.png $(SRC_DIR)/*.mc.png)
SPRITE_BINS := $(patsubst $(SRC_DIR)/%.png,$(OUT_DIR)/%.bin,$(SPRITE_PNGS))
SOURCES   := $(wildcard $(SRC_DIR)/*.asm $(SRC_DIR)/*.inc engine/*.asm) $(SPRITE_BINS)
DEFINES   := $(if $(filter release,$(BUILD)),,-define DEBUG)

.PHONY: all run run-sfx crunch d64 clean test-tools

all: $(PRG)

# -vicesymbols writes main.vs (named after the source) next to the PRG so VICE shows labels;
# -bytedumpfile writes main.dump: every source line with its address and bytes
$(PRG): $(SOURCES)
	@mkdir -p $(OUT_DIR)
	$(JAVA) -jar $(KICKASS_JAR) $(MAIN) -o $(PRG) -odir $(abspath $(OUT_DIR)) \
		-libdir $(CURDIR) -vicesymbols -symbolfile -bytedumpfile main.dump -showmem $(DEFINES)

# Absolute paths: the converter runs from tools/png2sprites (its uv project).
$(OUT_DIR)/%.hires.bin $(OUT_DIR)/%.hires.col $(OUT_DIR)/%.hires.inc: $(SRC_DIR)/%.hires.png $(wildcard tools/png2sprites/src/png2sprites/*.py) Makefile
	@mkdir -p $(OUT_DIR)
	@$(PNG2SPRITES) -m hires $(abspath $<) -o $(abspath $(OUT_DIR))/$*.hires.bin \
		--colors $(abspath $(OUT_DIR))/$*.hires.col --inc $(abspath $(OUT_DIR))/$*.hires.inc \
		--prefix $(shell echo $* | tr 'a-z-' 'A-Z_')_HIRES

$(OUT_DIR)/%.mc.bin $(OUT_DIR)/%.mc.col $(OUT_DIR)/%.mc.inc: $(SRC_DIR)/%.mc.png $(wildcard tools/png2sprites/src/png2sprites/*.py) Makefile
	@mkdir -p $(OUT_DIR)
	@$(PNG2SPRITES) -m multicolour $(abspath $<) -o $(abspath $(OUT_DIR))/$*.mc.bin \
		--colors $(abspath $(OUT_DIR))/$*.mc.col --inc $(abspath $(OUT_DIR))/$*.mc.inc \
		--prefix $(shell echo $* | tr 'a-z-' 'A-Z_')_MC

test-tools:
	cd tools/png2sprites && uv run --quiet pytest -q

crunch: $(SFX)

$(SFX): $(PRG)
	$(EXOMIZER) sfx basic -q -o $@ $<

d64: $(D64)

$(D64): $(SFX)
	$(C1541) -format "$(GAME),01" d64 $@ -write $< "$(GAME)" >/dev/null

run: $(PRG)
	$(X64) -moncommands $(OUT_DIR)/main.vs -autostart $(PRG) >/dev/null 2>&1 &

run-sfx: $(SFX)
	$(X64) -autostart $(SFX) >/dev/null 2>&1 &

clean:
	rm -rf build
