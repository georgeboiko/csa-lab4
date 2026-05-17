from datapath import DataPath
from config import *
from isa import Opcode


class ControlUnit:
    """
    Hardwired CU.
    Реализует цикл fetch-decode-execute с точностью до такта.
    """

    def __init__(self, program: list[dict], data_path: DataPath, superscalar: bool = True):
        self.program = program
        self.dp = data_path
        self.superscalar = superscalar

        self.pc: int = 0
        self.step: int = 0  # микрошаг текущей инструкции

        # Состояние прерываний
        self._interrupts_enabled: bool = False
        self._interrupt_pending: bool = False
        self._isr_addr: int | None = None

        # Счётчик тактов
        self._tick: int = 0

        self._log_slot_acc: str = ""
        self._log_slot_shadow: str = ""
        self._log_io: list[str] = []

        data_path._cu = self

    def current_tick(self) -> int:
        return self._tick

    def tick(self):
        """Увеличить счётчик тактов на 1."""
        self._tick += 1

    def _branch(self, condition: bool, addr: int) -> bool:
        """Выполняет условный переход. Возвращает True если переход совершён."""
        if condition:
            self.pc = addr
            return True
        return False

    def signal_latch_pc(self, next_pc: int):
        """Защёлкнуть PC."""
        self.pc = next_pc

    # Опкоды, после которых AC_SHADOW запрещён
    _BRANCH_OPCODES = frozenset({
        Opcode.JUMP,
        Opcode.BEQZ, Opcode.BNEZ, Opcode.BGTZ, Opcode.BLTZ,
        Opcode.BGEZ, Opcode.BLEZ, Opcode.BVS, Opcode.BVC,
        Opcode.BCS, Opcode.BCC,
        Opcode.CALL, Opcode.CALL_ACC, Opcode.RET, Opcode.IRET,
        Opcode.HALT,
    })

    # Опкоды, у которых операнд всегда показываем
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

    def _flush_shadow(self):
        """
        Сбросить теневой регистр в память.
        Вызывается перед переходами, вызовами, возвратами и HALT,
        чтобы гарантировать запись отложенного store до изменения PC.
        """
        if self.dp.shadow_addr is not None:
            self._log_slot_shadow = f"flush shadow -> [{self.dp.shadow_addr}]={self.dp.ac_shadow}"
            self.dp.signal_shadow_flush()
            self.tick()

    def process_next_tick(self):
        """
        Выполнить один такт симуляции.
        Каждая инструкция разбита на шаги (self.step).
        """
        instr = self.program[self.pc]
        op    = instr["opcode"]
        arg   = instr.get("arg", 0)
        dp    = self.dp

        # Сбрасываем лог-поля перед новым тактом
        self._log_slot_acc = self._fmt_instr(op, arg)
        self._log_slot_shadow = ""
        self._log_io = []
        # Добавляем отладочную информацию о состоянии shadow
        if self.superscalar and dp.shadow_addr is not None:
            self._log_slot_shadow = f"shadow:[{dp.shadow_addr}]={dp.ac_shadow}"

        if op == Opcode.HALT:
            if self.superscalar:
                if self.dp.shadow_addr is not None:
                    self._log_slot_shadow = f"HALT flush shadow -> [{self.dp.shadow_addr}]={self.dp.ac_shadow}"
                self._flush_shadow()
            raise StopIteration("HALT")

        elif op == Opcode.LOAD:
            if self.superscalar and dp.shadow_addr is not None and dp.shadow_addr == arg:
                # Shadow forwarding: shadow содержит свежее значение для arg.
                # Копируем ac_shadow в ACC.
                dp._set_acc(dp.ac_shadow)
                dp.acc_addr = arg
                self._log_slot_shadow = f"shadow-forward [{arg}]={dp.ac_shadow}"
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
            elif self.superscalar and dp.acc_addr == arg:
                # Dead load elimination: значение уже в ACC, читать не нужно.
                self._log_slot_shadow = f"dead-load-elim [{arg}]"
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
            elif self.superscalar and dp.shadow_addr is not None:
                # AC_SHADOW занят другим адресом -> параллельный flush+load.
                self._log_slot_shadow = f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || load->[{arg}]"
                dp.signal_shadow_flush_and_load(arg)
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()
            else:
                # Обычная загрузка: ACC <- mem[arg], acc_addr = arg
                dp.signal_latch_acc_from_mem(arg)
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()

        elif op == Opcode.LOAD_IMM:
            # Такт 0: ACC <- arg
            dp.signal_latch_acc_imm(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.LOAD_ACC:
            target_addr = dp.acc
            if self.superscalar and dp.shadow_addr is not None and target_addr == dp.shadow_addr:
                dp._set_acc(dp.ac_shadow)
                self._log_slot_shadow = f"dead-load-elim indirect [{target_addr}]"
            else:
                dp.signal_latch_acc_indirect()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.STORE:
            if self.superscalar:
                if dp.shadow_addr is None:
                    # Shadow пуст → deferred store через swap.
                    dp.signal_shadow_swap(arg)
                    self._log_slot_shadow = f"deferred-store [{arg}]"
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                elif dp.shadow_addr == arg:
                    # STORE по тому же адресу → просто обновляем shadow.
                    dp.signal_shadow_overwrite(arg)
                    self._log_slot_shadow = f"shadow-overwrite [{arg}]={dp.acc}"
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                else:
                    # Shadow занят другим адресом -> parallel flush:
                    # shadow→mem[shadow_addr] И ACC→mem[arg] параллельно.
                    self._log_slot_shadow = f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || store->[{arg}]={dp.acc}"
                    dp.signal_shadow_parallel_flush(arg)
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                    self.tick()
            else:
                dp.signal_store(arg)
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()

        elif op == Opcode.STORE_IND:
            target_addr = dp._mem_read(arg)
            if self.superscalar:
                if dp.shadow_addr is None:
                    # Shadow пуст -> deferred store через swap.
                    dp.signal_shadow_swap(target_addr)
                    self._log_slot_shadow = f"deferred-store-ind [{target_addr}]"
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                elif dp.shadow_addr == target_addr:
                    # STORE по адресу, который уже в shadow -> перезаписываем shadow.
                    dp.signal_shadow_overwrite(target_addr)
                    self._log_slot_shadow = f"shadow-overwrite-ind [{target_addr}]={dp.acc}"
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                else:
                    # Shadow занят другим адресом -> parallel flush.
                    self._log_slot_shadow = f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || store-ind->[{target_addr}]={dp.acc}"
                    dp.signal_shadow_parallel_flush(target_addr)
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                    self.tick()
            else:
                # Обычная косвенная запись
                dp.signal_store_indirect(arg)
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()

        elif op == Opcode.LOAD_SP:
            sp = dp.sp
            if self.superscalar and dp.shadow_addr is not None and dp.shadow_addr == sp:
                # Shadow forwarding: shadow содержит свежее значение для SP.
                dp._set_acc(dp.ac_shadow)
                dp.acc_addr = sp
                self._log_slot_shadow = f"shadow-forward-sp [{sp}]={dp.ac_shadow}"
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
            elif self.superscalar and dp.acc_addr == sp:
                # Dead load elim: значение для SP уже в ACC.
                self._log_slot_shadow = f"dead-load-elim-sp [{sp}]"
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
            elif self.superscalar and dp.shadow_addr is not None:
                # Shadow занят другим адресом -> parallel flush+load.
                self._log_slot_shadow = f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || load-sp->[{sp}]"
                dp.signal_shadow_flush_and_load(sp)
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()
            else:
                dp.signal_latch_acc_from_sp()
                dp.acc_addr = sp
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()

        elif op == Opcode.STORE_SP:
            sp = dp.sp
            if self.superscalar:
                if dp.shadow_addr is None:
                    # Shadow пуст -> deferred store.
                    dp.signal_shadow_swap(sp)
                    self._log_slot_shadow = f"deferred-store-sp [{sp}]"
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                elif dp.shadow_addr == sp:
                    # STORE по тому же SP-адресу -> перезаписываем shadow.
                    dp.signal_shadow_overwrite(sp)
                    self._log_slot_shadow = f"shadow-overwrite-sp [{sp}]={dp.acc}"
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                else:
                    # Shadow занят другим адресом -> parallel flush.
                    self._log_slot_shadow = f"parallel flush->[{dp.shadow_addr}]={dp.ac_shadow} || store-sp->[{sp}]={dp.acc}"
                    dp.signal_shadow_parallel_flush(sp)
                    self.signal_latch_pc(self.pc + 1)
                    self.step = 0
                    self.tick()
            else:
                dp.signal_store_to_sp()
                self.signal_latch_pc(self.pc + 1)
                self.step = 0
                self.tick()

        elif op == Opcode.INC_SP:
            # Такт 0: SP <- SP + 1
            dp.signal_inc_sp()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.DEC_SP:
            # Такт 0: SP <- SP - 1
            dp.signal_dec_sp()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        # Сдвиги

        elif op == Opcode.SHIFTL:
            dp.signal_alu_shiftl()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.SHIFTR:
            dp.signal_alu_shiftr()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        # Арифметика

        elif op == Opcode.ADD:
            dp.signal_alu_add(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.SUB:
            dp.signal_alu_sub(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.MUL:
            dp.signal_alu_mul(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.DIV:
            dp.signal_alu_div(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.MOD:
            dp.signal_alu_mod(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.INC:
            dp.signal_alu_inc()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.DEC:
            dp.signal_alu_dec()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        # Логические операции

        elif op == Opcode.AND:
            dp.signal_alu_and(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.OR:
            dp.signal_alu_or(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.XOR:
            dp.signal_alu_xor(arg)
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.NOT:
            dp.signal_alu_not()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        # Флаги

        elif op == Opcode.CLC:
            dp.signal_clc()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.CLV:
            dp.signal_clv()
            self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        # Переходы — перед изменением PC сбрасываем shadow
        
        elif op == Opcode.JUMP:
            if self.superscalar:
                self._flush_shadow()
            self.signal_latch_pc(arg)
            self.step = 0
            self.tick()

        elif op == Opcode.BEQZ:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(dp.flag_zero, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BNEZ:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(not dp.flag_zero, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BGTZ:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(not dp.flag_zero and not dp.flag_neg, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BLTZ:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(dp.flag_neg, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BGEZ:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(not dp.flag_neg, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BLEZ:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(dp.flag_zero or dp.flag_neg, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BVS:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(dp.flag_overflow, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BVC:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(not dp.flag_overflow, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BCS:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(dp.flag_carry, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        elif op == Opcode.BCC:
            if self.superscalar:
                self._flush_shadow()
            jumped = self._branch(not dp.flag_carry, arg)
            if not jumped:
                self.signal_latch_pc(self.pc + 1)
            self.step = 0
            self.tick()

        # Вызов / возврат

        elif op == Opcode.CALL:
            if self.step == 0:
                # Такт 0: сбрасываем shadow, сохраняем адрес возврата
                if self.superscalar:
                    self._flush_shadow()
                dp.push_return(self.pc + 1)
                self.step = 1
                self.tick()
            elif self.step == 1:
                # Такт 1: переходим по адресу
                self.signal_latch_pc(arg)
                self.step = 0
                self.tick()

        elif op == Opcode.CALL_ACC:
            if self.step == 0:
                # Такт 0: сбрасываем shadow, сохраняем адрес возврата
                if self.superscalar:
                    self._flush_shadow()
                dp.push_return(self.pc + 1)
                self.step = 1
                self.tick()
            elif self.step == 1:
                # Такт 1: переходим по ACC
                self.signal_latch_pc(dp.acc)
                self.step = 0
                self.tick()

        elif op == Opcode.RET:
            if self.step == 0:
                # Такт 0: сбрасываем shadow, читаем адрес возврата
                if self.superscalar:
                    self._flush_shadow()
                self._ret_addr = dp.pop_return()
                self.step = 1
                self.tick()
            elif self.step == 1:
                # Такт 1: переходим по адресу возврата
                self.signal_latch_pc(self._ret_addr)
                self.step = 0
                self.tick()

        elif op == Opcode.IRET:
            if self.step == 0:
                # Такт 0: сбрасываем shadow, читаем адрес возврата
                if self.superscalar:
                    self._flush_shadow()
                self._ret_addr = dp.pop_return()
                self.step = 1
                self.tick()
            elif self.step == 1:
                # Такт 1: переходим по адресу возврата, восстанавливаем ACC, разрешаем прерывания
                self.signal_latch_pc(self._ret_addr)
                dp._set_acc(dp.data_memory[ISR_ACC_ADDR])
                self._interrupts_enabled = True
                self.step = 0
                self.tick()

        else:
            raise ValueError(f"Неизвестный опкод: {op}")

        # Обработка прерываний (после завершения инструкции)

        if self.step == 0 and self._interrupts_enabled and self._interrupt_pending and self._isr_addr is not None:
            self._interrupt_pending = False
            self._interrupts_enabled = False
            self.dp.data_memory[ISR_ACC_ADDR] = self.dp.acc
            self.dp.push_return(self.pc)
            self.signal_latch_pc(self._isr_addr)
            logger.debug("INTERRUPT -> ISR @ %d (return addr=%d, saved ACC=%d)",
                         self._isr_addr, self.pc, self.dp.data_memory[ISR_ACC_ADDR])

    def trigger_interrupt(self, isr_addr: int):
        """Устанавливает флаг прерывания."""
        self._isr_addr = isr_addr
        self._interrupt_pending = True

    def enable_interrupts(self):
        """Разрешить прерывания."""
        self._interrupts_enabled = True

    def __repr__(self) -> str:
        """
        Строковое представление состояния процессора для отладки.
        """
        dp = self.dp
        sp = dp.sp

        shadow_info = ""
        if dp.shadow_addr is not None:
            shadow_info = f"  SHD:[{dp.shadow_addr}]={dp.ac_shadow}"
        if dp.acc_addr is not None:
            shadow_info += f"  ACC@[{dp.acc_addr}]"
        line1 = (
            "TICK:{:5d}  PC:{:4d}/{:d}  ACC:{:12d}  SP:{:5d}"
            "  N={:d} Z={:d} V={:d} C={:d}  RS:{:2d}{}".format(
                self._tick,
                self.pc,
                self.step,
                dp.acc,
                sp,
                int(dp.flag_neg),
                int(dp.flag_zero),
                int(dp.flag_overflow),
                int(dp.flag_carry),
                len(self.dp._return_stack),
                shadow_info,
            )
        )

        if self._log_slot_acc:
            slot_a = self._log_slot_acc
        elif self.pc < len(self.program):
            nxt = self.program[self.pc]
            slot_a = "(next) " + self._fmt_instr(nxt["opcode"], nxt.get("arg", 0))
        else:
            slot_a = "(next) halt"
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
