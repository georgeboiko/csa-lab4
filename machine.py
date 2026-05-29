"""
Модель процессора, позволяющая выполнить машинный код, полученный из программы на языке Forth.

Модель включает в себя три основных компонента:

- DataPath - тракт данных: память данных, аккумулятор, стек данных, IO
- ControlUnit - hardwired блок управления: память команд, PC, стек возвратов
- Цикл симуляции
"""

import json
import sys

from config import (
    INPUT_ADDR,
    IVT_INPUT_ADDR,
    logger,
    logging,
    to_signed32,
)
from control_unit import ControlUnit
from datapath import DataPath


def simulation(
    code: bytes,
    data_memory: list[int],
    input_schedule: list[tuple[int, int]] | None = None,
    limit: int = 10_000_000,
    superscalar: bool = True,
) -> tuple[list[int], int]:
    dp = DataPath(data_memory)
    cu = ControlUnit(code, dp, superscalar=superscalar)
    logger.debug("Superscalar mode: %s", "ON" if superscalar else "OFF")

    # Читаем адрес ISR из таблицы векторов прерываний (mem[IVT_INPUT_ADDR]).
    isr_addr: int | None = dp.data_memory[IVT_INPUT_ADDR] or None
    if isr_addr is not None:
        cu.enable_interrupts()
        logger.debug("Trap mode: ISR addr=%d (from IVT[0])", isr_addr)

    _SEP = "─" * 72
    logger.debug("%s\n%s", _SEP, cu)
    try:
        while cu.current_tick() < limit:
            if (
                isr_addr is not None
                and input_schedule
                and cu.current_tick() >= input_schedule[0][0]
                and cu._interrupts_enabled
                and not cu._irq
            ):
                sched_tick, char = input_schedule.pop(0)
                dp.data_memory[INPUT_ADDR] = char
                ch = chr(char) if 32 <= char < 127 else f"\\x{char:02x}"
                logger.debug(
                    "  [TRAP] tick=%d (scheduled=%d) char=%d (%r) -> mem[%d], ISR@%d",
                    cu.current_tick(),
                    sched_tick,
                    char,
                    ch,
                    INPUT_ADDR,
                    isr_addr,
                )
                cu.trigger_interrupt()

            cu.process_next_tick()
            logger.debug("%s\n%s", _SEP, cu)
    except EOFError:
        logger.warning("Input buffer is empty!")
    except StopIteration:
        pass

    if cu.current_tick() >= limit:
        logger.warning("Limit exceeded! PC=%d", cu.pc)

    logger.info("output_buffer: %s", repr(cu.dp.output_buffer))

    # Дамп памяти данных
    sp_top = dp.sp
    dump_end = min(sp_top, 256)
    last_nonzero = -1
    for i in range(dump_end):
        if dp.data_memory[i] != 0:
            last_nonzero = i
    if last_nonzero >= 0:
        lines = ["data memory dump (addr: value):"]
        for i in range(last_nonzero + 1):
            lines.append(f"  [{i:4d}] = {dp.data_memory[i]}")
        logger.info("\n".join(lines))
    else:
        logger.info("data memory dump: all zeros (addr 0..%d)", dump_end - 1)

    return dp.output_buffer, cu.current_tick()


def main(code_file: str, memory_file: str, input_file: str, superscalar: bool = True):
    """
    machine.py <code.bin> <memory.bin> <input.txt> [--debug] [--no-superscalar]

    Входной файл — список пар [такт, код_символа].
    Если IVT[0] == 0 (нет ISR), входной файл игнорируется.

    Флаги:
      --debug           включить подробное логирование (уровень DEBUG)
      --no-superscalar  отключить суперскалярность
    """

    with open(code_file, "rb") as f:
        code = f.read()

    with open(memory_file, "rb") as f:
        raw = f.read()
    data_memory = []
    for i in range(0, len(raw), 4):
        if i + 3 < len(raw):
            word = (raw[i] << 24) | (raw[i + 1] << 16) | (raw[i + 2] << 8) | raw[i + 3]
            data_memory.append(to_signed32(word))

    isr_addr_from_ivt = data_memory[IVT_INPUT_ADDR] if data_memory else 0
    logger.info("IVT[0]=%d", isr_addr_from_ivt)

    input_schedule: list[tuple[int, int]] | None = None
    try:
        with open(input_file, encoding="utf-8") as f:
            content = f.read().strip()
        raw_schedule = json.loads(content)
        input_schedule = [(int(t), int(c)) for t, c in raw_schedule]
        input_schedule.sort(key=lambda x: x[0])
        logger.info("Loaded input schedule: %s", input_schedule)
    except FileNotFoundError:
        pass

    output_tokens, ticks = simulation(
        code=code,
        data_memory=data_memory,
        input_schedule=input_schedule,
        superscalar=superscalar,
    )

    output_str = "".join(chr(v & 0xFF) if 0 <= (v & 0xFF) < 128 else f"\\x{v & 0xFF:02x}" for v in output_tokens)
    print(output_str, end="")
    print(f"\noutput: {output_tokens}", file=sys.stderr)
    print(f"ticks: {ticks}", file=sys.stderr)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.WARNING,
        format="%(message)s",
    )
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    assert len(args) == 3, "Использование: machine.py <code.bin> <memory.bin> <input.txt> [--debug] [--no-superscalar]"
    main(args[0], args[1], args[2], superscalar="--no-superscalar" not in sys.argv)
