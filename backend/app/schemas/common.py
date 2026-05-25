from enum import Enum


class StatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    PARTIAL = "partial"


class TimeRangeEnum(str, Enum):
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    SEVEN_DAYS = "7d"
    FIFTEEN_DAYS = "15d"
    ONE_MONTH = "1m"
