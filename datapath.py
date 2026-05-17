from config import *

class DataPath:
    """
    DataPath - реализованы сигналы защёлкивания значений, каждый сигнал - 1 такт.

    Стек возвратов реализован аппаратно.

    Регистры:
      acc - аккумулятор 
      ac_shadow - теневой аккумулятор для суперскалярных операций
      shadow_addr - адрес отложенного store (None = shadow чист)
      acc_addr - адрес, значение которого сейчас в ACC (None = неизвестно).
                 Устанавливается при LOAD; сбрасывается при операциях с АЛУ,
                 прямой загрузке, косвенной адресации.
                 После deferred store (swap): acc_addr = old shadow_addr,
                 т.к. ACC получает значение, которое было загружено для того адреса.
                 Используется для dead load elimination: LOAD addr пропускается,
                 если acc_addr == addr (значение уже в ACC).
      sp - указатель стека данных
      flag_zero - флаг нуля
      flag_neg - флаг знака
      flag_overflow - флаг переполнения
      flag_carry - флаг переноса
    """

    def __init__(self, data_memory: list[int]):
        self.data_memory = list(data_memory)
        self.data_memory += [0] * (DATA_MEMORY_SIZE - len(self.data_memory))

        self._return_stack: list[int] = []

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

    def push_return(self, addr: int):
        if len(self._return_stack) >= RETURN_STACK_SIZE:
            raise OverflowError("Переполнение стека возвратов")
        self._return_stack.append(addr)

    def pop_return(self) -> int:
        if not self._return_stack:
            raise RuntimeError("Опустошение стека возвратов")
        return self._return_stack.pop()

    def _set_acc(self, val: int):
        """Устанавливает ACC и обновляет флаги Z и N."""
        self.acc = to_signed32(val)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)

    def _mem_read(self, addr: int) -> int:
        """
        Читает слово из памяти данных.

        AC_SHADOW forwarding: если shadow не пуст и addr == shadow_addr,
        возвращаем ac_shadow (отложенное значение), а не устаревшее значение из памяти.
        Это обеспечивает консистентность при чтении данных, еще не записаннях(напрямую) в память.

        Работа с вводом: симулятор заранее записывает символ в data_memory[INPUT_ADDR]
        по расписанию прерываний; ISR читает его командой LOAD INPUT_ADDR.
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
        """Записывает слово в память данных."""
        val = to_signed32(val)
        if addr == OUTPUT_ADDR:
            self.output_buffer.append(val)
            ch = chr(val & 0xFF) if 32 <= (val & 0xFF) < 127 else f"\\x{val & 0xFF:02x}"
            if self._cu is not None:
                self._cu._log_io.append(f"OUT={val}({ch!r})")
            return
        self.data_memory[addr] = val

    # Сигналы защелкивания

    def signal_latch_acc_from_mem(self, addr: int):
        """ACC <- mem[addr]"""
        self._set_acc(self._mem_read(addr))
        self.acc_addr = addr

    def signal_latch_acc_imm(self, val: int):
        """ACC <- val (непосредственная загрузка)"""
        self._set_acc(val)
        self.acc_addr = None

    def signal_latch_acc_indirect(self):
        """ACC <- mem[ACC] (косвенная адресация)"""
        self._set_acc(self._mem_read(self.acc))
        self.acc_addr = None

    def signal_latch_acc_from_sp(self):
        """ACC <- mem[SP]"""
        self._set_acc(self._mem_read(self.sp))
        self.acc_addr = None

    # сигналы по суперскалярности

    def signal_shadow_swap(self, addr: int):
        """
        Отложенный store: ACC <-> AC_SHADOW, shadow_addr = addr.
        Вместо записи в память ACC и shadow меняются местами.
        """
        old_shadow_addr = self.shadow_addr
        self.acc, self.ac_shadow = self.ac_shadow, self.acc
        self.shadow_addr = addr
        self.acc_addr = old_shadow_addr
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)

    def signal_shadow_flush(self):
        """
        Сброс shadow в память.
        """
        if self.shadow_addr is not None:
            if self._cu is not None:
                self._cu._log_io.append(f"FLUSH: [{self.shadow_addr}]={self.ac_shadow}")
            self._mem_write(self.shadow_addr, self.ac_shadow)
            self.shadow_addr = None
            self.ac_shadow = 0

    def signal_shadow_parallel_flush(self, new_addr: int):
        """
        Параллельный сброс: ACC -> new_addr И shadow -> shadow_addr.
        Обе записи выполняются за 1 такт.
        """
        if self.shadow_addr is not None:
            # Параллельная запись: оба значения пишутся одновременно
            if self._cu is not None:
                self._cu._log_io.append(f"PARALLEL-FLUSH: [{self.shadow_addr}]={self.ac_shadow}, [{new_addr}]={self.acc}")
            self.data_memory[self.shadow_addr] = to_signed32(self.ac_shadow)
            self.shadow_addr = None
            self.ac_shadow = 0
        
        # Вторая запись (ACC -> new_addr)
        if new_addr == OUTPUT_ADDR:
            self.output_buffer.append(self.acc)
            ch = chr(self.acc & 0xFF) if 32 <= (self.acc & 0xFF) < 127 else f"\\x{self.acc & 0xFF:02x}"
            if self._cu is not None:
                self._cu._log_io.append(f"OUT={self.acc}({ch!r})")
        else:
            self.data_memory[new_addr] = to_signed32(self.acc)

    def signal_store(self, addr: int):
        """mem[addr] <- ACC"""
        self._mem_write(addr, self.acc)

    def signal_store_indirect(self, addr: int):
        """mem[mem[addr]] <- ACC"""
        target = self._mem_read(addr)
        self._mem_write(target, self.acc)

    def signal_store_to_sp(self):
        """mem[SP] <- ACC"""
        self._mem_write(self.sp, self.acc)

    def signal_inc_sp(self):
        """SP <- SP + 1"""
        self.sp += 1

    def signal_dec_sp(self):
        """SP <- SP - 1"""
        self.sp -= 1

    # Сигналы АЛУ

    def signal_alu_add(self, addr: int):
        """ACC <- ACC + mem[addr]"""
        old = self.acc
        operand = self._mem_read(addr)
        result = old + operand
        self.acc = to_signed32(result)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = bool(((old ^ self.acc) & (operand ^ self.acc)) & SIGN32)
        self.flag_carry = bool((result >> 32) & 1) if result >= 0 else False
        self.acc_addr = None

    def signal_alu_sub(self, addr: int):
        """ACC <- ACC - mem[addr]"""
        old = self.acc
        operand = self._mem_read(addr)
        result = old - operand
        self.acc = to_signed32(result)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = bool(((old ^ operand) & (old ^ self.acc)) & SIGN32)
        self.flag_carry = (result < -(1 << 31))
        self.acc_addr = None

    def signal_alu_mul(self, addr: int):
        """ACC <- ACC * mem[addr] (пока 32-битный результат, overflow если не влезает)"""
        operand = self._mem_read(addr)
        full = self.acc * operand
        self.acc = to_signed32(full)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = (full != self.acc)
        self.flag_carry = bool((full >> 32) & MASK32)
        self.acc_addr = None

    def signal_alu_div(self, addr: int):
        """ACC <- ACC / mem[addr]"""
        operand = self._mem_read(addr)
        if operand == 0:
            raise ZeroDivisionError("Деление на ноль")
        self.acc = to_signed32(int(self.acc / operand))
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_mod(self, addr: int):
        """ACC <- ACC % mem[addr]"""
        operand = self._mem_read(addr)
        if operand == 0:
            raise ZeroDivisionError("Деление на ноль (mod)")
        self.acc = to_signed32(self.acc % operand)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_and(self, addr: int):
        """ACC <- ACC & mem[addr]"""
        self.acc = to_signed32(self.acc & self._mem_read(addr))
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_or(self, addr: int):
        """ACC <- ACC | mem[addr]"""
        self.acc = to_signed32(self.acc | self._mem_read(addr))
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_xor(self, addr: int):
        """ACC <- ACC ^ mem[addr]"""
        self.acc = to_signed32(self.acc ^ self._mem_read(addr))
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_not(self):
        """ACC <- ~ACC"""
        self.acc = to_signed32(~self.acc)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.flag_overflow = False
        self.flag_carry = False
        self.acc_addr = None

    def signal_alu_inc(self):
        """ACC <- ACC + 1"""
        self.acc = to_signed32(self.acc + 1)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.acc_addr = None

    def signal_alu_dec(self):
        """ACC <- ACC - 1"""
        self.acc = to_signed32(self.acc - 1)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)
        self.acc_addr = None

    def signal_alu_shiftl(self):
        """ACC <- ACC << 1"""
        self.acc = to_signed32(self.acc << 1)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)

    def signal_alu_shiftr(self):
        """ACC <- ACC >> 1"""
        self.acc = to_signed32(self.acc >> 1)
        self.flag_zero = (self.acc == 0)
        self.flag_neg  = (self.acc < 0)

    def signal_clc(self):
        """Сброс флага переноса"""
        self.flag_carry = False

    def signal_clv(self):
        """Сброс флага переполнения"""
        self.flag_overflow = False