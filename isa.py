from enum import Enum
import json

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
    Opcode.JUMP, Opcode.BEQZ, Opcode.BNEZ, Opcode.BGTZ, Opcode.BLTZ, 
    Opcode.BGEZ, Opcode.BLEZ, Opcode.CALL
}

def to_signed24(num: int) -> int:
    if num & 0x800000:
        return num - 0x1000000
    return num

def to_arg24(num: int) -> int:
    return num & 0xFFFFFF


def to_bytes(code: list[dict]) -> bytes:
    """
    Преобразует список инструкций в бинарный формат.
    32 бита = Опкод (8 бит) | Аргумент (24 бита)
    """
    binary_bytes = bytearray()
    
    for instr in code:
        opcode_val = opcode_to_binary[instr["opcode"]]
        arg_val = instr.get("arg", 0)
        
        binary_instr = (opcode_val << 24) | to_arg24(arg_val)
 
        # Разбиваем на 4 байта (Big-Endian)
        binary_bytes.extend([
            (binary_instr >> 24) & 0xFF,
            (binary_instr >> 16) & 0xFF,
            (binary_instr >> 8) & 0xFF,
            binary_instr & 0xFF
        ])
        
    return bytes(binary_bytes)

def to_bytes_memory(memory: list[int]) -> bytes:
    """
    Преобразует память данных в бинарный формат.
    """
    binary_bytes = bytearray()
    
    for val in memory: 
        # Разбиваем на 4 байта (Big-Endian)
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
    Создает отладочный текстовый дамп.
    Формат: <address> - <HEXCODE> - <mnemonic>
    """
    binary_code = to_bytes(code)
    result = ["<addr>-<HEXCODE>-<mnemonic>"]

    for i in range(0, len(binary_code), 4):
        if i + 3 >= len(binary_code):
            break

        word = (binary_code[i] << 24) | (binary_code[i+1] << 16) | (binary_code[i+2] << 8) | binary_code[i+3]
        
        opcode_bin = (word >> 24) & 0xFF
        arg_bin = to_signed24(word & 0xFFFFFF)
        
        opcode = binary_to_opcode.get(opcode_bin)
        
        if opcode is None:
            mnemonic = f"UNKNOWN_{opcode_bin:02X}"
        else:
            if opcode in INSTRUCTIONS_WITH_ARG:
                mnemonic = f"{opcode.value} {arg_bin}"
            else:
                mnemonic = f"{opcode.value}"

        address = i // 4
        result.append(f"{address:04} - {word:08X} - {mnemonic}")

    return "\n".join(result)


def from_bytes(binary_code: bytes) -> list[dict]:
    """Десериализация бинарника обратно в список словарей инструкций."""
    structured_code = []
    
    for i in range(0, len(binary_code), 4):
        if i + 3 >= len(binary_code):
            break

        word = (binary_code[i] << 24) | (binary_code[i+1] << 16) | (binary_code[i+2] << 8) | binary_code[i+3]
        
        opcode_bin = (word >> 24) & 0xFF
        arg_bin = to_signed24(word & 0xFFFFFF)
        
        opcode = binary_to_opcode.get(opcode_bin)
        
        instr = {"opcode": opcode}
        if opcode in INSTRUCTIONS_WITH_ARG:
            instr["arg"] = arg_bin
            
        structured_code.append(instr)

    return structured_code


def write_json(filename: str, code: list[dict], memory: list[int]):
    """Сериализация в JSON."""
    with open(filename, "w", encoding="utf-8") as file:
        buf = [json.dumps(instr) for instr in code]
        file.write("[\n  " + ",\n  ".join(buf) + "\n]")
    with open(filename + ".mem", "w", encoding="utf-8") as file:
        buf = [json.dumps(val) for val in memory]
        file.write("[\n  " + ",\n  ".join(buf) + "\n]")