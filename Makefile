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
# ASSET_DIR=<dir> (optional, several allowed) also converts the sprite sheets of those directories
# into this build's directory, e.g. a wrapper build in tests/ that #imports a game from games/.

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
# Sprite sheets in SRC_DIR (and in each ASSET_DIR, if given) are converted by tools/png2sprites:
# NAME.hires.png (24x21 cells) and NAME.mc.png (12x21 multicolour cells) become
# build/<game>/NAME.{hires,mc}.bin, plus .col (one colour byte per sprite) and .inc (KickAssembler
# constants). The source loads them with LoadBinary("build/<game>/NAME.mc.bin"); constants are
# NAME_MC_COUNT/_MC1/_MC2 and NAME_HIRES_COUNT. build/<game>/ is also on the include path, so a
# source shared by two builds can say #import "NAME.hires.inc" / LoadBinary("NAME.hires.bin") with
# no build-specific path. See tools/png2sprites/README.md.
PNG2SPRITES := uv run --quiet --package png2sprites png2sprites
ASSET_DIR   ?=
ASSET_DIRS  := $(SRC_DIR) $(ASSET_DIR)
SPRITE_PNGS := $(foreach d,$(ASSET_DIRS),$(wildcard $(d)/*.hires.png $(d)/*.mc.png))
SPRITE_BINS := $(sort $(patsubst %.png,$(OUT_DIR)/%.bin,$(notdir $(SPRITE_PNGS))))
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

# Dependency file: SOURCES only knows SRC_DIR and engine/, but a program may #import files from
# anywhere (a wrapper build in tests/ importing games/<title>/src/). KickAssembler reports every
# file it read (-asminfo all, [files] section); the recipe turns that list into
# build/<game>/<game>.d ("PRG: file file ..."), which is included below, so the next run rebuilds
# when any of them changes. Each non-build file also gets an empty rule, so a deleted or renamed
# source does not stop make ("No rule to make target"). The first build has no .d: the PRG is
# missing, so it builds anyway. KickAss.jar's own include is skipped.
DEP      := $(OUT_DIR)/$(GAME).d
DEPINFO  := $(OUT_DIR)/.asminfo
DEPAWK   := '/^\[files\]/{f=1;next} /^\[/{f=0} f{sub(/^[0-9]+;/,""); sub(/^\.\//,""); if ($$0 !~ /^KickAss.jar:/) print}'

.PHONY: all run run-sfx crunch d64 clean test test-long test-tools

all: $(PRG)

# -vicesymbols writes main.vs (named after the source) next to the PRG so VICE shows labels;
# -bytedumpfile writes main.dump: every source line with its address and bytes
$(PRG): $(SOURCES)
	@mkdir -p $(OUT_DIR)
	$(JAVA) -jar $(KICKASS_JAR) $(MAIN) -o $(PRG) -odir $(abspath $(OUT_DIR)) \
		-libdir $(CURDIR) -libdir $(abspath $(OUT_DIR)) -vicesymbols -symbolfile -bytedumpfile main.dump -showmem \
		-asminfo all -asminfofile $(abspath $(DEPINFO)) $(DEFINES)
	@awk $(DEPAWK) $(DEPINFO) | awk -v prg=$(PRG) '{ d = d " " $$0; if ($$0 !~ /(^|\/)build\//) p = p $$0 ":\n" } \
		END { print prg ":" d; printf "%s", p }' > $(DEP)
	@rm -f $(DEPINFO)
	@echo "$(DEFINES)" > $(STAMP)

-include $(DEP)

# One pair of conversion rules per source directory (SRC_DIR, then each ASSET_DIR); the first
# whose PNG exists is used. Absolute paths, so the rules do not depend on the directory uv runs from.
define SPRITE_RULES
$$(OUT_DIR)/%.hires.bin $$(OUT_DIR)/%.hires.col $$(OUT_DIR)/%.hires.inc: $(1)/%.hires.png $$(wildcard tools/png2sprites/src/png2sprites/*.py) Makefile
	@mkdir -p $$(OUT_DIR)
	@$$(PNG2SPRITES) -m hires $$(abspath $$<) -o $$(abspath $$(OUT_DIR))/$$*.hires.bin \
		--colors $$(abspath $$(OUT_DIR))/$$*.hires.col --inc $$(abspath $$(OUT_DIR))/$$*.hires.inc \
		--prefix $$(shell echo $$* | tr 'a-z-' 'A-Z_')_HIRES

$$(OUT_DIR)/%.mc.bin $$(OUT_DIR)/%.mc.col $$(OUT_DIR)/%.mc.inc: $(1)/%.mc.png $$(wildcard tools/png2sprites/src/png2sprites/*.py) Makefile
	@mkdir -p $$(OUT_DIR)
	@$$(PNG2SPRITES) -m multicolour $$(abspath $$<) -o $$(abspath $$(OUT_DIR))/$$*.mc.bin \
		--colors $$(abspath $$(OUT_DIR))/$$*.mc.col --inc $$(abspath $$(OUT_DIR))/$$*.mc.inc \
		--prefix $$(shell echo $$* | tr 'a-z-' 'A-Z_')_MC
endef
$(foreach d,$(ASSET_DIRS),$(eval $(call SPRITE_RULES,$(d))))

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
