VERILATOR ?= verilator
TOP ?= hist_nonlinear_axi
RTL ?= ../src/hist_nonlinear_axi.v
OUTPUT_BITS ?= 14
FRAME_WIDTH ?= 640
FRAME_HEIGHT ?= 512

BUILD_DIR := obj_dir
SIM_BIN := $(BUILD_DIR)/V$(TOP)

.PHONY: all rtl-sim clean

all: rtl-sim

rtl-sim:
	$(VERILATOR) -Wall --cc $(RTL) --top-module $(TOP) \
		-GOUTPUT_BITS=$(OUTPUT_BITS) \
		-GFRAME_WIDTH=$(FRAME_WIDTH) \
		-GFRAME_HEIGHT=$(FRAME_HEIGHT) \
		--exe rtl_sim_main.cpp \
		-CFLAGS "-std=c++17 -O2"
	$(MAKE) -C $(BUILD_DIR) -f V$(TOP).mk V$(TOP)

clean:
	rm -rf $(BUILD_DIR)
