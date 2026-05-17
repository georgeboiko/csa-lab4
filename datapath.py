from config import *

class DataPath:
    """
    DataPath - реализованы сигналы защёлкивания значений, каждый сигнал - 1 такт.

    Стек возвратов реализован аппаратно в Control Unit.

    Регистры:
      acc          -- аккумулятор (32 бит)
      ac_shadow    -- теневой аккумулятор для суперскалярных операций (32 бит)
      shadow_addr  -- адрес отложенного store (None = shadow чист)
      acc_addr     -- адрес, значение которого сейчас в ACC (None = неизвестно).
                      Устанавливается при LOAD; сбрасывается при операциях с АЛУ,
                      прямой загрузке, косвенной адресации.
                      После deferred store (swap): acc_addr = old shadow_addr,
                      т.к. ACC получает значение, которое было загружено для того адреса.
                      Используется для dead load elimination: LOAD addr пропускается,
                      если acc_addr == addr (значение уже в ACC).
      sp           -- указатель стека данных
      flag_zero    -- флаг нуля       (Z)
      flag_neg     -- флаг знака      (N)
      flag_overflow-- флаг переполнения (V)
      flag_carry   -- флаг переноса   (C)
    """

    def __init__(self, data_memory: list[int]):
        self.data_memory = list(data_memory)
        self.data_memory += [0] * (DATA_MEMORY_SIZE - len(self.data_memory))

        self.output_buffer: list[int] = []

        self.acc: int = 0
        self.sp: int = INITIAL_SP

        self.ac_shadow: int = 0
        self.shadow_addr: int | None = None

        self.acc_addr: int | None = None

        self.flag_zero: bool = False
        self.flag_neg: bool = False
        self.flag_overflow: bool = False
        self.flag_carry: bool = False
        self._cu = None

    def _update_zn(self):
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)

    def _set_acc(self, val: int):
        self.acc = to_signed32(val)
        self._update_zn()

    def _mem_read(self, addr: int) -> int:
        """
        Чтение слова из памяти данных.

        AC_SHADOW forwarding: если shadow не пуст и addr == shadow_addr,
        возвращаем ac_shadow (отложенное значение), а не устаревшее значение
        из памяти. Это обеспечивает консистентность при чтении данных,
        ещё не записанных напрямую в память.

        Работа с вводом: симулятор заранее записывает символ в data_memory
        [INPUT_ADDR] по расписанию прерываний; ISR читает его командой
        LOAD INPUT_ADDR.
        """
        if self.shadow_addr is not None and addr == self.shadow_addr:
            return self.ac_shadow
        if addr == INPUT_ADDR:
            val = self.data_memory[INPUT_ADDR]
            ch = chr(val) if 32 <= val < 127 else f"\\x{val:02x}"
            if self._cu is not None:
                self._cu._log_io.append(f"IN={val}({ch!r})")
            return val
        return self.data_memory[addr]

    def _mem_write(self, addr: int, val: int):
        """Запись слова в память данных."""
        val = to_signed32(val)
        if addr == OUTPUT_ADDR:
            self.output_buffer.append(val)
            ch = chr(val & 0xFF) if 32 <= (val & 0xFF) < 127 else f"\\x{val & 0xFF:02x}"
            if self._cu is not None:
                self._cu._log_io.append(f"OUT={val}({ch!r})")
            return
        self.data_memory[addr] = val

    # Сигналы загрузки ACC

    def signal_latch_acc_from_mem(self, addr: int):
        """ACC <- mem[addr], acc_addr <- addr."""
        self._set_acc(self._mem_read(addr))
        self.acc_addr = addr

    def signal_latch_acc_imm(self, val: int):
        """ACC <- val (непосредственная загрузка)."""
        self._set_acc(val)
        self.acc_addr = None

    def signal_latch_acc_indirect(self):
        """ACC <- mem[ACC] (косвенная адресация)."""
        self._set_acc(self._mem_read(self.acc))
        self.acc_addr = None

    def signal_latch_acc_from_sp(self):
        """ACC <- mem[SP], acc_addr <- SP."""
        self._set_acc(self._mem_read(self.sp))
        self.acc_addr = self.sp

    def signal_latch_acc_from_shadow(self, addr: int | None):
        """
        ACC <- AC_SHADOW (shadow forwarding / dead-load-elim для shadow).
        acc_addr <- addr (адрес, по которому загружали; None для indirect).
        Память данных не задействуется -- значение берётся из AC_SHADOW.
        """
        self._set_acc(self.ac_shadow)
        self.acc_addr = addr

    # Сигналы сохранения / восстановления ACC при входе/выходе из ISR.

    def signal_save_acc_to_isr_slot(self):
        """mem[ISR_ACC_ADDR] <- ACC. Сохранение ACC при входе в ISR."""
        self._mem_write(ISR_ACC_ADDR, self.acc)

    def signal_restore_acc_from_isr_slot(self):
        """ACC <- mem[ISR_ACC_ADDR]. Восстановление ACC при выходе из ISR."""
        self._set_acc(self._mem_read(ISR_ACC_ADDR))
        self.acc_addr = ISR_ACC_ADDR

    def signal_read_ivt_input(self) -> int:
        """Прочитать адрес обработчика прерывания ввода из таблицы векторов."""
        return self._mem_read(IVT_INPUT_ADDR)

    # Сигналы суперскалярности.

    def signal_shadow_swap(self, addr: int):
        """
        Отложенный store: ACC <-> AC_SHADOW, shadow_addr = addr.
        Вместо записи в память ACC и shadow меняются местами.
        """
        old_shadow_addr = self.shadow_addr
        tmp = self.acc
        self._set_acc(self.ac_shadow)
        self.ac_shadow = tmp
        self.shadow_addr = addr
        self.acc_addr = old_shadow_addr

    def signal_shadow_overwrite(self, addr: int):
        """Перезапись отложенного store по тому же адресу."""
        self.ac_shadow = self.acc
        self.shadow_addr = addr

    def signal_shadow_flush(self):
        """Сброс shadow в память (одиночный flush, без операций с ACC)."""
        if self.shadow_addr is not None:
            if self._cu is not None:
                self._cu._log_io.append(f"FLUSH: [{self.shadow_addr}]={self.ac_shadow}")
            self._mem_write(self.shadow_addr, self.ac_shadow)
            self.shadow_addr = None
            self.ac_shadow = 0

    def signal_shadow_parallel_flush(self, new_addr: int):
        """
        Параллельный store: shadow -> shadow_addr И ACC -> new_addr.
        Обе записи выполняются за 1 такт (две независимые шины).
        """
        if self.shadow_addr is not None:
            if self._cu is not None:
                self._cu._log_io.append(
                    f"PARALLEL-FLUSH: [{self.shadow_addr}]={self.ac_shadow}, "
                    f"[{new_addr}]={self.acc}"
                )
            old_shadow_addr = self.shadow_addr
            old_shadow_val = self.ac_shadow
            self.shadow_addr = None
            self.ac_shadow = 0
            self._mem_write(old_shadow_addr, old_shadow_val)
        self._mem_write(new_addr, self.acc)

    def signal_shadow_flush_and_load(self, addr: int):
        """
        Параллельный flush + load: shadow -> shadow_addr И ACC <- mem[addr].
        Обе операции выполняются за 1 такт.
        """
        if self.shadow_addr is not None:
            if self._cu is not None:
                self._cu._log_io.append(
                    f"PARALLEL-FLUSH+LOAD: [{self.shadow_addr}]={self.ac_shadow}, "
                    f"ACC<-[{addr}]"
                )
            old_shadow_addr = self.shadow_addr
            old_shadow_val = self.ac_shadow
            self.shadow_addr = None
            self.ac_shadow = 0
            self._mem_write(old_shadow_addr, old_shadow_val)
        self._set_acc(self._mem_read(addr))
        self.acc_addr = addr

    # Сигналы записи в память.

    def signal_store(self, addr: int):
        """mem[addr] <- ACC."""
        self._mem_write(addr, self.acc)

    def signal_store_indirect(self, addr: int):
        """mem[mem[addr]] <- ACC."""
        target = self._mem_read(addr)
        self._mem_write(target, self.acc)

    def signal_store_to_sp(self):
        """mem[SP] <- ACC."""
        self._mem_write(self.sp, self.acc)

    # Сигналы SP.

    def signal_inc_sp(self):
        """SP <- SP + 1."""
        self.sp += 1

    def signal_dec_sp(self):
        """SP <- SP - 1."""
        self.sp -= 1

    # Сигналы АЛУ.

    def signal_alu_add(self, addr: int):
        old = self.acc
        operand = self._mem_read(addr)
        result = old + operand
        u_sum = (old & MASK32) + (operand & MASK32)
        self._set_acc(result)
        self.flag_overflow = bool(((old ^ self.acc) & (operand ^ self.acc)) & SIGN32)
        self.flag_carry = bool(u_sum >> 32)
        self.acc_addr = None

    def signal_alu_sub(self, addr: int):
        old = self.acc
        operand = self._mem_read(addr)
        result = old - operand
        self._set_acc(result)
        self.flag_overflow = bool(((old ^ operand) & (old ^ self.acc)) & SIGN32)
        self.flag_carry = (old & MASK32) < (operand & MASK32)
        self.acc_addr = None

    def signal_alu_mul(self, addr: int):
        operand = self._mem_read(addr)
        full = self.acc * operand
        self._set_acc(full)
        self.flag_overflow = (full != self.acc)
        self.flag_carry = bool((full >> 32) & MASK32)
        self.acc_addr = None

    def signal_alu_div(self, addr: int):
        operand = self._mem_read(addr)
        if operand == 0:
            raise ZeroDivisionError("Деление на ноль")
        self._set_acc(int(self.acc / operand))
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_mod(self, addr: int):
        operand = self._mem_read(addr)
        if operand == 0:
            raise ZeroDivisionError("Деление на ноль (mod)")
        self._set_acc(self.acc % operand)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_and(self, addr: int):
        self._set_acc(self.acc & self._mem_read(addr))
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_or(self, addr: int):
        self._set_acc(self.acc | self._mem_read(addr))
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_xor(self, addr: int):
        self._set_acc(self.acc ^ self._mem_read(addr))
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_not(self):
        self._set_acc(~self.acc)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_inc(self):
        self._set_acc(self.acc + 1)
        self.acc_addr = None

    def signal_alu_dec(self):
        self._set_acc(self.acc - 1)
        self.acc_addr = None

    def signal_alu_shiftl(self):
        self._set_acc(self.acc << 1)

    def signal_alu_shiftr(self):
        self._set_acc(self.acc >> 1)

    # Сигналы флагов.

    def signal_clc(self):
        self.flag_carry = False

    def signal_clv(self):
        self.flag_overflow = False
