import logging

DATA_MEMORY_SIZE = 8192

IVT_INPUT_ADDR = 0
TEMP0_ADDR = 1
TEMP1_ADDR = 2
TEMP2_ADDR = 3
INPUT_ADDR = 4
OUTPUT_ADDR = 5
DATA_SP_ADDR = 6
ACC_SAVE_ADDR = 7
ACC_ADDR_SAVE_ADDR = 8
NZVC_SAVE_ADDR = 9
TEMP0_SAVE_ADDR = 10
TEMP1_SAVE_ADDR = 11
TEMP2_SAVE_ADDR = 12

INITIAL_SP = DATA_MEMORY_SIZE - 1

MASK32 = 0xFFFFFFFF
SIGN32 = 0x80000000


def to_signed32(val: int) -> int:
    val &= MASK32
    if val & SIGN32:
        return val - (1 << 32)
    return val


logger = logging.getLogger(__name__)
