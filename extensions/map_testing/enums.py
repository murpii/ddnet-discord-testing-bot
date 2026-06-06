import enum


class UploadState(enum.Enum):
    PENDING =  "⏳"
    UPLOADED = "🆙"
    ERROR =    "⚠️"
    DELETED =  "🗑️"


class SubmissionState(enum.Enum):
    PENDING =   "⌛"
    VALIDATED = "☑️"
    UPLOADED =  "🆙"
    PROCESSED = "✅"
    ERROR =     "⚠️"
    AWAITING =  "⏸️"


class ApprovalResult(enum.Enum):
    """Outcome of approving/force-accepting a #submit-maps submission."""
    CREATED =    enum.auto()  # testing channel built
    CONFLICT =   enum.auto()  # map name already taken -> declined
    BUSY =       enum.auto()  # already being processed, or no .map attachment
    UNVERIFIED = enum.auto()  # released-map list unavailable -> fail closed, retry later


class MapState(enum.Enum):
    TESTING =  ""
    RC =       "☑"
    WAITING =  "💤"
    READY =    "✅"
    DECLINED = "❌"
    RELEASED = "🆙"


class TestingChannelEvent(enum.Enum):
    """Events that drive a testing channel's MapState (see states.py)."""
    READY_VOTE =          enum.auto()
    MOVE_WAITING =        enum.auto()
    RESET =               enum.auto()
    RELEASE =             enum.auto()
    DECLINE =             enum.auto()
    AUTHOR_CLEAN_UPLOAD = enum.auto()
    AUTHOR_BUGGY_UPLOAD = enum.auto()


class MapServer(enum.Enum):
    Novice =    "👶"
    Moderate =  "🌸"
    Brutal =    "💪"
    Insane =    "💀"
    Dummy =     "♿"
    Oldschool = "👴"
    Solo =      "⚡"
    Race =      "🏁"
    Fun =       "🎉"