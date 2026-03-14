from enum import IntEnum, auto

class ErrorCode(IntEnum):
   NO_ERROR = 0
   INVALID_USAGE = auto()
   UNEXISTING_FILE_ERROR = auto()
