`timescale 1ns / 1ps

/* verilator lint_off DECLFILENAME */

module hist_nonlinear_axi #(
    parameter INPUT_BITS = 14,
    parameter OUTPUT_BITS = 10,
    parameter AXIS_BITS = 16,
    parameter FRAME_WIDTH = 640,
    parameter FRAME_HEIGHT = 512,
    parameter INTENSITY_LEVELS = 1024,
    parameter LOG_TABLE_ENTRIES = 1024,
    parameter COUNT_BITS = 32,
    parameter ADDR_BITS = 10,
    parameter MEM_USE_BRAM = 1
) (
    input wire aclk,
    input wire aresetn,

    input wire [AXIS_BITS-1:0] s_axis_tdata,
    input wire s_axis_tvalid,
    output wire s_axis_tready,
    input wire s_axis_tuser,
    input wire s_axis_tlast,

    output wire [AXIS_BITS-1:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input wire m_axis_tready,
    output wire m_axis_tuser,
    output wire m_axis_tlast,

    output wire busy_building_lut,
    output wire lut_valid
);

    wire hist_we;
    wire [ADDR_BITS-1:0] hist_waddr;
    wire [COUNT_BITS-1:0] hist_wdata;
    wire [ADDR_BITS-1:0] hist_raddr;
    wire [COUNT_BITS-1:0] hist_rdata;

    wire lut_we;
    wire [ADDR_BITS-1:0] lut_waddr;
    wire [OUTPUT_BITS-1:0] lut_wdata;
    wire [ADDR_BITS-1:0] lut_raddr;
    wire [OUTPUT_BITS-1:0] lut_rdata;

    hist_nonlinear_axi_core #(
        .INPUT_BITS(INPUT_BITS),
        .OUTPUT_BITS(OUTPUT_BITS),
        .AXIS_BITS(AXIS_BITS),
        .FRAME_WIDTH(FRAME_WIDTH),
        .FRAME_HEIGHT(FRAME_HEIGHT),
        .LOG_TABLE_ENTRIES(LOG_TABLE_ENTRIES),
        .COUNT_BITS(COUNT_BITS),
        .ADDR_BITS(ADDR_BITS)
    ) core (
        .aclk(aclk),
        .aresetn(aresetn),

        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tuser(s_axis_tuser),
        .s_axis_tlast(s_axis_tlast),

        .m_axis_tdata(m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .m_axis_tuser(m_axis_tuser),
        .m_axis_tlast(m_axis_tlast),

        .busy_building_lut(busy_building_lut),
        .lut_valid(lut_valid),

        .hist_we(hist_we),
        .hist_waddr(hist_waddr),
        .hist_wdata(hist_wdata),
        .hist_raddr(hist_raddr),
        .hist_rdata(hist_rdata),

        .lut_we(lut_we),
        .lut_waddr(lut_waddr),
        .lut_wdata(lut_wdata),
        .lut_raddr(lut_raddr),
        .lut_rdata(lut_rdata)
    );

    hist_nonlinear_ram_1r1w #(
        .DATA_BITS(COUNT_BITS),
        .ADDR_BITS(ADDR_BITS),
        .DEPTH(INTENSITY_LEVELS),
        .USE_BRAM(MEM_USE_BRAM)
    ) histogram_memory (
        .clk(aclk),
        .rd_addr(hist_raddr),
        .rd_data(hist_rdata),
        .we(hist_we),
        .wr_addr(hist_waddr),
        .wr_data(hist_wdata)
    );

    hist_nonlinear_ram_1r1w #(
        .DATA_BITS(OUTPUT_BITS),
        .ADDR_BITS(ADDR_BITS),
        .DEPTH(INTENSITY_LEVELS),
        .USE_BRAM(MEM_USE_BRAM)
    ) lut_memory (
        .clk(aclk),
        .rd_addr(lut_raddr),
        .rd_data(lut_rdata),
        .we(lut_we),
        .wr_addr(lut_waddr),
        .wr_data(lut_wdata)
    );

endmodule

module hist_nonlinear_axi_core #(
    parameter INPUT_BITS = 14,
    parameter OUTPUT_BITS = 10,
    parameter AXIS_BITS = 16,
    parameter FRAME_WIDTH = 640,
    parameter FRAME_HEIGHT = 512,
    parameter LOG_TABLE_ENTRIES = 1024,
    parameter COUNT_BITS = 32,
    parameter ADDR_BITS = 10
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
    output reg lut_valid,

    output reg hist_we,
    output reg [ADDR_BITS-1:0] hist_waddr,
    output reg [COUNT_BITS-1:0] hist_wdata,
    output reg [ADDR_BITS-1:0] hist_raddr,
    input wire [COUNT_BITS-1:0] hist_rdata,

    output reg lut_we,
    output reg [ADDR_BITS-1:0] lut_waddr,
    output reg [OUTPUT_BITS-1:0] lut_wdata,
    output reg [ADDR_BITS-1:0] lut_raddr,
    input wire [OUTPUT_BITS-1:0] lut_rdata
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
    reg [1:0] stream_stage;
    reg [1:0] build_stage;
    reg [ADDR_BITS-1:0] clear_addr;
    reg [ADDR_BITS-1:0] build_addr;
    reg [COUNT_BITS-1:0] pixel_count;
    reg [COUNT_BITS-1:0] modified_total;
    reg [COUNT_BITS-1:0] lut_total;
    reg [COUNT_BITS-1:0] cumulative;
    reg [COUNT_BITS-1:0] modified_value;
    reg [COUNT_BITS-1:0] next_cumulative;

    reg [ADDR_BITS-1:0] stream_level;
    reg [OUTPUT_BITS-1:0] stream_bypass_pixel;
    reg stream_tuser;
    reg stream_tlast;
    reg stream_last_pixel;

    wire output_slot_available;
    wire input_transfer;
    wire [ADDR_BITS-1:0] input_level;
    wire [OUTPUT_BITS-1:0] output_pixel;
    /* verilator lint_off UNUSEDSIGNAL */
    wire [AXIS_BITS-INPUT_BITS-1:0] unused_input_bits;
    /* verilator lint_on UNUSEDSIGNAL */

    assign output_slot_available = (!m_axis_tvalid) || m_axis_tready;
    assign s_axis_tready = (state == STATE_STREAM) && (stream_stage == 2'd0) && output_slot_available;
    assign input_transfer = s_axis_tvalid && s_axis_tready;
    assign input_level = s_axis_tdata[INPUT_BITS-1 -: ADDR_BITS];
    assign output_pixel = lut_valid ? lut_rdata : stream_bypass_pixel;
    assign unused_input_bits = s_axis_tdata[AXIS_BITS-1:INPUT_BITS];

    generate
        if (INPUT_BITS > ADDR_BITS) begin : gen_unused_input_lsb_bits
            /* verilator lint_off UNUSEDSIGNAL */
            wire [INPUT_BITS-ADDR_BITS-1:0] unused_input_lsb_bits;
            /* verilator lint_on UNUSEDSIGNAL */

            assign unused_input_lsb_bits = s_axis_tdata[INPUT_BITS-ADDR_BITS-1:0];
        end
    endgenerate

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

    /* verilator lint_off BLKSEQ */
    always @(posedge aclk) begin
        if (!aresetn) begin
            state <= STATE_CLEAR;
            stream_stage <= 2'd0;
            build_stage <= 2'd0;
            clear_addr <= {ADDR_BITS{1'b0}};
            build_addr <= {ADDR_BITS{1'b0}};
            pixel_count <= {COUNT_BITS{1'b0}};
            modified_total <= {COUNT_BITS{1'b0}};
            lut_total <= {COUNT_BITS{1'b0}};
            cumulative <= {COUNT_BITS{1'b0}};
            hist_we <= 1'b0;
            hist_waddr <= {ADDR_BITS{1'b0}};
            hist_wdata <= {COUNT_BITS{1'b0}};
            hist_raddr <= {ADDR_BITS{1'b0}};
            lut_we <= 1'b0;
            lut_waddr <= {ADDR_BITS{1'b0}};
            lut_wdata <= {OUTPUT_BITS{1'b0}};
            lut_raddr <= {ADDR_BITS{1'b0}};
            stream_level <= {ADDR_BITS{1'b0}};
            stream_bypass_pixel <= {OUTPUT_BITS{1'b0}};
            stream_tuser <= 1'b0;
            stream_tlast <= 1'b0;
            stream_last_pixel <= 1'b0;
            m_axis_tdata <= {AXIS_BITS{1'b0}};
            m_axis_tvalid <= 1'b0;
            m_axis_tuser <= 1'b0;
            m_axis_tlast <= 1'b0;
            busy_building_lut <= 1'b0;
            lut_valid <= 1'b0;
        end else begin
            hist_we <= 1'b0;
            lut_we <= 1'b0;

            if (m_axis_tvalid && m_axis_tready) begin
                m_axis_tvalid <= 1'b0;
                m_axis_tuser <= 1'b0;
                m_axis_tlast <= 1'b0;
            end

            case (state)
                STATE_CLEAR: begin
                    busy_building_lut <= 1'b1;
                    hist_we <= 1'b1;
                    hist_waddr <= clear_addr;
                    hist_wdata <= {COUNT_BITS{1'b0}};
                    if (clear_addr == LAST_LEVEL_ADDR) begin
                        clear_addr <= {ADDR_BITS{1'b0}};
                        pixel_count <= {COUNT_BITS{1'b0}};
                        stream_stage <= 2'd0;
                        busy_building_lut <= 1'b0;
                        state <= STATE_STREAM;
                    end else begin
                        clear_addr <= clear_addr + 1'b1;
                    end
                end

                STATE_STREAM: begin
                    busy_building_lut <= 1'b0;
                    case (stream_stage)
                        2'd0: begin
                            if (input_transfer) begin
                                hist_raddr <= input_level;
                                lut_raddr <= input_level;
                                stream_level <= input_level;
                                stream_bypass_pixel <= s_axis_tdata[INPUT_BITS-1 -: OUTPUT_BITS];
                                stream_tuser <= s_axis_tuser;
                                stream_tlast <= s_axis_tlast;
                                stream_last_pixel <= (pixel_count == LAST_FRAME_PIXEL);
                                stream_stage <= 2'd1;
                                if (pixel_count == LAST_FRAME_PIXEL) begin
                                    pixel_count <= {COUNT_BITS{1'b0}};
                                end else begin
                                    pixel_count <= pixel_count + 1'b1;
                                end
                            end
                        end

                        2'd1: begin
                            stream_stage <= 2'd2;
                        end

                        default: begin
                            if (output_slot_available) begin
                                hist_we <= 1'b1;
                                hist_waddr <= stream_level;
                                hist_wdata <= hist_rdata + 1'b1;
                                m_axis_tdata <= {{(AXIS_BITS-OUTPUT_BITS){1'b0}}, output_pixel};
                                m_axis_tvalid <= 1'b1;
                                m_axis_tuser <= stream_tuser;
                                m_axis_tlast <= stream_tlast;
                                stream_stage <= 2'd0;
                                if (stream_last_pixel) begin
                                    build_addr <= {ADDR_BITS{1'b0}};
                                    modified_total <= {COUNT_BITS{1'b0}};
                                    build_stage <= 2'd0;
                                    busy_building_lut <= 1'b1;
                                    state <= STATE_SUM;
                                end
                            end
                        end
                    endcase
                end

                STATE_SUM: begin
                    busy_building_lut <= 1'b1;
                    case (build_stage)
                        2'd0: begin
                            hist_raddr <= build_addr;
                            build_stage <= 2'd1;
                        end

                        2'd1: begin
                            build_stage <= 2'd2;
                        end

                        default: begin
                            modified_value = paper_log_count(hist_rdata);
                            if (build_addr == LAST_LEVEL_ADDR) begin
                                lut_total <= modified_total + modified_value;
                                modified_total <= {COUNT_BITS{1'b0}};
                                build_addr <= {ADDR_BITS{1'b0}};
                                cumulative <= {COUNT_BITS{1'b0}};
                                build_stage <= 2'd0;
                                state <= STATE_LUT;
                            end else begin
                                modified_total <= modified_total + modified_value;
                                build_addr <= build_addr + 1'b1;
                                build_stage <= 2'd0;
                            end
                        end
                    endcase
                end

                STATE_LUT: begin
                    busy_building_lut <= 1'b1;
                    case (build_stage)
                        2'd0: begin
                            hist_raddr <= build_addr;
                            build_stage <= 2'd1;
                        end

                        2'd1: begin
                            build_stage <= 2'd2;
                        end

                        default: begin
                            modified_value = paper_log_count(hist_rdata);
                            next_cumulative = cumulative + modified_value;
                            cumulative <= next_cumulative;
                            lut_we <= 1'b1;
                            lut_waddr <= build_addr;
                            if (lut_total == 0) begin
                                lut_wdata <= {OUTPUT_BITS{1'b0}};
                            end else begin
                                lut_wdata <= scale_cumulative_to_lut(next_cumulative, lut_total);
                            end

                            if (build_addr == LAST_LEVEL_ADDR) begin
                                build_addr <= {ADDR_BITS{1'b0}};
                                clear_addr <= {ADDR_BITS{1'b0}};
                                cumulative <= {COUNT_BITS{1'b0}};
                                build_stage <= 2'd0;
                                lut_valid <= 1'b1;
                                state <= STATE_CLEAR;
                            end else begin
                                build_addr <= build_addr + 1'b1;
                                build_stage <= 2'd0;
                            end
                        end
                    endcase
                end

                default: begin
                    state <= STATE_CLEAR;
                end
            endcase
        end
    end
    /* verilator lint_on BLKSEQ */

endmodule

module hist_nonlinear_ram_1r1w #(
    parameter DATA_BITS = 32,
    parameter ADDR_BITS = 10,
    parameter DEPTH = 1024,
    /* verilator lint_off UNUSEDPARAM */
    parameter USE_BRAM = 1
    /* verilator lint_on UNUSEDPARAM */
) (
    input wire clk,
    input wire [ADDR_BITS-1:0] rd_addr,
    output reg [DATA_BITS-1:0] rd_data,
    input wire we,
    input wire [ADDR_BITS-1:0] wr_addr,
    input wire [DATA_BITS-1:0] wr_data
);

    generate
`ifdef VERILATOR
        begin : gen_verilator_ram
            reg [DATA_BITS-1:0] mem [0:DEPTH-1];

            always @(posedge clk) begin
                rd_data <= mem[rd_addr];
                if (we) begin
                    mem[wr_addr] <= wr_data;
                end
            end
        end
`else
        if (USE_BRAM != 0) begin : gen_bram_ram
            (* ram_style = "block" *) reg [DATA_BITS-1:0] mem [0:DEPTH-1];

            always @(posedge clk) begin
                rd_data <= mem[rd_addr];
                if (we) begin
                    mem[wr_addr] <= wr_data;
                end
            end
        end else begin : gen_generic_ram
            reg [DATA_BITS-1:0] mem [0:DEPTH-1];

            always @(posedge clk) begin
                rd_data <= mem[rd_addr];
                if (we) begin
                    mem[wr_addr] <= wr_data;
                end
            end
        end
`endif
    endgenerate

endmodule

/* verilator lint_on DECLFILENAME */
