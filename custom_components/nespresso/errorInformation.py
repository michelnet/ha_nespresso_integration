"""Decode errors reported by a Nespresso machine."""

from dataclasses import dataclass
from enum import Enum


class ErrorCategory(Enum):
    DEVICE_ERROR_NONE = 0
    DEVICE_ERROR_POWER_LINE = 1
    DEVICE_ERROR_MMI = 2
    DEVICE_ERROR_MAIN_SYSTEM = 3
    DEVICE_ERROR_SENSOR = 4
    DEVICE_ERROR_ACTUATOR = 5
    DEVICE_ERROR_OTHER = 6

    @classmethod
    def from_byte(cls, value: int) -> ErrorCategory:
        """Decode the category stored in the upper nibble."""

        return cls((value >> 4) & 0x0F)


@dataclass(frozen=True, slots=True)
class ErrorInformation:
    error_number: int
    error_category: ErrorCategory
    error_sub_code: int

    def __str__(self) -> str:
        return (
            f"Error Number: {self.error_number}, "
            f"Error Category: {self.error_category.name}, "
            f"Error Sub-Code: {self.error_sub_code}"
        )


def to_error_information(byte_data: bytes | bytearray) -> ErrorInformation:
    """Decode the four-byte error-information header."""

    if len(byte_data) < 4:
        raise ValueError(f"Error information must contain at least 4 bytes, got {len(byte_data)}")

    return ErrorInformation(
        error_number=byte_data[0],
        error_category=ErrorCategory.from_byte(byte_data[1]),
        error_sub_code=int.from_bytes(byte_data[2:4], byteorder="big"),
    )
