"""Decode responses received from the Nespresso command characteristic."""

from enum import Enum


class ResponseCode(Enum):
    ACK = 32
    CONDITIONS_NOT_FULFILLED = 36
    OUT_OF_RANGE = 54
    INVALID = 255

    @classmethod
    def from_id(cls, value: int) -> ResponseCode:
        try:
            return cls(value)
        except ValueError:
            return cls.INVALID


class CommandResponse(Enum):
    DONE = "Done"
    OUT_OF_RANGE = "Out of Range"
    UNDEFINED = "Undefined"
    INVALID_STATE = "Invalid State"
    CAPSULE_CONTAINER_FULL = "Capsule Container Full"
    OBSTACLE_DETECTED = "Obstacle Detected"
    DESCALE_ON = "Descale On"
    LAST_ACTION_NOT_FINISHED = "Last Action Not Finished"
    NOT_ABORTABLE_ACTION = "Not Abortable Action"
    SLIDER_OPEN = "Slider Open"
    NO_PROGRAMMED_BREW_ACTIVE = "No Programmed Brew Active"
    PUMP_RUNNING = "Pump Running"
    MOTOR_RUNNING = "Motor Running"
    SLIDER_NOT_BEEN_OPENED = "Slider Not Been Opened"


_CONDITION_RESPONSES = {
    1: CommandResponse.INVALID_STATE,
    2: CommandResponse.INVALID_STATE,
    3: CommandResponse.CAPSULE_CONTAINER_FULL,
    4: CommandResponse.OBSTACLE_DETECTED,
    5: CommandResponse.DESCALE_ON,
    6: CommandResponse.LAST_ACTION_NOT_FINISHED,
    7: CommandResponse.NOT_ABORTABLE_ACTION,
    8: CommandResponse.SLIDER_OPEN,
    9: CommandResponse.NO_PROGRAMMED_BREW_ACTIVE,
    16: CommandResponse.PUMP_RUNNING,
    17: CommandResponse.MOTOR_RUNNING,
    18: CommandResponse.SLIDER_NOT_BEEN_OPENED,
}


def from_byte_buffer(byte_buffer: bytes | bytearray) -> CommandResponse:
    """Decode a command response buffer."""

    if len(byte_buffer) < 4:
        raise ValueError(f"Command response must contain at least 4 bytes, got {len(byte_buffer)}")

    response_code = ResponseCode.from_id(byte_buffer[3])
    if response_code is ResponseCode.ACK:
        return CommandResponse.DONE
    if response_code is ResponseCode.OUT_OF_RANGE:
        return CommandResponse.OUT_OF_RANGE
    if response_code is ResponseCode.CONDITIONS_NOT_FULFILLED:
        if len(byte_buffer) < 5:
            raise ValueError("Condition response is missing its reason byte")
        return from_condition_not_fulfilled(byte_buffer[4])
    return CommandResponse.UNDEFINED


def from_condition_not_fulfilled(value: int) -> CommandResponse:
    """Decode the reason for an unfulfilled command condition."""

    return _CONDITION_RESPONSES.get(value, CommandResponse.UNDEFINED)


# Compatibility for the original misspelled helper name.
from_condition_not_full_filled = from_condition_not_fulfilled
