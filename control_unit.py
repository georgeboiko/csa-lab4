from config import (
    ACC_ADDR_SAVE_ADDR,
    ACC_SAVE_ADDR,
    INITIAL_RSP,
    INITIAL_SP,
    INPUT_ADDR,
    IVT_INPUT_ADDR,
    NZVC_SAVE_ADDR,
    OUTPUT_ADDR,
)
from datapath import DataPath
from isa import (
    ARG_MASK,
    INSTRUCTIONS_WITH_ARG,
    INSTR_BYTES,
    Opcode,
    binary_to_opcode,
    to_signed24,
)
from typing import ClassVar


class ControlUnit:

    _ALWAYS_SHOW_ARG = frozenset(
        {
            Opcode.LOAD_IMM,
            Opcode.LOAD,
            Opcode.STORE,
            Opcode.STORE_IND,
            Opcode.ADD,
            Opcode.SUB,
            Opcode.MUL,
            Opcode.DIV,
            Opcode.MOD,
            Opcode.AND,
            Opcode.OR,
            Opcode.XOR,
            Opcode.JUMP,
            Opcode.BEQZ,
            Opcode.BNEZ,
            Opcode.BGTZ,
            Opcode.BLTZ,
            Opcode.BGEZ,
            Opcode.BLEZ,
            Opcode.BVS,
            Opcode.BVC,
            Opcode.BCS,
            Opcode.BCC,
            Opcode.CALL,
        }
    )

    _ALU_BIN: ClassVar[dict] = {
        Opcode.ADD: (DataPath.ALU_ADD, True),
        Opcode.SUB: (DataPath.ALU_SUB, True),
        Opcode.MUL: (DataPath.ALU_MUL, True),
        Opcode.DIV: (DataPath.ALU_DIV, False),
        Opcode.MOD: (DataPath.ALU_MOD, False),
        Opcode.AND: (DataPath.ALU_AND, False),
        Opcode.OR: (DataPath.ALU_OR, False),
        Opcode.XOR: (DataPath.ALU_XOR, False),
    }

    _ALU_UN: ClassVar[dict] = {
        Opcode.INC: DataPath.ALU_INC,
        Opcode.DEC: DataPath.ALU_DEC,
        Opcode.NOT: DataPath.ALU_NOT,
        Opcode.SHIFTL: DataPath.ALU_SHL,
        Opcode.SHIFTR: DataPath.ALU_SHR,
    }

    _FLUSH_OPS = frozenset(
        {
            Opcode.HALT,
            Opcode.JUMP,
            Opcode.CALL,
            Opcode.CALL_ACC,
            Opcode.RET,
            Opcode.BEQZ,
            Opcode.BNEZ,
            Opcode.BGTZ,
            Opcode.BLTZ,
            Opcode.BGEZ,
            Opcode.BLEZ,
            Opcode.BVS,
            Opcode.BVC,
            Opcode.BCS,
            Opcode.BCC,
        }
    )

    def __init__(self, program, data_path, superscalar=True):
        self.program_memory = list(program)
        self.dp = data_path
        self.superscalar = superscalar

        self.pc = 0
        self.ir = 0
        self.step = 0

        self._interrupts_enabled = False
        self._irq = False

        self._isr_in_entry = False

        self._tick = 0
        self._log_slot_acc = ""
        self._log_slot_shadow = ""
        self._log_io = []

        data_path._cu = self

    def signal_latch_pc(self, value):
        self.pc = value
        self.step = 0

    def signal_inc_pc(self, delta=INSTR_BYTES):
        self.pc += delta

    def signal_latch_ir(self, word):
        self.ir = word

    def signal_step_inc(self):
        self.step += 1

    def signal_step_reset(self):
        self.step = 0

    def signal_latch_ei(self, value):
        self._interrupts_enabled = value

    def trigger_interrupt(self):
        self._irq = True

    def enable_interrupts(self):
        self.signal_latch_ei(True)

    def current_tick(self):
        return self._tick

    def tick(self):
        self._tick += 1

    def _read_instr_word(self, ba):
        m = self.program_memory
        b0 = m[ba] if ba < len(m) else 0
        b1 = m[ba + 1] if ba + 1 < len(m) else 0
        b2 = m[ba + 2] if ba + 2 < len(m) else 0
        b3 = m[ba + 3] if ba + 3 < len(m) else 0
        return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3

    def _ir_opcode(self):
        return binary_to_opcode.get((self.ir >> 24) & 0xFF)

    def _ir_arg(self):
        return to_signed24(self.ir & ARG_MASK)

    def process_next_tick(self):
        dp = self.dp
        self._log_slot_acc = ""
        self._log_slot_shadow = ""
        self._log_io = []

        if self._isr_in_entry:
            self._isr_entry_tick(self.step)
            self.tick()
            return

        # IRQ check в начале такта
        if (
            self._interrupts_enabled
            and self._irq
            and dp.data_memory[IVT_INPUT_ADDR] != 0
        ):
            self._irq = False
            restart_pc = self.pc if self.step == 0 else self.pc - INSTR_BYTES
            self._isr_in_entry = True
            self.signal_step_reset()
            self._log_slot_acc = f"INTERRUPT -> ISR push retPC={restart_pc}"
            dp.signal_dec_rsp()
            dp.signal_latch_ar(dp.rsp)
            dp.signal_mem_write(DataPath.D_FROM_PC, from_pc_value=restart_pc)
            self.signal_step_inc()
            self.tick()
            return

        # FETCH - 1 такт
        if self.step == 0:
            word = self._read_instr_word(self.pc)
            self.signal_latch_ir(word)
            prev_pc = self.pc
            self.signal_inc_pc(INSTR_BYTES)
            self.signal_step_inc()
            op = self._ir_opcode()
            if op is None:
                raise ValueError(f"Неизвестный опкод по PC={prev_pc}: {word:#010x}")
            self._log_slot_acc = (
                f"FETCH pc={prev_pc} word={word:#010x} -> IR={op.value}"
            )
            self.tick()
            return

        # EXECUTE
        op = self._ir_opcode()
        arg = self._ir_arg() if op in INSTRUCTIONS_WITH_ARG else 0
        s = self.step

        if self.superscalar and op in self._FLUSH_OPS and dp.shadow_addr is not None:
            if s == 1:
                dp.signal_latch_ar(dp.shadow_addr)
                self._log_slot_shadow = f"flush AR <- SH_ADDR={dp.shadow_addr}"
                self.signal_step_inc()
                self.tick()
                return
            if s == 2:
                addr = dp.ar
                dp.signal_mem_write(DataPath.D_AC_SH)
                dp.signal_clear_acc_sh()
                dp.signal_latch_sh_addr(None)
                self._log_slot_shadow = f"flush mem[{addr}] <- AC_SH"
                self.step = 1
                self.tick()
                return

        self._log_slot_acc = f"{self._fmt_instr(op, arg)} S{s}"
        if self.superscalar and dp.shadow_addr is not None:
            self._log_slot_shadow = f"shadow:[{dp.shadow_addr}]={dp.ac_shadow}"

        self._execute_step(op, arg, s)
        self.tick()

    def _isr_entry_tick(self, s):
        dp = self.dp
        if s == 1:
            if dp.shadow_addr is not None:
                dp.signal_latch_ar(dp.shadow_addr)
                self._log_slot_acc = f"ISR flush: AR<-SH_ADDR={dp.shadow_addr}"
            else:
                self._log_slot_acc = "ISR flush: no shadow"
        elif s == 2:
            if dp.shadow_addr is not None:
                dp.signal_mem_write(DataPath.D_AC_SH)
                self._log_slot_acc = f"ISR flush: mem[{dp.ar}]<-AC_SH={dp.ac_shadow}"
            dp.signal_clear_acc_sh()
            dp.signal_latch_sh_addr(None)
            dp.signal_latch_acc_addr(DataPath.AA_NONE)
        # ACC
        elif s == 3:
            dp.signal_latch_ar(ACC_SAVE_ADDR)
        elif s == 4:
            dp.signal_mem_write(DataPath.D_ACC)
            self._log_slot_acc = f"ISR save ACC -> [{ACC_SAVE_ADDR}]={dp.acc}"
        # ACC_ADDR
        elif s == 5:
            dp.signal_latch_ar(ACC_ADDR_SAVE_ADDR)
        elif s == 6:
            dp.signal_mem_write(DataPath.D_ACC_ADDR)
            self._log_slot_acc = (
                f"ISR save ACC_ADDR -> [{ACC_ADDR_SAVE_ADDR}]={dp.acc_addr}"
            )
        # NZVC
        elif s == 7:
            dp.signal_latch_ar(NZVC_SAVE_ADDR)
        elif s == 8:
            dp.signal_mem_write(DataPath.D_NZVC)
            self._log_slot_acc = f"ISR save NZVC -> [{NZVC_SAVE_ADDR}]=0b{dp.nzvc:04b}"
        # IVT fetch
        elif s == 9:
            dp.signal_latch_ar(IVT_INPUT_ADDR)
        elif s == 10:
            dp.signal_latch_dr_from_mem()
            self._log_slot_acc = f"ISR DR<-IVT[0]={dp.dr}"
        else:
            isr_addr = dp.dr
            self.signal_latch_ei(False)
            self.signal_latch_pc(isr_addr)
            self._isr_in_entry = False
            self._log_slot_acc = f"ISR jump @ {isr_addr}, EI<-0"
            return
        self.signal_step_inc()

    def _execute_step(self, op, arg, s):
        dp = self.dp

        if op == Opcode.HALT:
            raise StopIteration("HALT")

        if op == Opcode.LOAD_IMM:
            dp.signal_alu_op(
                DataPath.ALU_PASS_R, DataPath.R_FROM_IR, ir_arg=arg, update_vc=False
            )
            self.signal_step_reset()
            return
        if op == Opcode.INC_SP:
            dp.signal_inc_sp()
            self.signal_step_reset()
            return
        if op == Opcode.DEC_SP:
            dp.signal_dec_sp()
            self.signal_step_reset()
            return
        if op in self._ALU_UN:
            dp.signal_alu_op(self._ALU_UN[op], update_vc=False)
            self.signal_step_reset()
            return
        if op == Opcode.CLC:
            dp.signal_clc()
            self.signal_step_reset()
            return
        if op == Opcode.CLV:
            dp.signal_clv()
            self.signal_step_reset()
            return

        if op == Opcode.JUMP:
            self.signal_latch_pc(arg)
            return
        cond = self._branch_cond(op)
        if cond is not None:
            if cond:
                self.signal_latch_pc(arg)
            else:
                self.signal_step_reset()
            return

        if op == Opcode.CALL:
            return self._step_call(arg, s)
        if op == Opcode.CALL_ACC:
            return self._step_call(dp.acc, s)
        if op == Opcode.RET:
            return self._step_ret(s)
        if op == Opcode.IRET:
            return self._step_iret(s)

        if op == Opcode.LOAD:
            return self._step_load(arg, s)
        if op == Opcode.LOAD_ACC:
            return self._step_load(dp.acc, s)
        if op == Opcode.LOAD_SP:
            return self._step_load(dp.sp, s)
        if op == Opcode.STORE:
            return self._step_store(arg, s)
        if op == Opcode.STORE_SP:
            return self._step_store(dp.sp, s)
        if op == Opcode.STORE_IND:
            return self._step_store_ind(arg, s)
        if op in self._ALU_BIN:
            return self._step_alu_bin(op, arg, s)

        raise ValueError(f"Неизвестный опкод: {op}")

    def _branch_cond(self, op):
        dp = self.dp
        return {
            Opcode.BEQZ: dp.flag_zero,
            Opcode.BNEZ: not dp.flag_zero,
            Opcode.BGTZ: not dp.flag_zero and not dp.flag_neg,
            Opcode.BLTZ: dp.flag_neg,
            Opcode.BGEZ: not dp.flag_neg,
            Opcode.BLEZ: dp.flag_zero or dp.flag_neg,
            Opcode.BVS: dp.flag_overflow,
            Opcode.BVC: not dp.flag_overflow,
            Opcode.BCS: dp.flag_carry,
            Opcode.BCC: not dp.flag_carry,
        }.get(op)

    def _step_load(self, addr, s):
        dp = self.dp
        if self.superscalar and s == 1:
            if dp.shadow_addr is not None and dp.shadow_addr == addr:
                dp.signal_latch_acc_from_shadow()
                dp.acc_addr = addr
                self._log_slot_shadow = f"shadow-forward [{addr}]"
                self.signal_step_reset()
                return
            if dp.acc_addr == addr:
                self._log_slot_shadow = f"dead-load-elim [{addr}]"
                self.signal_step_reset()
                return

        if s == 1:
            dp.signal_latch_ar(addr)
            self.signal_step_inc()
            return
        if s == 2:
            dp.signal_latch_dr_from_mem()
            self.signal_step_inc()
            return
        if s == 3:
            dp.signal_alu_op(DataPath.ALU_PASS_R, DataPath.R_DR, update_vc=False)
            dp.acc_addr = addr
            self.signal_step_reset()
            return

    def _step_store(self, addr, s):
        dp = self.dp
        mmio = addr in (OUTPUT_ADDR, INPUT_ADDR)

        if self.superscalar and not mmio and s == 1:
            if dp.shadow_addr is None:
                dp.signal_latch_acc_sh_from_acc()
                dp.signal_latch_sh_addr(addr)
                dp.signal_latch_acc_addr(DataPath.AA_SH_ADDR)
                self._log_slot_shadow = f"deferred-store [{addr}]={dp.acc}"
                self.signal_step_reset()
                return
            if dp.shadow_addr == addr:
                dp.signal_latch_acc_sh_from_acc()
                self._log_slot_shadow = f"shadow-overwrite [{addr}]={dp.acc}"
                self.signal_step_reset()
                return

            old = dp.shadow_addr
            dp.signal_latch_ar(old)
            self._log_slot_shadow = f"parallel: AR<-SH_ADDR={old}"
            self.signal_step_inc()
            return
        if self.superscalar and not mmio and s == 2:
            dp.signal_mem_write(DataPath.D_AC_SH)
            dp.signal_latch_acc_sh_from_acc()
            dp.signal_latch_sh_addr(addr)
            dp.signal_latch_acc_addr(DataPath.AA_SH_ADDR)
            self._log_slot_shadow = (
                f"parallel: mem[{dp.ar}]<-AC_SH || store->[{addr}]={dp.acc}"
            )
            self.signal_step_reset()
            return

        if s == 1:
            dp.signal_latch_ar(addr)
            self.signal_step_inc()
            return
        if s == 2:
            dp.signal_mem_write(DataPath.D_ACC)
            if not mmio:
                dp.signal_latch_acc_addr(DataPath.AA_AR)
            self.signal_step_reset()
            return

    def _step_store_ind(self, arg, s):
        dp = self.dp
        if s == 1:
            dp.signal_latch_ar(arg)
            self.signal_step_inc()
            return
        if s == 2:
            dp.signal_latch_dr_from_mem()
            self._ind_target = dp.dr
            self.signal_step_inc()
            return
        return self._step_store(self._ind_target, s - 2)

    def _step_alu_bin(self, op, addr, s):
        dp = self.dp
        alu_op, upd_vc = self._ALU_BIN[op]
        if (
            self.superscalar
            and s == 1
            and dp.shadow_addr is not None
            and dp.shadow_addr == addr
        ):
            dp.signal_alu_op(alu_op, DataPath.R_AC_SH, update_vc=upd_vc)
            self._log_slot_shadow = f"alu-shadow-forward [{addr}]"
            self.signal_step_reset()
            return
        if s == 1:
            dp.signal_latch_ar(addr)
            self.signal_step_inc()
            return
        if s == 2:
            dp.signal_latch_dr_from_mem()
            self.signal_step_inc()
            return
        if s == 3:
            dp.signal_alu_op(alu_op, DataPath.R_DR, update_vc=upd_vc)
            self.signal_step_reset()
            return

    def _step_call(self, target, s):
        dp = self.dp
        if s == 1:
            dp.signal_dec_rsp()
            self.signal_step_inc()
            return
        if s == 2:
            dp.signal_latch_ar(dp.rsp)
            self.signal_step_inc()
            return
        if s == 3:
            dp.signal_mem_write(DataPath.D_FROM_PC, from_pc_value=self.pc)
            self.signal_step_inc()
            return
        if s == 4:
            self.signal_latch_pc(target)
            return

    def _step_ret(self, s):
        dp = self.dp
        if s == 1:
            dp.signal_latch_ar(dp.rsp)
            self.signal_step_inc()
            return
        if s == 2:
            dp.signal_latch_dr_from_mem()
            self.signal_step_inc()
            return
        if s == 3:
            ret = dp.dr
            dp.signal_inc_rsp()
            self.signal_latch_pc(ret)
            return

    def _step_iret(self, s):
        dp = self.dp
        if s == 1:
            if dp.shadow_addr is not None:
                dp.signal_latch_ar(dp.shadow_addr)
                self._log_slot_acc = f"IRET flush: AR<-SH_ADDR={dp.shadow_addr}"
            else:
                self._log_slot_acc = "IRET flush: (no shadow)"
        elif s == 2:
            if dp.shadow_addr is not None:
                dp.signal_mem_write(DataPath.D_AC_SH)
                self._log_slot_acc = f"IRET flush: mem[{dp.ar}]<-AC_SH={dp.ac_shadow}"
                dp.signal_clear_acc_sh()
                dp.signal_latch_sh_addr(None)
                dp.signal_latch_acc_addr(DataPath.AA_NONE)

        elif s == 3:
            dp.signal_latch_ar(ACC_SAVE_ADDR)
        elif s == 4:
            dp.signal_latch_dr_from_mem()
            dp.signal_alu_op(DataPath.ALU_PASS_R, DataPath.R_DR, update_vc=False)
            self._log_slot_acc = f"IRET ACC <- [{ACC_SAVE_ADDR}]={dp.acc}"
        elif s == 5:
            dp.signal_latch_ar(ACC_ADDR_SAVE_ADDR)
        elif s == 6:
            dp.signal_latch_dr_from_mem()
            dp.acc_addr = dp.dr
            self._log_slot_acc = (
                f"IRET ACC_ADDR <- [{ACC_ADDR_SAVE_ADDR}]={dp.acc_addr}"
            )
        elif s == 7:
            dp.signal_latch_ar(NZVC_SAVE_ADDR)
        elif s == 8:
            dp.signal_latch_dr_from_mem()
            dp.signal_latch_nzvc_from_dr()
            self._log_slot_acc = f"IRET NZVC <- 0b{dp.nzvc:04b}"
        elif s == 9:
            dp.signal_latch_ar(dp.rsp)
        elif s == 10:
            dp.signal_latch_dr_from_mem()
            self._log_slot_acc = f"IRET DR <- [SP]={dp.dr}"
        else:
            ret = dp.dr
            dp.signal_inc_rsp()
            self.signal_latch_ei(True)
            self.signal_latch_pc(ret)
            self._log_slot_acc = f"IRET ret PC <- {ret}, EI<-1"
            return
        self.signal_step_inc()

    @staticmethod
    def _fmt_instr(op, arg):
        if op in ControlUnit._ALWAYS_SHOW_ARG or arg != 0:
            return f"{op.value} {arg}"
        return op.value

    def _peek_next_opcode(self):
        if self.pc >= len(self.program_memory):
            return "<eop>"
        word = self._read_instr_word(self.pc)
        op_byte = (word >> 24) & 0xFF
        op = binary_to_opcode.get(op_byte)
        if op is None:
            return f"<bad opcode {op_byte:#04x}>"
        arg = to_signed24(word & ARG_MASK) if op in INSTRUCTIONS_WITH_ARG else 0
        return self._fmt_instr(op, arg)

    def __repr__(self):
        dp = self.dp
        sp = dp.sp

        shadow_info = ""
        if dp.shadow_addr is not None:
            shadow_info = f"  SHD:[{dp.shadow_addr}]={dp.ac_shadow}"
        if dp.acc_addr is not None:
            shadow_info += f"  ACC@[{dp.acc_addr}]"

        op = self._ir_opcode()
        ir_str = op.value if op is not None and self.ir != 0 else "-"
        ir_arg = self._ir_arg() if op in INSTRUCTIONS_WITH_ARG else 0
        rsp_used = (INITIAL_RSP - dp.rsp) // 4

        line1 = (
            f"TICK:{self._tick:5d}  PC:{self.pc:5d}/S{self.step}  "
            f"IR:{ir_str:<10s} ARG:{ir_arg:10d}  ACC:{dp.acc:12d}  "
            f"SP:{sp:5d}  RSP:{dp.rsp:5d}  NZVC=0b{dp.nzvc:04b}  "
            f"EI={int(self._interrupts_enabled)} IRQ={int(self._irq)}  "
            f"RS:{rsp_used:2d}{shadow_info}"
        )

        slot_a = self._log_slot_acc or ("(next) " + self._peek_next_opcode())
        slot_b = (
            f"  ||  SHADOW: {self._log_slot_shadow}" if self._log_slot_shadow else ""
        )
        line2 = f"  SLOT-A: {slot_a:<26s}{slot_b}"

        if sp < INITIAL_SP:
            tos = dp.data_memory[sp]
            extras = []
            for k in range(1, 4):
                addr = sp + k * 4
                if addr < INITIAL_SP:
                    extras.append(dp.data_memory[addr])
                else:
                    break
            extras_str = (
                "  [" + "  ".join(f"{v:6d}" for v in extras) + "]" if extras else ""
            )
            stack_line = f"  STACK:  TOS={tos:10d}{extras_str}"
        else:
            stack_line = "  STACK:  <empty>"

        io_line = "  IO:     " + "  ".join(self._log_io) if self._log_io else ""
        parts = [line1, line2, stack_line]
        if io_line:
            parts.append(io_line)
        return "\n".join(parts)
