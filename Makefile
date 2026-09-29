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
SOURCES   := $(wildcard $(SRC_DIR)/*.asm $(SRC_DIR)/*.inc engine/*.asm)
DEFINES   := $(if $(filter release,$(BUILD)),,-define DEBUG)

.PHONY: all run run-sfx crunch d64 clean

all: $(PRG)

# -vicesymbols writes main.vs (named after the source) next to the PRG so VICE shows labels;
# -bytedumpfile writes main.dump: every source line with its address and bytes
$(PRG): $(SOURCES)
	@mkdir -p $(OUT_DIR)
	$(JAVA) -jar $(KICKASS_JAR) $(MAIN) -o $(PRG) -odir $(abspath $(OUT_DIR)) \
		-libdir $(CURDIR) -vicesymbols -symbolfile -bytedumpfile main.dump -showmem $(DEFINES)

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
