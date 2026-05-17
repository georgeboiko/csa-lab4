from enum import Enum
import json

"""
ISA - инструкции переменной длины:
  - Инструкция без аргумента: 1 байт = опкод.
  - Инструкция с аргументом : 5 байт = опкод + 32-битный операнд.
Память поддерживает байтовую адресацию.
"""

class Opcode(str, Enum):
    HALT = "halt"

    LOAD = "load"
    LOAD_IMM = "load_imm"
    LOAD_ACC = "load_acc"
    STORE = "store"
    STORE_IND = "store_ind"

    LOAD_SP = "load_sp"
    STORE_SP = "store_sp"
    INC_SP = "inc_sp"
    DEC_SP = "dec_sp"

    SHIFTL = "shiftl"
    SHIFTR = "shiftr"

    ADD = "add"
    SUB = "sub"
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
    Opcode.LOAD, Opcode.LOAD_IMM, Opcode.STORE, Opcode.STORE_IND,
    Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD,
    Opcode.AND, Opcode.OR, Opcode.XOR,
    Opcode.JUMP, Opcode.BEQZ, Opcode.BNEZ, Opcode.BGTZ, Opcode.BLTZ,
    Opcode.BGEZ, Opcode.BLEZ, Opcode.BVS, Opcode.BVC, Opcode.BCS, Opcode.BCC,
    Opcode.CALL,
}

OPCODE_BYTES = 1
ARG_BYTES = 4
INSTR_BYTES_MAX = OPCODE_BYTES + ARG_BYTES


def instr_size_bytes(opcode: "Opcode") -> int:
    """Длина инструкции в байтах с учётом наличия аргумента."""
    return INSTR_BYTES_MAX if opcode in INSTRUCTIONS_WITH_ARG else OPCODE_BYTES


def to_signed32(num: int) -> int:
    num &= 0xFFFFFFFF
    if num & 0x80000000:
        return num - 0x100000000
    return num

def to_arg32(num: int) -> int:
    return num & 0xFFFFFFFF


def to_bytes(code: list[dict]) -> bytes:
    """
    Преобразует список инструкций в бинарный формат.
    """
    binary_bytes = bytearray()

    for instr in code:
        opcode = instr["opcode"]
        opcode_val = opcode_to_binary[opcode]
        binary_bytes.append(opcode_val & 0xFF)

        if opcode in INSTRUCTIONS_WITH_ARG:
            arg_val = to_arg32(instr.get("arg", 0))
            binary_bytes.extend([
                (arg_val >> 24) & 0xFF,
                (arg_val >> 16) & 0xFF,
                (arg_val >> 8) & 0xFF,
                arg_val & 0xFF,
            ])

    return bytes(binary_bytes)

def to_bytes_memory(memory: list[int]) -> bytes:
    """
    Преобразует память данных в бинарный формат.
    """
    binary_bytes = bytearray()
    
    for val in memory: 
        binary_bytes.extend([
            (val >> 24) & 0xFF,
            (val >> 16) & 0xFF,
            (val >> 8) & 0xFF,
            val & 0xFF
        ])
        
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

        word = (binary_memory[i] << 24) | (binary_memory[i+1] << 16) | (binary_memory[i+2] << 8) | binary_memory[i+3]
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
        opcode_bin = binary_code[i]
        opcode = binary_to_opcode.get(opcode_bin)
        if opcode is None:
            result.append(f"{i:04} - {opcode_bin:02X} - UNKNOWN_{opcode_bin:02X}")
            i += 1
            continue

        if opcode in INSTRUCTIONS_WITH_ARG:
            if i + INSTR_BYTES_MAX > len(binary_code):
                break
            arg_unsigned = (
                (binary_code[i + 1] << 24)
                | (binary_code[i + 2] << 16)
                | (binary_code[i + 3] << 8)
                | binary_code[i + 4]
            )
            arg_bin = to_signed32(arg_unsigned)
            mnemonic = f"{opcode.value} {arg_bin}"
            result.append(f"{i:04} - {opcode_bin:02X}{arg_unsigned:08X} - {mnemonic}")
            i += INSTR_BYTES_MAX
        else:
            result.append(f"{i:04} - {opcode_bin:02X}         - {opcode.value}")
            i += OPCODE_BYTES

    return "\n".join(result)


def from_bytes(binary_code: bytes) -> list[dict]:
    """
    Десериализация бинарника обратно в список словарей инструкций
    (для отладочного вывода / unit-тестов). Полностью обходит variable-length
    кодирование.
    """
    structured_code: list[dict] = []
    i = 0
    while i < len(binary_code):
        opcode_bin = binary_code[i]
        opcode = binary_to_opcode.get(opcode_bin)
        if opcode is None:
            i += 1
            continue
        instr: dict = {"opcode": opcode}
        if opcode in INSTRUCTIONS_WITH_ARG:
            if i + INSTR_BYTES_MAX > len(binary_code):
                break
            arg_unsigned = (
                (binary_code[i + 1] << 24)
                | (binary_code[i + 2] << 16)
                | (binary_code[i + 3] << 8)
                | binary_code[i + 4]
            )
            instr["arg"] = to_signed32(arg_unsigned)
            i += INSTR_BYTES_MAX
        else:
            i += OPCODE_BYTES
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