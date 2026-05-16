"""
Модель процессора, позволяющая выполнить машинный код, полученный из программы на языке Forth.

Модель включает в себя три основных компонента:

- DataPath - тракт данных: память данных, аккумулятор, стек данных, IO
- ControlUnit - hardwired блок управления: память команд, PC, стек возвратов
- Цикл симуляции

Архитектура:
  - Аккумуляторная
  - Гарвардская (раздельные память команд и данных)
  - Hardwired control unit
  - Tick-accurate моделирование
  - Trap-based IO: прерывания по расписанию, ISR-адрес в mem[IVT_INPUT_ADDR]
  - Memory-mapped IO: addr 3 = INPUT, addr 4 = OUTPUT
  - Аппаратный стек возвратов
  - 2x суперскалярность по схеме AC_SHADOW:
      deferred store - STORE откладывается: ACC <-> AC_SHADOW, без записи в память
      dead load elim - LOAD addr пропускается если shadow_addr == addr (swap вместо чтения)
      parallel flush - когда shadow занят и нужен новый STORE: оба регистра пишутся
                       в память одновременно (1 такт = 2 записи)

Память данных:
    0 — адрес ISR ввода (0 если нет обработчика прерывания)
    1 — TEMP0
    2 — TEMP1
    3 — INPUT
    4 — OUTPUT
    5 — ISR_ACC - сохранение ACC при входе в ISR (восстанавливается при IRET)
    6..N   — переменные пользователя, строки
    ..8191 — стек данных (растёт вниз)
"""

import json
import logging
import sys

from isa import from_bytes

logger = logging.getLogger(__name__)

IVT_INPUT_ADDR = 0
INPUT_ADDR = 3
OUTPUT_ADDR = 4
ISR_ACC_ADDR = 5

DATA_MEMORY_SIZE = 8192

INITIAL_SP = DATA_MEMORY_SIZE - 1

RETURN_STACK_SIZE = 256

MASK32 = 0xFFFFFFFF
SIGN32 = 0x80000000


def to_signed32(val: int) -> int:
    val &= MASK32
    if val & SIGN32:
        return val - (1 << 32)
    return val

def simulation(
    code: list[dict],
    data_memory: list[int],
    input_schedule: list[tuple[int, int]] | None = None,
    limit: int = 10_000_000,
    superscalar: bool = True,
) -> tuple[list[int], int]:
    return [], 0


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
        code = from_bytes(f.read())

    with open(memory_file, "rb") as f:
        raw = f.read()
    data_memory = []
    for i in range(0, len(raw), 4):
        if i + 3 < len(raw):
            word = (raw[i] << 24) | (raw[i+1] << 16) | (raw[i+2] << 8) | raw[i+3]
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
        code = code,
        data_memory = data_memory,
        input_schedule = input_schedule,
        superscalar = superscalar,
    )

    output_str = "".join(
        chr(v & 0xFF) if 0 <= (v & 0xFF) < 128 else f"\\x{v & 0xFF:02x}"
        for v in output_tokens
    )
    print(output_str, end="")
    print(f"\noutput: {output_tokens}", file=sys.stderr)
    print(f"ticks: {ticks}", file=sys.stderr)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.WARNING,
        format="%(message)s",
    )
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    assert len(args) == 3, (
        "Использование: machine.py <code.bin> <memory.bin> <input.txt> [--debug] [--no-superscalar]"
    )
    main(*args, superscalar="--no-superscalar" not in sys.argv)
