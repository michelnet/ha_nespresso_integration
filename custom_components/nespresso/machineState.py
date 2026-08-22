"""Decode the bit-packed Nespresso machine state."""

from __future__ import annotations

from .enums import MachineState


def default_machine_state_from(value: int) -> str:
    """Return a state name, falling back to ``UNKNOWN``."""

    try:
        return MachineState(value).name
    except ValueError:
        return MachineState.UNKNOWN.name


def get_boolean(byte_array: bytes | bytearray, bit_position: int) -> bool:
    """Return a bit using the protocol's least-significant-bit numbering."""

    if bit_position < 0:
        raise ValueError("Bit position cannot be negative")
    byte_index, bit_index = divmod(bit_position, 8)
    if byte_index >= len(byte_array):
        raise ValueError(f"Bit position {bit_position} exceeds a {len(byte_array)}-byte buffer")
    return bool(byte_array[byte_index] & (1 << bit_index))


def select_bits(byte_array: bytes | bytearray, start_bit: int, length: int) -> int:
    """Select bits using the protocol's most-significant-bit numbering."""

    if start_bit < 0:
        raise ValueError("Start bit cannot be negative")
    if length <= 0:
        raise ValueError("Bit length must be positive")
    bit_count = len(byte_array) * 8
    if start_bit + length > bit_count:
        raise ValueError(
            f"Bits {start_bit}:{start_bit + length} exceed a {len(byte_array)}-byte buffer"
        )

    value = int.from_bytes(byte_array, byteorder="big")
    value >>= bit_count - start_bit - length
    return value & ((1 << length) - 1)


def from_byte_array(byte_array: bytes | bytearray) -> dict[str, str | int | bool]:
    """Decode a machine-state characteristic value."""

    if len(byte_array) < 5:
        raise ValueError(f"Machine state must contain at least 5 bytes, got {len(byte_array)}")

    return {
        "MachineState": default_machine_state_from(select_bits(byte_array, 12, 4)),
        "CapsuleStockCounter": select_bits(byte_array, 17, 10),
        "ProgrammedBrewingActive": get_boolean(byte_array, 27),
        "ProgrammedBrewEventCounter": select_bits(byte_array, 28, 2),
        "CapsuleStockEventCounter": select_bits(byte_array, 30, 2),
        "BlockedMachineEventCounter": select_bits(byte_array, 32, 2),
    }
