from datapath import DataPath
from config import *
from isa import (
    Opcode,
    INSTRUCTIONS_WITH_ARG,
    OPCODE_BYTES,
    ARG_BYTES,
    binary_to_opcode,
    to_signed32,
)


class ControlUnit:
    """
    Hardwired Control Unit.

    Архитектура памяти команд:
      - program_memory - память с побайтовой адресацией.
      - PC хранит байтовый адрес.

    Регистры Control Unit:
      PC (32 бит) - счётчик команд (байтовый адрес);
      IR (8 бит) - регистр опкода, защёлкивается на FETCH_OP;
      DR (32 бит) - регистр операнда, защёлкивается на FETCH_ARG;
      RAR (32 бит) - return address register, временная защёлка
        для двухтактовых RET/IRET (между pop_return и защёлкиванием в PC);
      fetch_phase (2 бит) - состояние FSM выборки команды;
      step (2 бит) - шаг внутри стадии EXECUTE;
      IE (1 бит) - флаг разрешения прерываний;
      IP (1 бит) - флаг запроса прерывания.

    Стек возвратов аппаратный.
    Адрес обработчика прерывания читается из таблицы векторов прерываний в памяти данных.

    Цикл выборки команды (self.fetch_phase):
      0 = FETCH_OP: считываем 32 бита с program_memory[PC..PC+3], берём
                    старший байт как опкод -> IR; PC += 1; tick.
      1 = FETCH_ARG: считываем 32 бита с program_memory[PC..PC+3] как DR
                     (signed-32); PC += 4; tick.
      2 = EXECUTE: декодируем IR, исполняем; такты исполнения
                   управляются шагом self.step.
    Если опкод не требует аргумента, FETCH_ARG пропускается.

    PC mux:
      - PC + instr_size   (инкрементер CU, во время фазы fetch);
      - DR                (регистр CU; для JUMP/branches/CALL imm);
      - RAR (после pop)   (стек возвратов CU; для RET/IRET);
      - ACC               (единственный кросс-доменный сигнал DataPath->CU;
                           используется в CALL_ACC);
      - mem[IVT_INPUT_ADDR] (память данных; при диспетче прерывания).
    """

    def __init__(self, program: bytes, data_path: DataPath, superscalar: bool = True):
        self.program_memory: list[int] = list(program)

        self.dp = data_path
        self.superscalar = superscalar

        self.pc: int = 0
        self.step: int = 0
        self.ir: Opcode | None = None
        self.dr: int = 0
        self.fetch_phase: int = 0
        self.rar: int = 0
        self._interrupts_enabled: bool = False
        self._interrupt_pending: bool = False

        self.isr_saved_phase: int = 0
        self.isr_saved_step: int = 0
        self.isr_saved_ir: Opcode | None = None
        self.isr_saved_dr: int = 0
        self.isr_saved_rar: int = 0
        self.isr_saved_flags: tuple[bool, bool, bool, bool] = (False, False, False, False)

        self._return_stack: list[int] = []

        self._tick: int = 0

        self._log_slot_acc: str = ""
        self._log_slot_shadow: str = ""
        self._log_io: list[str] = []

        data_path._cu = self

    # Работа со стеком возвратов.

    def push_return(self, addr: int):
        if len(self._return_stack) >= RETURN_STACK_SIZE:
            raise OverflowError("Переполнение стека возвратов")
        self._return_stack.append(addr)

    def pop_return(self) -> int:
        if not self._return_stack:
            raise RuntimeError("Опустошение стека возвратов")
        return self._return_stack.pop()

    def _read_instr_word(self, byte_addr: int) -> int:
        pmem = self.program_memory
        b0 = pmem[byte_addr] if byte_addr < len(pmem) else 0
        b1 = pmem[byte_addr + 1] if byte_addr + 1 < len(pmem) else 0
        b2 = pmem[byte_addr + 2] if byte_addr + 2 < len(pmem) else 0
        b3 = pmem[byte_addr + 3] if byte_addr + 3 < len(pmem) else 0
        return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3

    def current_tick(self) -> int:
        return self._tick

    def tick(self):
        """Увеличить счётчик тактов на 1."""
        self._tick += 1

    # Управляющие сигналы CU.

    def signal_latch_pc(self, next_pc: int):
        """
        Защёлкнуть PC новым значением и сбросить машину выборки в FETCH_OP.
        """
        self.pc = next_pc
        self.fetch_phase = 0
        self.ir = None

    def signal_inc_pc(self, delta: int):
        """
        Инкремент PC на стадии fetch (PC += delta).
        """
        self.pc += delta

    def signal_latch_ir(self, op: Opcode):
        """IR <- op (защёлкивание опкода в конце стадии FETCH_OP)."""
        self.ir = op

    def signal_latch_dr(self, val: int):
        """DR <- val (защёлкивание операнда в конце стадии FETCH_ARG)."""
        self.dr = val

    def signal_latch_rar(self, val: int):
        """RAR <- val (защёлкивание адреса возврата после pop_return)."""
        self.rar = val

    def signal_set_phase(self, phase: int):
        """fetch_phase <- phase (явное переключение фазы выборки)."""
        self.fetch_phase = phase

    def signal_set_step(self, step: int):
        """step <- step (защёлкивание счётчика шагов внутри EXECUTE)."""
        self.step = step

    def signal_latch_ie(self, value: bool):
        """IE <- value. Триггер разрешения прерываний."""
        self._interrupts_enabled = value

    def signal_latch_ip(self, value: bool):
        """IP <- value. Триггер запроса прерывания."""
        self._interrupt_pending = value

    def signal_save_isr_context(self):
        """Сохранить микроархитектурный контекст в теневые регистры при входе в прерывание."""
        self.isr_saved_phase = self.fetch_phase
        self.isr_saved_step = self.step
        self.isr_saved_ir = self.ir
        self.isr_saved_dr = self.dr
        self.isr_saved_rar = self.rar
        self.isr_saved_flags = (
            self.dp.flag_zero,
            self.dp.flag_neg,
            self.dp.flag_carry,
            self.dp.flag_overflow,
        )

    def signal_restore_isr_context(self):
        """Восстановить микроархитектурный контекст из теневых регистров при выходе из прерывания."""
        self.fetch_phase = self.isr_saved_phase
        self.step = self.isr_saved_step
        self.ir = self.isr_saved_ir
        self.dr = self.isr_saved_dr
        self.rar = self.isr_saved_rar
        (
            self.dp.flag_zero,
            self.dp.flag_neg,
            self.dp.flag_carry,
            self.dp.flag_overflow,
        ) = self.isr_saved_flags

    def _branch(self, condition: bool, addr: int) -> bool:
        """
        Условный переход. Если условие истинно - защёлкивает PC в addr.
        Возвращает True, если переход совершён.
        """
        if condition:
            self.signal_latch_pc(addr)
            return True
        return False

    def _complete_instruction(self):
        """
        Завершение инструкции, у которой нет изменения потока управления.
        """
        self.signal_set_phase(0)
        self.signal_latch_ir(None)
        self.signal_set_step(0)

    def _flush_shadow(self):
        """
        Сбросить теневой регистр в память.
        """
        if self.dp.shadow_addr is not None:
            self._log_slot_shadow = (
                f"flush shadow -> [{self.dp.shadow_addr}]={self.dp.ac_shadow}"
            )
            self.dp.signal_shadow_flush()
            self.tick()

    # Опкоды, у которых операнд всегда показываем в логе.
    _ALWAYS_SHOW_ARG = frozenset({
        Opcode.LOAD_IMM, Opcode.LOAD, Opcode.STORE,
        Opcode.STORE_IND, Opcode.ADD, Opcode.SUB, Opcode.MUL,
        Opcode.DIV, Opcode.MOD, Opcode.AND, Opcode.OR, Opcode.XOR,
        Opcode.JUMP, Opcode.BEQZ, Opcode.BNEZ, Opcode.BGTZ, Opcode.BLTZ,
        Opcode.BGEZ, Opcode.BLEZ, Opcode.BVS, Opcode.BVC,
        Opcode.BCS, Opcode.BCC, Opcode.CALL,
    })

    @staticmethod
    def _fmt_instr(op: Opcode, arg) -> str:
        """Форматирует мнемонику инструкции: <opcode arg> или <opcode>."""
        if op in ControlUnit._ALWAYS_SHOW_ARG or arg != 0:
            return f"{op.value} {arg}"
        return op.value

    # Главный цикл моделирования.

    def process_next_tick(self):
        """
        Выполняет один такт симуляции.
        """
        dp = self.dp

        # Сбрасываем поля лога перед новым тактом.
        self._log_slot_acc = ""
        self._log_slot_shadow = ""
        self._log_io = []

        if self._interrupts_enabled and self._interrupt_pending:
            isr_addr = dp.signal_read_ivt_input()
            if isr_addr != 0:
                self.signal_latch_ip(False)
                self.signal_latch_ie(False)
                dp.signal_save_acc_to_isr_slot()
                self.signal_save_isr_context()
                
                self.push_return(self.pc)
                self.signal_latch_pc(isr_addr)
                logger.debug(
                    "INTERRUPT -> ISR @ %d (return addr saved, saved ACC=%d)",
                    isr_addr, dp.acc,
                )
                self.tick()
                return
            else:
                self.signal_latch_ip(False)

        # FETCH_OP
        if self.fetch_phase == 0:
            word = self._read_instr_word(self.pc)
            op_byte = (word >> 24) & 0xFF
            op_enum = binary_to_opcode.get(op_byte)
            if op_enum is None:
                raise ValueError(
                    f"Неизвестный опкод {op_byte:#04x} по адресу PC={self.pc}"
                )
            self.signal_latch_ir(op_enum)
            prev_pc = self.pc
            self.signal_inc_pc(OPCODE_BYTES)
            # Если у опкода нет аргумента -- сразу переходим в EXECUTE.
            self.signal_set_phase(1 if op_enum in INSTRUCTIONS_WITH_ARG else 2)
            self._log_slot_acc = (
                f"FETCH_OP  pc={prev_pc} word={word:#010x} -> IR={op_enum.value}"
            )
            self.tick()
            return

        # FETCH_ARG
        if self.fetch_phase == 1:
            word = self._read_instr_word(self.pc)
            self.signal_latch_dr(to_signed32(word))
            prev_pc = self.pc
            self.signal_inc_pc(ARG_BYTES)
            self.signal_set_phase(2)
            self._log_slot_acc = (
                f"FETCH_ARG pc={prev_pc} word={word:#010x} -> DR={self.dr}"
            )
            self.tick()
            return

        # EXECUTE
        op  = self.ir
        arg = self.dr if op in INSTRUCTIONS_WITH_ARG else 0

        self._log_slot_acc = self._fmt_instr(op, arg)
        if self.superscalar and dp.shadow_addr is not None:
            self._log_slot_shadow = f"shadow:[{dp.shadow_addr}]={dp.ac_shadow}"

        if op == Opcode.HALT:
            if self.superscalar:
                if self.dp.shadow_addr is not None:
                    self._log_slot_shadow = (
                        f"HALT flush shadow -> [{self.dp.shadow_addr}]={self.dp.ac_shadow}"
                    )
                self._flush_shadow()
            raise StopIteration("HALT")

        elif op == Opcode.LOAD:
            if self.superscalar and dp.shadow_addr is not None and dp.shadow_addr == arg:
                # Shadow forwarding: shadow содержит свежее значение для arg.
                dp.signal_latch_acc_from_shadow(arg)
                self._log_slot_shadow = f"shadow-forward [{arg}]={dp.ac_shadow}"
                self._complete_instruction()
            elif self.superscalar and dp.acc_addr == arg:
                # Dead load elimination: значение уже в ACC.
                self._log_slot_shadow = f"dead-load-elim [{arg}]"
                self._complete_instruction()
            elif self.superscalar and dp.shadow_addr is not None:
                # AC_SHADOW занят другим адресом -> параллельный flush+load.
                self._log_slot_shadow = (
                    f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || load->[{arg}]"
                )
                dp.signal_shadow_flush_and_load(arg)
                self._complete_instruction()
                self.tick()
            else:
                dp.signal_latch_acc_from_mem(arg)
                self._complete_instruction()
                self.tick()

        elif op == Opcode.LOAD_IMM:
            dp.signal_latch_acc_imm(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.LOAD_ACC:
            target_addr = dp.acc
            if self.superscalar and dp.shadow_addr is not None and target_addr == dp.shadow_addr:
                # Indirect dead-load-elim: значение уже в AC_SHADOW.
                dp.signal_latch_acc_from_shadow(None)
                self._log_slot_shadow = f"dead-load-elim indirect [{target_addr}]"
            else:
                dp.signal_latch_acc_indirect()
            self._complete_instruction()
            self.tick()

        elif op == Opcode.STORE:
            if self.superscalar:
                if dp.shadow_addr is None:
                    dp.signal_shadow_swap(arg)
                    self._log_slot_shadow = f"deferred-store [{arg}]"
                    self._complete_instruction()
                elif dp.shadow_addr == arg:
                    dp.signal_shadow_overwrite(arg)
                    self._log_slot_shadow = f"shadow-overwrite [{arg}]={dp.acc}"
                    self._complete_instruction()
                else:
                    self._log_slot_shadow = (
                        f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || "
                        f"store->[{arg}]={dp.acc}"
                    )
                    dp.signal_shadow_parallel_flush(arg)
                    self._complete_instruction()
                    self.tick()
            else:
                dp.signal_store(arg)
                self._complete_instruction()
                self.tick()

        elif op == Opcode.STORE_IND:
            target_addr = dp._mem_read(arg)
            if self.superscalar:
                if dp.shadow_addr is None:
                    dp.signal_shadow_swap(target_addr)
                    self._log_slot_shadow = f"deferred-store-ind [{target_addr}]"
                    self._complete_instruction()
                elif dp.shadow_addr == target_addr:
                    dp.signal_shadow_overwrite(target_addr)
                    self._log_slot_shadow = (
                        f"shadow-overwrite-ind [{target_addr}]={dp.acc}"
                    )
                    self._complete_instruction()
                else:
                    self._log_slot_shadow = (
                        f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || "
                        f"store-ind->[{target_addr}]={dp.acc}"
                    )
                    dp.signal_shadow_parallel_flush(target_addr)
                    self._complete_instruction()
                    self.tick()
            else:
                dp.signal_store_indirect(arg)
                self._complete_instruction()
                self.tick()

        elif op == Opcode.LOAD_SP:
            sp = dp.sp
            if self.superscalar and dp.shadow_addr is not None and dp.shadow_addr == sp:
                dp.signal_latch_acc_from_shadow(sp)
                self._log_slot_shadow = f"shadow-forward-sp [{sp}]={dp.ac_shadow}"
                self._complete_instruction()
            elif self.superscalar and dp.acc_addr == sp:
                self._log_slot_shadow = f"dead-load-elim-sp [{sp}]"
                self._complete_instruction()
            elif self.superscalar and dp.shadow_addr is not None:
                self._log_slot_shadow = (
                    f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || load-sp->[{sp}]"
                )
                dp.signal_shadow_flush_and_load(sp)
                self._complete_instruction()
                self.tick()
            else:
                dp.signal_latch_acc_from_sp()
                self._complete_instruction()
                self.tick()

        elif op == Opcode.STORE_SP:
            sp = dp.sp
            if self.superscalar:
                if dp.shadow_addr is None:
                    dp.signal_shadow_swap(sp)
                    self._log_slot_shadow = f"deferred-store-sp [{sp}]"
                    self._complete_instruction()
                elif dp.shadow_addr == sp:
                    dp.signal_shadow_overwrite(sp)
                    self._log_slot_shadow = f"shadow-overwrite-sp [{sp}]={dp.acc}"
                    self._complete_instruction()
                else:
                    self._log_slot_shadow = (
                        f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || "
                        f"store-sp->[{sp}]={dp.acc}"
                    )
                    dp.signal_shadow_parallel_flush(sp)
                    self._complete_instruction()
                    self.tick()
            else:
                dp.signal_store_to_sp()
                self._complete_instruction()
                self.tick()

        elif op == Opcode.INC_SP:
            dp.signal_inc_sp()
            self._complete_instruction()
            self.tick()

        elif op == Opcode.DEC_SP:
            dp.signal_dec_sp()
            self._complete_instruction()
            self.tick()

        # Сдвиги
        elif op == Opcode.SHIFTL:
            dp.signal_alu_shiftl()
            self._complete_instruction()
            self.tick()

        elif op == Opcode.SHIFTR:
            dp.signal_alu_shiftr()
            self._complete_instruction()
            self.tick()

        # Арифметика
        elif op == Opcode.ADD:
            dp.signal_alu_add(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.SUB:
            dp.signal_alu_sub(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.MUL:
            dp.signal_alu_mul(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.DIV:
            dp.signal_alu_div(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.MOD:
            dp.signal_alu_mod(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.INC:
            dp.signal_alu_inc()
            self._complete_instruction()
            self.tick()

        elif op == Opcode.DEC:
            dp.signal_alu_dec()
            self._complete_instruction()
            self.tick()

        # Логические операции
        elif op == Opcode.AND:
            dp.signal_alu_and(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.OR:
            dp.signal_alu_or(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.XOR:
            dp.signal_alu_xor(arg)
            self._complete_instruction()
            self.tick()

        elif op == Opcode.NOT:
            dp.signal_alu_not()
            self._complete_instruction()
            self.tick()

        # Флаги
        elif op == Opcode.CLC:
            dp.signal_clc()
            self._complete_instruction()
            self.tick()

        elif op == Opcode.CLV:
            dp.signal_clv()
            self._complete_instruction()
            self.tick()

        # Переходы. signal_latch_pc(...) сбрасывает fetch-FSM.
        elif op == Opcode.JUMP:
            if self.superscalar:
                self._flush_shadow()
            self.signal_latch_pc(arg)
            self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BEQZ:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(dp.flag_zero, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BNEZ:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(not dp.flag_zero, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BGTZ:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(not dp.flag_zero and not dp.flag_neg, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BLTZ:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(dp.flag_neg, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BGEZ:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(not dp.flag_neg, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BLEZ:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(dp.flag_zero or dp.flag_neg, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BVS:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(dp.flag_overflow, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BVC:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(not dp.flag_overflow, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BCS:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(dp.flag_carry, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.BCC:
            if self.superscalar:
                self._flush_shadow()
            if not self._branch(not dp.flag_carry, arg):
                self._complete_instruction()
            else:
                self.signal_set_step(0)
            self.tick()

        elif op == Opcode.CALL:
            if self.superscalar:
                self._flush_shadow()
            self.push_return(self.pc)
            self.signal_latch_pc(arg)
            self.tick()

        elif op == Opcode.CALL_ACC:
            if self.superscalar:
                self._flush_shadow()
            self.push_return(self.pc)
            self.signal_latch_pc(dp.acc)
            self.tick()

        elif op == Opcode.RET:
            if self.step == 0:
                if self.superscalar:
                    self._flush_shadow()
                self.signal_latch_rar(self.pop_return())
                self.signal_set_step(1)
                self.tick()
            else:  # step == 1
                self.signal_latch_pc(self.rar)
                self.signal_set_step(0)
                self.tick()

        elif op == Opcode.IRET:
            if self.step == 0:
                if self.superscalar:
                    self._flush_shadow()
                self.signal_latch_rar(self.pop_return())
                self.signal_set_step(1)
                self.tick()
            else:  # step == 1
                self.signal_latch_pc(self.rar)
                self.signal_restore_isr_context()
                dp.signal_restore_acc_from_isr_slot()
                self.signal_latch_ie(True)
                self.tick()

        else:
            raise ValueError(f"Неизвестный опкод: {op}")

    def trigger_interrupt(self):
        self.signal_latch_ip(True)

    def enable_interrupts(self):
        self.signal_latch_ie(True)

    def _peek_next_opcode(self) -> str:
        if self.pc >= len(self.program_memory):
            return "<eop>"
        op_byte = self.program_memory[self.pc]
        op_enum = binary_to_opcode.get(op_byte)
        if op_enum is None:
            return f"<bad opcode {op_byte:#04x}>"
        if op_enum in INSTRUCTIONS_WITH_ARG:
            word = self._read_instr_word(self.pc + OPCODE_BYTES)
            arg = to_signed32(word)
            return self._fmt_instr(op_enum, arg)
        return self._fmt_instr(op_enum, 0)

    def __repr__(self) -> str:
        dp = self.dp
        sp = dp.sp

        shadow_info = ""
        if dp.shadow_addr is not None:
            shadow_info = f"  SHD:[{dp.shadow_addr}]={dp.ac_shadow}"
        if dp.acc_addr is not None:
            shadow_info += f"  ACC@[{dp.acc_addr}]"

        phase_chr = (
            "FOP" if self.fetch_phase == 0
            else ("FAR" if self.fetch_phase == 1 else "EXE")
        )
        ir_str = self.ir.value if self.ir is not None else "-"

        line1 = (
            "TICK:{:5d}  PC:{:5d}/{:s}#{:d}  IR:{:<10s} DR:{:11d}"
            "  ACC:{:12d}  SP:{:5d}"
            "  N={:d} Z={:d} V={:d} C={:d}  IE={:d} IP={:d}  RS:{:2d}{}".format(
                self._tick,
                self.pc,
                phase_chr,
                self.step,
                ir_str,
                self.dr,
                dp.acc,
                sp,
                int(dp.flag_neg),
                int(dp.flag_zero),
                int(dp.flag_overflow),
                int(dp.flag_carry),
                int(self._interrupts_enabled),
                int(self._interrupt_pending),
                len(self._return_stack),
                shadow_info,
            )
        )

        if self._log_slot_acc:
            slot_a = self._log_slot_acc
        else:
            slot_a = "(next) " + self._peek_next_opcode()
        slot_b_part = f"  ||  SHADOW: {self._log_slot_shadow}" if self._log_slot_shadow else ""
        line2 = "  SLOT-A: {:<26s}{}".format(slot_a, slot_b_part)

        if sp < INITIAL_SP:
            tos = dp.data_memory[sp]
            extras = []
            for offset in range(1, 4):
                addr = sp + offset
                if addr < INITIAL_SP:
                    extras.append(dp.data_memory[addr])
                else:
                    break
            extras_str = "  [{}]".format(
                "  ".join(f"{v:6d}" for v in extras)
            ) if extras else ""
            stack_line = "  STACK:  TOS={:10d}{}".format(tos, extras_str)
        else:
            stack_line = "  STACK:  <empty>"

        io_line = ("  IO:     " + "  ".join(self._log_io)) if self._log_io else ""

        parts = [line1, line2, stack_line]
        if io_line:
            parts.append(io_line)
        return "\n".join(parts)
