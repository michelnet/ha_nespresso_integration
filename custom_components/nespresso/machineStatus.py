"""Decode status sensor characteristics exposed by a Nespresso machine."""

from __future__ import annotations

from .enums import (
    CapsuleMechanismJammed,
    DescalingNeeded,
    MachineState,
    SliderOpen,
    WaterHardness,
    WaterIsEmpty,
    WaterIsFresh,
)
from .machines import decode_pairing_key_state


class MachineStatus:
    """Decoder for the primary machine-status byte buffer."""

    def __init__(self, raw_data: bytes | bytearray) -> None:
        self.raw_data = raw_data

    def select_bits(self, start_bit: int, length: int) -> int:
        if start_bit < 0:
            raise ValueError("Start bit cannot be negative")
        if length <= 0:
            raise ValueError("Bit length must be positive")
        bit_count = len(self.raw_data) * 8
        if start_bit + length > bit_count:
            raise ValueError(f"Bits {start_bit}:{start_bit + length} exceed the status buffer")

        value = int.from_bytes(self.raw_data, byteorder="big")
        value >>= bit_count - start_bit - length
        return value & ((1 << length) - 1)

    def decode_water_is_empty(self) -> WaterIsEmpty:
        return WaterIsEmpty(self.raw_data[0] & 1)

    def decode_descaling_needed(self) -> DescalingNeeded:
        return DescalingNeeded((self.raw_data[0] >> 2) & 1)

    def decode_capsule_mechanism_jammed(self) -> CapsuleMechanismJammed:
        return CapsuleMechanismJammed((self.raw_data[0] >> 4) & 1)

    def decode_water_fresh(self) -> WaterIsFresh:
        return WaterIsFresh(self.raw_data[1] & 1)

    def decode(self) -> dict[str, str | int]:
        if len(self.raw_data) < 9:
            raise ValueError(
                f"Machine status must contain at least 9 bytes, got {len(self.raw_data)}"
            )
        return {
            "water_is_empty": self.decode_water_is_empty().name,
            "descaling_needed": self.decode_descaling_needed().name,
            "capsule_mechanism_jammed": self.decode_capsule_mechanism_jammed().name,
            "water_fresh": self.decode_water_fresh().name,
            "state": MachineState(self.select_bits(12, 4)).name,
            "descaling_counter": int.from_bytes(self.raw_data[6:9], byteorder="big"),
        }


class BaseDecode:
    """Dispatch characteristic data to the matching value decoder."""

    def __init__(self, name: str, format_type: str) -> None:
        self.name = name
        self.format_type = format_type

    def decode_data(self, raw_data: bytes | bytearray) -> dict[str, object]:
        if self.format_type == "state":
            return MachineStatus(raw_data).decode()
        if self.format_type == "caps_number":
            if not raw_data:
                raise ValueError("Capsule count cannot be empty")
            return {self.name: int.from_bytes(raw_data, byteorder="big")}
        if self.format_type == "pairing_status":
            if not raw_data:
                raise ValueError("Pairing status cannot be empty")
            pairing_key_state = decode_pairing_key_state(raw_data)
            if pairing_key_state == "UNDEFINED":
                raise ValueError("Pairing status is undefined")
            return {self.name: pairing_key_state == "PRESENT"}
        if self.format_type == "water_hardness":
            if len(raw_data) < 3:
                raise ValueError("Water-hardness data must contain at least three bytes")
            return {self.name: WaterHardness(raw_data[2]).name}
        if self.format_type == "slider":
            if not raw_data:
                raise ValueError("Slider data cannot be empty")
            return {self.name: SliderOpen((raw_data[0] >> 1) & 1).name}
        return {self.name: raw_data}
