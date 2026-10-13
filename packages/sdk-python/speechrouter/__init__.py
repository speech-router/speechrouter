"""SpeechRouter — one API for every speech model. https://speechrouter.ai"""

from .client import SpeechRouter
from .errors import SpeechRouterError
from .events import (
    AudioChunk,
    Cleared,
    Done,
    ErrorEvent,
    KeepAlive,
    ListenEvent,
    ProviderSwitched,
    SessionOpen,
    SpeechStarted,
    TextDelta,
    Transcript,
    UtteranceEnd,
    Word,
)
from .speak import SpeakStream
from .stream import ListenStream

__version__ = "0.1.0"

__all__ = [
    "AudioChunk",
    "Cleared",
    "Done",
    "ErrorEvent",
    "KeepAlive",
    "ListenEvent",
    "ListenStream",
    "ProviderSwitched",
    "SessionOpen",
    "SpeakStream",
    "SpeechRouter",
    "SpeechRouterError",
    "SpeechStarted",
    "TextDelta",
    "Transcript",
    "UtteranceEnd",
    "Word",
]

from . import provider_params as provider_params
