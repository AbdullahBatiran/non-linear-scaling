VERILATOR ?= verilator
TOP ?= hist_nonlinear_axi
RTL ?= ../src/hist_nonlinear_axi.v
OUTPUT_BITS ?= 8
INPUT_BITS ?= 14
ADDR_BITS ?= 10
INTENSITY_LEVELS ?= 1024
FRAME_WIDTH ?= 640
FRAME_HEIGHT ?= 512
TRACE ?= 0

BUILD_DIR := obj_dir
SIM_BIN := $(BUILD_DIR)/V$(TOP)
TRACE_FLAGS :=

ifeq ($(TRACE),1)
TRACE_FLAGS += --trace
endif

.PHONY: all rtl-sim view-wave clean

all: rtl-sim

rtl-sim:
	$(VERILATOR) -Wall $(TRACE_FLAGS) --cc $(RTL) --top-module $(TOP) \
		-GINPUT_BITS=$(INPUT_BITS) \
		-GOUTPUT_BITS=$(OUTPUT_BITS) \
		-GADDR_BITS=$(ADDR_BITS) \
		-GINTENSITY_LEVELS=$(INTENSITY_LEVELS) \
		-GFRAME_WIDTH=$(FRAME_WIDTH) \
		-GFRAME_HEIGHT=$(FRAME_HEIGHT) \
		--exe rtl_sim_main.cpp \
		-CFLAGS "-std=c++17 -O2"
	$(MAKE) -C $(BUILD_DIR) -f V$(TOP).mk V$(TOP)

view-wave:
	./view_waveform.sh "$(WAVE)"

clean:
	rm -rf $(BUILD_DIR)
