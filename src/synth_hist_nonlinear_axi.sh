#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TOP="${TOP:-hist_nonlinear_axi}"
PART="${PART:-xc7z020clg484-1}"
CLOCK_PERIOD_NS="${CLOCK_PERIOD_NS:-10.0}"
MODE="${MODE:-impl}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/tmp/hist_nonlinear_axi_vivado}"
RTL_FILE="$SCRIPT_DIR/hist_nonlinear_axi.v"
CLEAN=0
PARAM_OVERRIDES=()

usage() {
    cat <<'EOF'
Usage: src/synth_hist_nonlinear_axi.sh [options]

Run Vivado synthesis for src/hist_nonlinear_axi.v and print utilization,
timing, and power summaries. Implementation runs by default when possible.

Options:
  --part PART              FPGA part number. Default: xc7z020clg484-1
  --clock-period NS        aclk period in ns. Default: 10.0
  --mode synth|impl        synth only, or synth + opt/place/route. Default: impl
  --build-dir DIR          Output directory. Default: tmp/hist_nonlinear_axi_vivado
  --jobs N                 Vivado max threads. Default: nproc
  --top TOP                Top module. Default: hist_nonlinear_axi
  --param NAME=VALUE       Override one Verilog parameter. Repeatable.
  --params "A=1 B=2"       Override multiple Verilog parameters.
  --clean                  Remove the build directory before running
  -h, --help               Show this help

Environment overrides are also supported:
  PART, CLOCK_PERIOD_NS, MODE, BUILD_DIR, JOBS, TOP, IP_PARAMS

Examples:
  src/synth_hist_nonlinear_axi.sh
  src/synth_hist_nonlinear_axi.sh --mode synth
  PART=xc7z020clg400-1 src/synth_hist_nonlinear_axi.sh --clock-period 8
  src/synth_hist_nonlinear_axi.sh --mode synth --param OUTPUT_BITS=8 --param ADDR_BITS=8 --param INTENSITY_LEVELS=256
  IP_PARAMS="OUTPUT_BITS=8 ADDR_BITS=8 INTENSITY_LEVELS=256" src/synth_hist_nonlinear_axi.sh
EOF
}

add_param_override() {
    local override="$1"
    if [[ ! "$override" =~ ^[A-Za-z_][A-Za-z0-9_]*=.+$ ]]; then
        echo "Invalid parameter override: $override" >&2
        echo "Expected NAME=VALUE, for example OUTPUT_BITS=8" >&2
        exit 2
    fi
    PARAM_OVERRIDES+=("$override")
}

if [[ -n "${IP_PARAMS:-}" ]]; then
    for param_override in $IP_PARAMS; do
        add_param_override "$param_override"
    done
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --part)
            PART="$2"
            shift 2
            ;;
        --clock-period)
            CLOCK_PERIOD_NS="$2"
            shift 2
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        --top)
            TOP="$2"
            shift 2
            ;;
        --param)
            add_param_override "$2"
            shift 2
            ;;
        --params)
            for param_override in $2; do
                add_param_override "$param_override"
            done
            shift 2
            ;;
        --clean)
            CLEAN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$MODE" != "synth" && "$MODE" != "impl" ]]; then
    echo "--mode must be 'synth' or 'impl'" >&2
    exit 2
fi

if [[ ! "$JOBS" =~ ^[0-9]+$ || "$JOBS" -lt 1 ]]; then
    echo "--jobs must be a positive integer" >&2
    exit 2
fi

if [[ "$JOBS" -gt 8 ]]; then
    echo "Vivado general.maxThreads supports at most 8; using --jobs 8 instead of $JOBS" >&2
    JOBS=8
fi

if [[ ! -f "$RTL_FILE" ]]; then
    echo "RTL file not found: $RTL_FILE" >&2
    exit 1
fi

# Vivado is intentionally activated here so the script can run from a fresh shell.
# activate.sh currently tries the repo author's installed Vivado paths.
source "$REPO_ROOT/activate.sh"

if ! command -v vivado >/dev/null 2>&1; then
    echo "vivado was not found on PATH after sourcing $REPO_ROOT/activate.sh" >&2
    exit 1
fi

if [[ "$CLEAN" -eq 1 ]]; then
    rm -rf "$BUILD_DIR"
fi

REPORT_DIR="$BUILD_DIR/reports"
TCL_FILE="$BUILD_DIR/run_hist_nonlinear_axi_synth.tcl"
CONSTRAINTS_FILE="$BUILD_DIR/hist_nonlinear_axi_ip.xdc"
CONSOLE_LOG="$BUILD_DIR/vivado_console.log"
VIVADO_LOG="$BUILD_DIR/vivado.log"
VIVADO_JOU="$BUILD_DIR/vivado.jou"

mkdir -p "$REPORT_DIR"

cat > "$CONSTRAINTS_FILE" <<EOF
create_clock -name aclk -period $CLOCK_PERIOD_NS [get_ports aclk]
EOF

cat > "$TCL_FILE" <<'EOF'
set top $::env(HIST_SYNTH_TOP)
set part $::env(HIST_SYNTH_PART)
set mode $::env(HIST_SYNTH_MODE)
set jobs $::env(HIST_SYNTH_JOBS)
set rtl_file [file normalize $::env(HIST_SYNTH_RTL_FILE)]
set xdc_file [file normalize $::env(HIST_SYNTH_XDC_FILE)]
set build_dir [file normalize $::env(HIST_SYNTH_BUILD_DIR)]
set report_dir [file normalize $::env(HIST_SYNTH_REPORT_DIR)]
set param_text [string trim $::env(HIST_SYNTH_PARAMS)]

set_param general.maxThreads $jobs
file mkdir $report_dir

puts "INFO: Reading $rtl_file"
read_verilog $rtl_file
read_xdc $xdc_file

set generic_args {}
if {$param_text ne ""} {
    foreach generic [split $param_text] {
        if {$generic ne ""} {
            lappend generic_args $generic
        }
    }
}

puts "INFO: Synthesizing top=$top part=$part"
if {[llength $generic_args] > 0} {
    puts "INFO: Parameter overrides: $generic_args"
    synth_design -top $top -part $part -generic $generic_args
} else {
    synth_design -top $top -part $part
}

set input_ports {}
set output_ports {}
foreach port [get_ports -quiet *] {
    set direction [get_property DIRECTION $port]
    set port_name [get_property NAME $port]
    if {$direction eq "IN" && $port_name ne "aclk"} {
        lappend input_ports $port
    } elseif {$direction eq "OUT"} {
        lappend output_ports $port
    }
}
if {[llength $input_ports] > 0} {
    set_input_delay -clock aclk 0 $input_ports
}
if {[llength $output_ports] > 0} {
    set_output_delay -clock aclk 0 $output_ports
}

write_checkpoint -force "$build_dir/${top}_synth.dcp"
report_utilization -file "$report_dir/synth_utilization.rpt"
report_utilization -hierarchical -file "$report_dir/synth_utilization_hier.rpt"
report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose -file "$report_dir/synth_timing_summary.rpt"
if {[catch {report_power -file "$report_dir/synth_power.rpt"} power_error]} {
    puts "WARN: synth report_power failed: $power_error"
}

if {$mode eq "impl"} {
    puts "INFO: Running implementation through route_design"
    if {[catch {
        opt_design
        place_design
        phys_opt_design
        route_design
        write_checkpoint -force "$build_dir/${top}_routed.dcp"
        report_utilization -file "$report_dir/impl_utilization.rpt"
        report_utilization -hierarchical -file "$report_dir/impl_utilization_hier.rpt"
        report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose -file "$report_dir/impl_timing_summary.rpt"
        report_clock_utilization -file "$report_dir/impl_clock_utilization.rpt"
        if {[catch {report_power -file "$report_dir/impl_power.rpt"} impl_power_error]} {
            puts "WARN: impl report_power failed: $impl_power_error"
        }
    } impl_error]} {
        puts "WARN: implementation did not complete: $impl_error"
    }
}

puts "INFO: Reports written to $report_dir"
EOF

export HIST_SYNTH_TOP="$TOP"
export HIST_SYNTH_PART="$PART"
export HIST_SYNTH_MODE="$MODE"
export HIST_SYNTH_JOBS="$JOBS"
export HIST_SYNTH_RTL_FILE="$RTL_FILE"
export HIST_SYNTH_XDC_FILE="$CONSTRAINTS_FILE"
export HIST_SYNTH_BUILD_DIR="$BUILD_DIR"
export HIST_SYNTH_REPORT_DIR="$REPORT_DIR"
export HIST_SYNTH_PARAMS="${PARAM_OVERRIDES[*]}"

echo "Running Vivado $MODE flow"
echo "  RTL:          $RTL_FILE"
echo "  Top:          $TOP"
echo "  Part:         $PART"
echo "  Clock period: ${CLOCK_PERIOD_NS} ns"
echo "  Build dir:    $BUILD_DIR"
if [[ "${#PARAM_OVERRIDES[@]}" -gt 0 ]]; then
    echo "  Parameters:   ${PARAM_OVERRIDES[*]}"
fi

if ! vivado -mode batch -source "$TCL_FILE" -log "$VIVADO_LOG" -journal "$VIVADO_JOU" > "$CONSOLE_LOG" 2>&1; then
    echo
    echo "Vivado failed. Last 80 log lines:"
    tail -n 80 "$CONSOLE_LOG" || true
    echo
    echo "Full log: $CONSOLE_LOG"
    exit 1
fi

print_matching_lines() {
    local title="$1"
    local file="$2"
    local pattern="$3"

    echo
    echo "== $title =="
    if [[ ! -f "$file" ]]; then
        echo "Report not available: $file"
        return
    fi

    local matches
    matches="$(grep -E "$pattern" "$file" || true)"
    if [[ -n "$matches" ]]; then
        echo "$matches" | awk -F'|' '
            {
                key = $2
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
                gsub(/\*$/, "", key)
                if (!seen[key]++) {
                    print
                }
            }
        '
    else
        echo "No compact summary lines matched. See full report: $file"
    fi
}

print_timing_summary() {
    local title="$1"
    local file="$2"

    echo
    echo "== $title =="
    if [[ ! -f "$file" ]]; then
        echo "Report not available: $file"
        return
    fi

    awk '
        /\| Design Timing Summary/ {
            print
            in_design = 1
            next
        }
        in_design && /WNS\(ns\)/ {
            print
            getline
            print
            getline
            print
            in_design = 0
            next
        }
        /\| Clock Summary/ {
            print
            in_clock = 1
            next
        }
        in_clock && /^Clock[[:space:]]+Waveform/ {
            print
            getline
            print
            getline
            print
            in_clock = 0
            next
        }
        /Slack \(MET\)|Slack \(VIOLATED\)/ && slack_lines < 1 {
            print
            slack_lines++
        }
    ' "$file"
}

FINAL_STAGE="synth"
if [[ "$MODE" == "impl" && -f "$REPORT_DIR/impl_utilization.rpt" ]]; then
    FINAL_STAGE="impl"
fi

UTIL_REPORT="$REPORT_DIR/${FINAL_STAGE}_utilization.rpt"
TIMING_REPORT="$REPORT_DIR/${FINAL_STAGE}_timing_summary.rpt"
POWER_REPORT="$REPORT_DIR/${FINAL_STAGE}_power.rpt"

print_matching_lines \
    "Utilization ($FINAL_STAGE)" \
    "$UTIL_REPORT" \
    '^\|[[:space:]]*(Slice LUTs\*?|LUT as Logic|LUT as Memory|Slice Registers|Register as Flip Flop|Block RAM Tile|RAMB18|RAMB36/FIFO\*?|DSPs|Bonded IOB|BUFGCTRL|BUFG)[[:space:]]'

print_timing_summary "Timing ($FINAL_STAGE)" "$TIMING_REPORT"

print_matching_lines \
    "Power ($FINAL_STAGE)" \
    "$POWER_REPORT" \
    '(Total On-Chip Power|Dynamic \(W\)|Device Static \(W\)|Junction Temperature|Thermal Margin|Confidence level|Power supplied)'

echo
echo "Full reports:"
echo "  Utilization: $UTIL_REPORT"
echo "  Timing:      $TIMING_REPORT"
echo "  Power:       $POWER_REPORT"
echo "  Vivado log:  $CONSOLE_LOG"
