#include <verilated.h>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "Vhist_nonlinear_axi.h"

namespace {

struct Args {
    std::string input_path;
    std::string output_path;
    int width = 640;
    int height = 512;
    int input_stall_period = 0;
    int output_stall_period = 0;
    uint64_t max_cycles = 0;
};

uint16_t read_le16(const char* ptr) {
    const auto b0 = static_cast<uint8_t>(ptr[0]);
    const auto b1 = static_cast<uint8_t>(ptr[1]);
    return static_cast<uint16_t>(b0 | (b1 << 8));
}

void write_le16(std::ostream& stream, uint16_t value) {
    const char bytes[2] = {
        static_cast<char>(value & 0xFF),
        static_cast<char>((value >> 8) & 0xFF),
    };
    stream.write(bytes, sizeof(bytes));
}

std::vector<uint16_t> read_raw16(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("failed to open input: " + path);
    }
    std::vector<char> bytes((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    if (bytes.size() % 2 != 0) {
        throw std::runtime_error("input byte count is not divisible by 2");
    }
    std::vector<uint16_t> words(bytes.size() / 2);
    for (size_t index = 0; index < words.size(); ++index) {
        words[index] = read_le16(&bytes[index * 2]);
    }
    return words;
}

void write_raw16(const std::string& path, const std::vector<uint16_t>& words) {
    std::ofstream file(path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("failed to open output: " + path);
    }
    for (const auto word : words) {
        write_le16(file, word);
    }
}

void usage(const char* argv0) {
    std::cerr
        << "usage: " << argv0 << " --input in.raw --output out.raw [--width 640] [--height 512]\n"
        << "       [--input-stall-period N] [--output-stall-period N] [--max-cycles N]\n";
}

Args parse_args(int argc, char** argv) {
    Args args;
    for (int index = 1; index < argc; ++index) {
        const std::string option = argv[index];
        auto require_value = [&](const std::string& name) -> std::string {
            if (index + 1 >= argc) {
                throw std::runtime_error("missing value for " + name);
            }
            return argv[++index];
        };

        if (option == "--input") {
            args.input_path = require_value(option);
        } else if (option == "--output") {
            args.output_path = require_value(option);
        } else if (option == "--width") {
            args.width = std::stoi(require_value(option));
        } else if (option == "--height") {
            args.height = std::stoi(require_value(option));
        } else if (option == "--input-stall-period") {
            args.input_stall_period = std::stoi(require_value(option));
        } else if (option == "--output-stall-period") {
            args.output_stall_period = std::stoi(require_value(option));
        } else if (option == "--max-cycles") {
            args.max_cycles = std::stoull(require_value(option));
        } else if (option == "--help" || option == "-h") {
            usage(argv[0]);
            std::exit(0);
        } else {
            throw std::runtime_error("unknown option: " + option);
        }
    }

    if (args.input_path.empty() || args.output_path.empty()) {
        usage(argv[0]);
        throw std::runtime_error("--input and --output are required");
    }
    if (args.width <= 0 || args.height <= 0) {
        throw std::runtime_error("--width and --height must be positive");
    }
    return args;
}

bool stalled(uint64_t cycle, int period) {
    return period > 0 && (cycle % static_cast<uint64_t>(period)) == 0;
}

void eval_at(Vhist_nonlinear_axi& dut, int clock) {
    dut.aclk = clock;
    dut.eval();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        Verilated::commandArgs(argc, argv);
        const Args args = parse_args(argc, argv);
        const std::vector<uint16_t> input_words = read_raw16(args.input_path);
        const uint64_t frame_pixels = static_cast<uint64_t>(args.width) * static_cast<uint64_t>(args.height);
        if (frame_pixels == 0 || (input_words.size() % frame_pixels) != 0) {
            throw std::runtime_error("input does not contain a whole number of frames");
        }

        Vhist_nonlinear_axi dut;
        std::vector<uint16_t> output_words;
        output_words.reserve(input_words.size());

        dut.aclk = 0;
        dut.aresetn = 0;
        dut.s_axis_tdata = 0;
        dut.s_axis_tvalid = 0;
        dut.s_axis_tuser = 0;
        dut.s_axis_tlast = 0;
        dut.m_axis_tready = 1;

        for (int cycle = 0; cycle < 8; ++cycle) {
            eval_at(dut, 0);
            eval_at(dut, 1);
        }
        dut.aresetn = 1;

        size_t input_index = 0;
        uint64_t cycle = 0;
        const uint64_t max_cycles =
            args.max_cycles != 0 ? args.max_cycles : (input_words.size() * 20ULL + 5000000ULL);

        while (output_words.size() < input_words.size()) {
            if (cycle > max_cycles) {
                throw std::runtime_error("simulation exceeded max cycle limit");
            }

            const bool have_input = input_index < input_words.size();
            const uint64_t frame_offset = have_input ? (input_index % frame_pixels) : 0;
            const int x = static_cast<int>(frame_offset % static_cast<uint64_t>(args.width));
            const bool input_valid = have_input && !stalled(cycle, args.input_stall_period);

            dut.s_axis_tvalid = input_valid ? 1 : 0;
            dut.s_axis_tdata = have_input ? input_words[input_index] : 0;
            dut.s_axis_tuser = input_valid && frame_offset == 0 ? 1 : 0;
            dut.s_axis_tlast = input_valid && x == args.width - 1 ? 1 : 0;
            dut.m_axis_tready = stalled(cycle, args.output_stall_period) ? 0 : 1;

            eval_at(dut, 0);
            const bool input_fire = dut.s_axis_tvalid && dut.s_axis_tready;
            const bool output_fire = dut.m_axis_tvalid && dut.m_axis_tready;
            if (output_fire) {
                output_words.push_back(static_cast<uint16_t>(dut.m_axis_tdata & 0xFFFF));
            }

            eval_at(dut, 1);
            if (input_fire) {
                ++input_index;
            }
            ++cycle;
        }

        write_raw16(args.output_path, output_words);
        std::cerr << "simulated " << input_words.size() << " pixels in " << cycle << " cycles\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << "\n";
        return 1;
    }
}
