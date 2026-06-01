import json
from enum import Enum

"""
ISA - инструкции фиксированной длины 32 бита.
  - Биты 31..24 - опкод.
  - Биты 23..0  - знаковый аргумент (24 бита).
Память команд поддерживает побайтовую адресацию, PC всегда инкрементируется на 4.
"""


class Opcode(str, Enum):
    HALT = "halt"

    LOAD = "load"
    LOAD_IMM = "load_imm"
    LOAD_ACC = "load_acc"
    STORE = "store"
    STORE_IND = "store_ind"

    SHIFTL = "shiftl"
    SHIFTR = "shiftr"

    ADD = "add"
    ADD_IMM = "add_imm"
    SUB = "sub"
    SUB_IMM = "sub_imm"
    MUL = "mul"
    DIV = "div"
    MOD = "mod"
    INC = "inc"
    DEC = "dec"

    AND = "and"
    OR = "or"
    XOR = "xor"
    NOT = "not"

    CLC = "clc"
    CLV = "clv"

    JUMP = "jump"
    BEQZ = "beqz"
    BNEZ = "bnez"
    BGTZ = "bgtz"
    BLTZ = "bltz"
    BGEZ = "bgez"
    BLEZ = "blez"
    BVS = "bvs"
    BVC = "bvc"
    BCS = "bcs"
    BCC = "bcc"

    CALL = "call"
    CALL_ACC = "call_acc"
    RET = "ret"
    IRET = "iret"

    def __str__(self):
        return str(self.value)


opcode_to_binary = {op: i for i, op in enumerate(Opcode)}
binary_to_opcode = {i: op for i, op in enumerate(Opcode)}

INSTRUCTIONS_WITH_ARG = {
    Opcode.LOAD,
    Opcode.LOAD_IMM,
    Opcode.STORE,
    Opcode.STORE_IND,
    Opcode.ADD,
    Opcode.ADD_IMM,
    Opcode.SUB,
    Opcode.SUB_IMM,
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

INSTR_BYTES = 4
ARG_MASK = 0x00FFFFFF
ARG_SIGN = 0x00800000


def to_signed32(num: int) -> int:
    num &= 0xFFFFFFFF
    if num & 0x80000000:
        return num - 0x100000000
    return num


def to_signed24(num: int) -> int:
    num &= ARG_MASK
    if num & ARG_SIGN:
        return num - (1 << 24)
    return num


def to_arg24(num: int) -> int:
    return num & ARG_MASK


def encode_instr(opcode: "Opcode", arg: int = 0) -> int:
    """Закодировать инструкцию в 32-битное слово."""
    op_val = opcode_to_binary[opcode] & 0xFF
    return (op_val << 24) | to_arg24(arg)


def to_bytes(code: list[dict]) -> bytes:
    """
    Преобразует список инструкций в бинарный формат (по 4 байта на инструкцию).
    """
    binary_bytes = bytearray()

    for instr in code:
        word = encode_instr(instr["opcode"], instr.get("arg", 0))
        binary_bytes.extend(
            [
                (word >> 24) & 0xFF,
                (word >> 16) & 0xFF,
                (word >> 8) & 0xFF,
                word & 0xFF,
            ]
        )

    return bytes(binary_bytes)


def to_bytes_memory(memory: list[int]) -> bytes:
    """
    Преобразует память данных в бинарный формат.
    """
    binary_bytes = bytearray()

    for val in memory:
        binary_bytes.extend([(val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])

    return bytes(binary_bytes)


def to_hex_memory(memory: list[int]) -> str:
    """
    Создает отладочный дамп памяти.
    Формат: <address> - <value>
    """
    binary_memory = to_bytes_memory(memory)
    result = ["<addr>-<value>"]

    for i in range(0, len(binary_memory), 4):
        if i + 3 >= len(binary_memory):
            break

        word = (
            (binary_memory[i] << 24) | (binary_memory[i + 1] << 16) | (binary_memory[i + 2] << 8) | binary_memory[i + 3]
        )
        result.append(f"{(i // 4):04} - {word:08X}")

    return "\n".join(result)


def to_hex(code: list[dict]) -> str:
    """
    Отладочный текстовый дамп памяти команд.
    Формат: <byte_addr> - <HEXCODE> - <mnemonic>
    """
    binary_code = to_bytes(code)
    result = ["<addr>-<HEXCODE>-<mnemonic>"]

    i = 0
    while i < len(binary_code):
        if i + INSTR_BYTES > len(binary_code):
            break
        word = (binary_code[i] << 24) | (binary_code[i + 1] << 16) | (binary_code[i + 2] << 8) | binary_code[i + 3]
        opcode_bin = (word >> 24) & 0xFF
        opcode = binary_to_opcode.get(opcode_bin)
        if opcode is None:
            result.append(f"{i:04} - {word:08X} - UNKNOWN_{opcode_bin:02X}")
            i += INSTR_BYTES
            continue

        if opcode in INSTRUCTIONS_WITH_ARG:
            arg_bin = to_signed24(word & ARG_MASK)
            mnemonic = f"{opcode.value} {arg_bin}"
        else:
            mnemonic = opcode.value
        result.append(f"{i:04} - {word:08X} - {mnemonic}")
        i += INSTR_BYTES

    return "\n".join(result)


def from_bytes(binary_code: bytes) -> list[dict]:
    """
    Десериализация бинарника обратно в список словарей инструкций.
    """
    structured_code: list[dict] = []
    i = 0
    while i + INSTR_BYTES <= len(binary_code):
        word = (binary_code[i] << 24) | (binary_code[i + 1] << 16) | (binary_code[i + 2] << 8) | binary_code[i + 3]
        opcode_bin = (word >> 24) & 0xFF
        opcode = binary_to_opcode.get(opcode_bin)
        if opcode is None:
            i += INSTR_BYTES
            continue
        instr: dict = {"opcode": opcode}
        if opcode in INSTRUCTIONS_WITH_ARG:
            instr["arg"] = to_signed24(word & ARG_MASK)
        i += INSTR_BYTES
        structured_code.append(instr)
    return structured_code


def write_json(code_file: str, memory_file: str, code: list[dict], memory: list[int]):
    """Сериализация в JSON."""
    with open(code_file, "w", encoding="utf-8") as file:
        buf = [json.dumps(instr) for instr in code]
        file.write("[\n  " + ",\n  ".join(buf) + "\n]")
    with open(memory_file, "w", encoding="utf-8") as file:
        buf = [f'{{"{idx}": {json.dumps(val)}}}' for idx, val in enumerate(memory)]
        file.write("[\n  " + ",\n  ".join(buf) + "\n]")
