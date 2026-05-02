from enum import Enum

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