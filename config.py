import logging

IVT_INPUT_ADDR        = 0
TEMP0_ADDR            = 1
TEMP1_ADDR            = 2
INPUT_ADDR            = 3
OUTPUT_ADDR           = 4
ACC_SAVE_ADDR         = 5
AC_SHADOW_SAVE_ADDR   = 6
ACC_ADDR_SAVE_ADDR    = 7
SHADOW_ADDR_SAVE_ADDR = 8
NZVC_SAVE_ADDR        = 9

DATA_MEMORY_SIZE = 8192

INITIAL_SP = DATA_MEMORY_SIZE - 1

INITIAL_RSP = DATA_MEMORY_SIZE // 2 - 1

MASK32 = 0xFFFFFFFF
SIGN32 = 0x80000000

def to_signed32(val: int) -> int:
    val &= MASK32
    if val & SIGN32:
        return val - (1 << 32)
    return val

logger = logging.getLogger(__name__)
