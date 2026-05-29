from config import *

N_BIT = 0b1000
Z_BIT = 0b0100
V_BIT = 0b0010
C_BIT = 0b0001


class DataPath:
    """DataPath.

    Регистры: ACC, AC_SH, ACC_ADDR, SH_ADDR, AR, DR, SP, RSP, NZVC.
    """

    # ALU op
    ALU_ADD, ALU_SUB, ALU_MUL, ALU_DIV, ALU_MOD = "add", "sub", "mul", "div", "mod"
    ALU_AND, ALU_OR, ALU_XOR, ALU_NOT = "and", "or", "xor", "not"
    ALU_INC, ALU_DEC, ALU_SHL, ALU_SHR = "inc", "dec", "shl", "shr"
    ALU_PASS_R = "pass_r"

    # sel_alu_r
    R_FROM_IR, R_AC_SH, R_DR = "from_ir", "ac_sh", "dr"

    # sel_data
    D_ACC, D_AC_SH, D_SH_ADDR, D_ACC_ADDR, D_NZVC, D_FROM_PC = (
        "acc",
        "ac_sh",
        "sh_addr",
        "acc_addr",
        "nzvc",
        "from_pc",
    )

    # sel_acc_addr
    AA_AR, AA_SH_ADDR, AA_NONE = "ar", "sh_addr", "none"

    def __init__(self, data_memory):
        self.data_memory = list(data_memory)
        self.data_memory += [0] * (DATA_MEMORY_SIZE - len(self.data_memory))
        self.output_buffer = []

        self.acc = 0
        self.ar = 0
        self.dr = 0
        self.sp = INITIAL_SP
        self.rsp = INITIAL_RSP

        self.ac_shadow = 0
        self.acc_addr = None
        self.shadow_addr = None

        self.nzvc = 0
        self._cu = None

    @property
    def flag_neg(self):
        return bool(self.nzvc & N_BIT)

    @property
    def flag_zero(self):
        return bool(self.nzvc & Z_BIT)

    @property
    def flag_overflow(self):
        return bool(self.nzvc & V_BIT)

    @property
    def flag_carry(self):
        return bool(self.nzvc & C_BIT)

    def _set_nz(self, val):
        self.nzvc = (
            (self.nzvc & 0b0011)
            | (N_BIT if val < 0 else 0)
            | (Z_BIT if val == 0 else 0)
        )

    def _set_vc(self, ov, cy):
        self.nzvc = (self.nzvc & 0b1100) | (V_BIT if ov else 0) | (C_BIT if cy else 0)

    def signal_latch_ar(self, value):
        self.ar = value

    def signal_latch_dr_from_mem(self):
        addr = self.ar
        if self.shadow_addr is not None and addr == self.shadow_addr:
            self.dr = self.ac_shadow
            return
        if addr == INPUT_ADDR:
            val = self.data_memory[INPUT_ADDR]
            ch = chr(val) if 32 <= val < 127 else f"\\x{val:02x}"
            if self._cu is not None:
                self._cu._log_io.append(f"IN={val}({ch!r})")
            self.dr = val
            return
        self.dr = self.data_memory[addr]

    def signal_mem_write(self, sel_data, from_pc_value=0):
        if sel_data == self.D_ACC:
            val = to_signed32(self.acc)
        elif sel_data == self.D_AC_SH:
            val = to_signed32(self.ac_shadow)
        elif sel_data == self.D_NZVC:
            val = self.nzvc
        elif sel_data == self.D_FROM_PC:
            val = to_signed32(from_pc_value)
        elif sel_data == self.D_SH_ADDR:
            self.data_memory[self.ar] = self.shadow_addr
            return
        elif sel_data == self.D_ACC_ADDR:
            self.data_memory[self.ar] = self.acc_addr
            return
        else:
            raise ValueError(f"Unknown sel_data: {sel_data}")

        addr = self.ar
        if addr == OUTPUT_ADDR:
            self.output_buffer.append(val)
            ch = chr(val & 0xFF) if 32 <= (val & 0xFF) < 127 else f"\\x{val & 0xFF:02x}"
            if self._cu is not None:
                self._cu._log_io.append(f"OUT={val}({ch!r})")
            return
        self.data_memory[addr] = val

    def signal_latch_acc_addr(self, source):
        if source == self.AA_AR:
            self.acc_addr = self.ar
        elif source == self.AA_SH_ADDR:
            self.acc_addr = self.shadow_addr
        elif source == self.AA_NONE:
            self.acc_addr = None
        else:
            raise ValueError(f"Unknown sel_acc_addr: {source}")

    def signal_latch_sh_addr(self, value):
        self.shadow_addr = value

    def signal_latch_acc_sh_from_acc(self):
        self.ac_shadow = self.acc

    def signal_latch_acc_sh_from_dr(self):
        self.ac_shadow = to_signed32(self.dr or 0)

    def signal_clear_acc_sh(self):
        self.ac_shadow = 0

    def signal_alu_op(self, op, sel_alu_r=R_DR, ir_arg=0, update_vc=True):
        if sel_alu_r == self.R_FROM_IR:
            r = ir_arg
        elif sel_alu_r == self.R_AC_SH:
            r = self.ac_shadow
        else:
            r = self.dr

        a = self.acc
        ov = cy = False

        if op == self.ALU_ADD:
            result = a + r
            res32 = to_signed32(result)
            ov = bool(((a ^ res32) & (r ^ res32)) & SIGN32)
            cy = bool(((a & MASK32) + (r & MASK32)) >> 32)
        elif op == self.ALU_SUB:
            result = a - r
            res32 = to_signed32(result)
            ov = bool(((a ^ r) & (a ^ res32)) & SIGN32)
            cy = (a & MASK32) < (r & MASK32)
        elif op == self.ALU_MUL:
            result = a * r
            res32 = to_signed32(result)
            ov = result != res32
            cy = bool((result >> 32) & MASK32)
        elif op == self.ALU_DIV:
            if r == 0:
                raise ZeroDivisionError("div")
            result = int(a / r)
        elif op == self.ALU_MOD:
            if r == 0:
                raise ZeroDivisionError("mod")
            result = a % r
        elif op == self.ALU_AND:
            result = a & r
        elif op == self.ALU_OR:
            result = a | r
        elif op == self.ALU_XOR:
            result = a ^ r
        elif op == self.ALU_NOT:
            result = ~a
        elif op == self.ALU_INC:
            result = a + 1
        elif op == self.ALU_DEC:
            result = a - 1
        elif op == self.ALU_SHL:
            result = a << 1
        elif op == self.ALU_SHR:
            result = a >> 1
        elif op == self.ALU_PASS_R:
            result = r
        else:
            raise ValueError(f"Unknown ALU op: {op}")

        self.acc = to_signed32(result)
        self._set_nz(self.acc)
        if update_vc:
            self._set_vc(ov, cy)
        self.acc_addr = None

    def signal_latch_acc_from_shadow(self):
        self.acc = to_signed32(self.ac_shadow)

    def signal_inc_sp(self):
        self.sp += 4

    def signal_dec_sp(self):
        self.sp -= 4

    def signal_inc_rsp(self):
        self.rsp += 4

    def signal_dec_rsp(self):
        self.rsp -= 4

    def signal_clc(self):
        self.nzvc &= ~C_BIT

    def signal_clv(self):
        self.nzvc &= ~V_BIT

    def signal_latch_nzvc_from_dr(self):
        self.nzvc = (self.dr or 0) & 0xF
