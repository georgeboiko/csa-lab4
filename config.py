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
