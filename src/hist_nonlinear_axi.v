`timescale 1ns / 1ps

module hist_nonlinear_axi #(
    parameter INPUT_BITS = 14,
    parameter OUTPUT_BITS = 14,
    parameter AXIS_BITS = 16,
    parameter FRAME_WIDTH = 640,
    parameter FRAME_HEIGHT = 512,
    parameter INTENSITY_LEVELS = 16384,
    parameter LOG_TABLE_ENTRIES = 1024,
    parameter COUNT_BITS = 32,
    parameter ADDR_BITS = 14
) (
    input wire aclk,
    input wire aresetn,

    input wire [AXIS_BITS-1:0] s_axis_tdata,
    input wire s_axis_tvalid,
    output wire s_axis_tready,
    input wire s_axis_tuser,
    input wire s_axis_tlast,

    output reg [AXIS_BITS-1:0] m_axis_tdata,
    output reg m_axis_tvalid,
    input wire m_axis_tready,
    output reg m_axis_tuser,
    output reg m_axis_tlast,

    output reg busy_building_lut,
    output reg lut_valid
);

    localparam STATE_CLEAR = 2'd0;
    localparam STATE_STREAM = 2'd1;
    localparam STATE_SUM = 2'd2;
    localparam STATE_LUT = 2'd3;

    localparam FRAME_PIXELS = FRAME_WIDTH * FRAME_HEIGHT;
    localparam [ADDR_BITS-1:0] LAST_LEVEL_ADDR = {ADDR_BITS{1'b1}};
    localparam [COUNT_BITS-1:0] LAST_FRAME_PIXEL = FRAME_PIXELS - 1;
    localparam [COUNT_BITS-1:0] LOG_UPPER_LAST = (LOG_TABLE_ENTRIES / 2) - 1;
    localparam [63:0] OUTPUT_MAX_64 = (64'd1 << OUTPUT_BITS) - 1;

    reg [1:0] state;
    reg [ADDR_BITS-1:0] clear_addr;
    reg [ADDR_BITS-1:0] build_addr;
    reg [COUNT_BITS-1:0] pixel_count;
    reg [COUNT_BITS-1:0] histogram [0:INTENSITY_LEVELS-1];
    reg [OUTPUT_BITS-1:0] lut [0:INTENSITY_LEVELS-1];
    reg [COUNT_BITS-1:0] modified_total;
    reg [COUNT_BITS-1:0] lut_total;
    reg [COUNT_BITS-1:0] cumulative;
    reg [COUNT_BITS-1:0] modified_value;
    reg [COUNT_BITS-1:0] next_cumulative;

    wire output_slot_available;
    wire input_transfer;
    wire [ADDR_BITS-1:0] input_level;
    wire [OUTPUT_BITS-1:0] output_pixel;
    /* verilator lint_off UNUSEDSIGNAL */
    wire [AXIS_BITS-INPUT_BITS-1:0] unused_input_bits;
    /* verilator lint_on UNUSEDSIGNAL */

    assign output_slot_available = (!m_axis_tvalid) || m_axis_tready;
    assign s_axis_tready = (state == STATE_STREAM) && output_slot_available;
    assign input_transfer = s_axis_tvalid && s_axis_tready;
    assign input_level = s_axis_tdata[INPUT_BITS-1:0];
    assign output_pixel = lut_valid ? lut[input_level] : s_axis_tdata[OUTPUT_BITS-1:0];
    assign unused_input_bits = s_axis_tdata[AXIS_BITS-1:INPUT_BITS];

    function [COUNT_BITS-1:0] floor_log2;
        input [COUNT_BITS-1:0] value;
        integer bit_index;
        begin
            floor_log2 = {COUNT_BITS{1'b0}};
            for (bit_index = 0; bit_index < COUNT_BITS; bit_index = bit_index + 1) begin
                if (value[bit_index]) begin
                    floor_log2 = bit_index[COUNT_BITS-1:0];
                end
            end
        end
    endfunction

    function [9:0] paper_log_address;
        input [COUNT_BITS-1:0] count;
        reg [COUNT_BITS-1:0] upper_index;
        begin
            if (count < 512) begin
                paper_log_address = {1'b0, count[8:0]};
            end else begin
                upper_index = count >> 9;
                if (upper_index > LOG_UPPER_LAST) begin
                    upper_index = LOG_UPPER_LAST;
                end
                paper_log_address = {1'b1, upper_index[8:0]};
            end
        end
    endfunction

    function [COUNT_BITS-1:0] paper_log_table;
        input [9:0] address;
        reg [COUNT_BITS-1:0] expanded_count;
        begin
            if (address[9] == 1'b0) begin
                expanded_count = {{(COUNT_BITS-9){1'b0}}, address[8:0]};
            end else begin
                expanded_count = {{(COUNT_BITS-9){1'b0}}, address[8:0]} << 9;
            end
            if (expanded_count == 0) begin
                paper_log_table = {COUNT_BITS{1'b0}};
            end else begin
                paper_log_table = floor_log2(expanded_count);
            end
        end
    endfunction

    function [COUNT_BITS-1:0] paper_log_count;
        input [COUNT_BITS-1:0] count;
        begin
            if (count == 0) begin
                paper_log_count = {COUNT_BITS{1'b0}};
            end else if (count >= 262144) begin
                paper_log_count = 18;
            end else begin
                paper_log_count = paper_log_table(paper_log_address(count));
            end
        end
    endfunction

    function [OUTPUT_BITS-1:0] scale_cumulative_to_lut;
        input [COUNT_BITS-1:0] cumulative_value;
        input [COUNT_BITS-1:0] total_value;
        reg [63:0] scaled_value;
        /* verilator lint_off UNUSEDSIGNAL */
        reg [63:0] divided_value;
        /* verilator lint_on UNUSEDSIGNAL */
        begin
            scaled_value = (({{(64-COUNT_BITS){1'b0}}, cumulative_value}) * OUTPUT_MAX_64)
                + (({{(64-COUNT_BITS){1'b0}}, total_value}) >> 1);
            divided_value = scaled_value / {{(64-COUNT_BITS){1'b0}}, total_value};
            scale_cumulative_to_lut = divided_value[OUTPUT_BITS-1:0];
        end
    endfunction

    integer reset_index;
    initial begin
        state = STATE_CLEAR;
        clear_addr = {ADDR_BITS{1'b0}};
        build_addr = {ADDR_BITS{1'b0}};
        pixel_count = {COUNT_BITS{1'b0}};
        modified_total = {COUNT_BITS{1'b0}};
        lut_total = {COUNT_BITS{1'b0}};
        cumulative = {COUNT_BITS{1'b0}};
        m_axis_tdata = {AXIS_BITS{1'b0}};
        m_axis_tvalid = 1'b0;
        m_axis_tuser = 1'b0;
        m_axis_tlast = 1'b0;
        busy_building_lut = 1'b0;
        lut_valid = 1'b0;
        for (reset_index = 0; reset_index < INTENSITY_LEVELS; reset_index = reset_index + 1) begin
            histogram[reset_index] = {COUNT_BITS{1'b0}};
            lut[reset_index] = {OUTPUT_BITS{1'b0}};
        end
    end

    /* verilator lint_off BLKSEQ */
    always @(posedge aclk) begin
        if (!aresetn) begin
            state <= STATE_CLEAR;
            clear_addr <= {ADDR_BITS{1'b0}};
            build_addr <= {ADDR_BITS{1'b0}};
            pixel_count <= {COUNT_BITS{1'b0}};
            modified_total <= {COUNT_BITS{1'b0}};
            lut_total <= {COUNT_BITS{1'b0}};
            cumulative <= {COUNT_BITS{1'b0}};
            m_axis_tdata <= {AXIS_BITS{1'b0}};
            m_axis_tvalid <= 1'b0;
            m_axis_tuser <= 1'b0;
            m_axis_tlast <= 1'b0;
            busy_building_lut <= 1'b0;
            lut_valid <= 1'b0;
        end else begin
            if (m_axis_tvalid && m_axis_tready) begin
                m_axis_tvalid <= 1'b0;
                m_axis_tuser <= 1'b0;
                m_axis_tlast <= 1'b0;
            end

            case (state)
                STATE_CLEAR: begin
                    busy_building_lut <= 1'b1;
                    histogram[clear_addr] <= {COUNT_BITS{1'b0}};
                    if (clear_addr == LAST_LEVEL_ADDR) begin
                        clear_addr <= {ADDR_BITS{1'b0}};
                        pixel_count <= {COUNT_BITS{1'b0}};
                        busy_building_lut <= 1'b0;
                        state <= STATE_STREAM;
                    end else begin
                        clear_addr <= clear_addr + 1'b1;
                    end
                end

                STATE_STREAM: begin
                    busy_building_lut <= 1'b0;
                    if (input_transfer) begin
                        histogram[input_level] <= histogram[input_level] + 1'b1;
                        m_axis_tdata <= {{(AXIS_BITS-OUTPUT_BITS){1'b0}}, output_pixel};
                        m_axis_tvalid <= 1'b1;
                        m_axis_tuser <= s_axis_tuser;
                        m_axis_tlast <= s_axis_tlast;

                        if (pixel_count == LAST_FRAME_PIXEL) begin
                            pixel_count <= {COUNT_BITS{1'b0}};
                            build_addr <= {ADDR_BITS{1'b0}};
                            modified_total <= {COUNT_BITS{1'b0}};
                            busy_building_lut <= 1'b1;
                            state <= STATE_SUM;
                        end else begin
                            pixel_count <= pixel_count + 1'b1;
                        end
                    end
                end

                STATE_SUM: begin
                    busy_building_lut <= 1'b1;
                    modified_value = paper_log_count(histogram[build_addr]);
                    if (build_addr == LAST_LEVEL_ADDR) begin
                        lut_total <= modified_total + modified_value;
                        modified_total <= {COUNT_BITS{1'b0}};
                        build_addr <= {ADDR_BITS{1'b0}};
                        cumulative <= {COUNT_BITS{1'b0}};
                        state <= STATE_LUT;
                    end else begin
                        modified_total <= modified_total + modified_value;
                        build_addr <= build_addr + 1'b1;
                    end
                end

                STATE_LUT: begin
                    busy_building_lut <= 1'b1;
                    modified_value = paper_log_count(histogram[build_addr]);
                    next_cumulative = cumulative + modified_value;
                    cumulative <= next_cumulative;

                    if (lut_total == 0) begin
                        lut[build_addr] <= {OUTPUT_BITS{1'b0}};
                    end else begin
                        lut[build_addr] <= scale_cumulative_to_lut(next_cumulative, lut_total);
                    end

                    if (build_addr == LAST_LEVEL_ADDR) begin
                        build_addr <= {ADDR_BITS{1'b0}};
                        clear_addr <= {ADDR_BITS{1'b0}};
                        cumulative <= {COUNT_BITS{1'b0}};
                        lut_valid <= 1'b1;
                        state <= STATE_CLEAR;
                    end else begin
                        build_addr <= build_addr + 1'b1;
                    end
                end

                default: begin
                    state <= STATE_CLEAR;
                end
            endcase
        end
    end
    /* verilator lint_on BLKSEQ */

endmodule
