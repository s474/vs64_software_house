# C64 Software House build.
#   make                 build games/$(GAME) -> build/$(GAME)/$(GAME).prg
#   make run             build and autostart in VICE
#   make crunch          Exomizer self-extracting build -> $(GAME)-sfx.prg
#   make d64             disk image containing the crunched build
#   make test            budget runner: build + run the engine spikes in VICE, check budget.json
#   make test-long       the same checks with ~34x the samples and frames (LONG_SCALE=n to change)
#   make test-tools      pytest for the Python tools
#   make clean
# Pick a game with GAME=<name> (default: hello). For programs outside games/, also set
# SRC_DIR, e.g. make GAME=badline SRC_DIR=tests/timing/badline
# BUILD=release drops the DEBUG define (matching VS64's "build" setting). Tool paths can
# be overridden from the environment, e.g. KICKASS_JAR=~/tools/KickAss.jar make

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
PNG2SPRITES := uv run --quiet --package png2sprites png2sprites
SPRITE_PNGS := $(wildcard $(SRC_DIR)/*.hires.png $(SRC_DIR)/*.mc.png)
SPRITE_BINS := $(patsubst $(SRC_DIR)/%.png,$(OUT_DIR)/%.bin,$(SPRITE_PNGS))
SOURCES   := $(wildcard $(SRC_DIR)/*.asm $(SRC_DIR)/*.inc engine/*.asm) $(SPRITE_BINS)
DEFINES   := $(if $(filter release,$(BUILD)),,-define DEBUG)

# Build stamp: build/<game>/.build-defines holds the DEFINES the PRG was built with. When it differs
# from this run's DEFINES (BUILD= was switched, in either direction), the stale PRG is deleted
# while the makefile is read, before make looks at any timestamp, so the PRG rebuilds. Done at
# parse time because make 3.81 (macOS) compares whole seconds: a prerequisite stamp rewritten in
# the same second as the PRG would not look newer, and deleting the PRG from a recipe is too
# late (make has already decided it is up to date). The PRG recipe writes the stamp after a
# successful build. Any new build-wide setting that changes the output belongs in DEFINES.
STAMP := $(OUT_DIR)/.build-defines
ifeq ($(shell [ -f $(STAMP) ] && [ "`cat $(STAMP)`" = "$(DEFINES)" ] && echo same),)
$(shell rm -f $(PRG))
endif

.PHONY: all run run-sfx crunch d64 clean test test-long test-tools

all: $(PRG)

# -vicesymbols writes main.vs (named after the source) next to the PRG so VICE shows labels;
# -bytedumpfile writes main.dump: every source line with its address and bytes
$(PRG): $(SOURCES)
	@mkdir -p $(OUT_DIR)
	$(JAVA) -jar $(KICKASS_JAR) $(MAIN) -o $(PRG) -odir $(abspath $(OUT_DIR)) \
		-libdir $(CURDIR) -vicesymbols -symbolfile -bytedumpfile main.dump -showmem $(DEFINES)
	@echo "$(DEFINES)" > $(STAMP)

# Absolute paths, so the rules do not depend on the directory uv runs from.
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

# Python tests for every workspace member that has some (no VICE needed).
test-tools:
	uv run --quiet --all-packages pytest -q tools

# Budget runner: builds each tests/**/budget.json spike, runs it in VICE, checks the budgets.
# Pass ARGS to select spikes: make test ARGS=irq_chain
test:
	@uv run --quiet --package budget-runner budget-runner $(ARGS)

# Long run: the same checks with every sample / frame count multiplied by LONG_SCALE (default 34:
# the multiplexer's 600-pass main-loop checks become ~20,000 passes). Pass ARGS to select spikes.
LONG_SCALE ?= 34
test-long:
	@uv run --quiet --package budget-runner budget-runner --scale $(LONG_SCALE) $(ARGS)

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
