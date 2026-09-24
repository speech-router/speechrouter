"""GENERATED from gateway providers/*/params.json — do not edit.
Regenerate: python3 scripts/gen_provider_params.py
"""
from typing import Literal, TypedDict

AssemblyaiParams = TypedDict(
    "AssemblyaiParams",
    {
        "end_of_turn_confidence_threshold": float,
        "min_turn_silence": int,
        "max_turn_silence": int,
        "vad_threshold": float,
        "continuous_partials": bool,
        "max_speakers": int,
        "language_detection": bool,
        "domain": Literal["medical-v1"],
        "prompt": str,
        "redact_pii": bool,
        "inactivity_timeout": int,
        "mode": Literal["max_accuracy", "balanced", "min_latency"],
    },
    total=False,
)
"""Provider-specific options for assemblyai/* models."""

AwsParams = TypedDict(
    "AwsParams",
    {},
    total=False,
)
"""Provider-specific options for aws/* models."""

AzureParams = TypedDict(
    "AzureParams",
    {
        "locales": list,
        "diarization": dict,
        "channels": list,
        "enhancedMode": dict,
    },
    total=False,
)
"""Provider-specific options for azure/* models."""

CartesiaParams = TypedDict(
    "CartesiaParams",
    {
        "turn_start_threshold": float,
        "turn_eager_end_threshold": float,
        "turn_end_threshold": float,
        "turn_end_timeout_ms": int,
        "min_volume": float,
        "max_silence_duration_secs": float,
    },
    total=False,
)
"""Provider-specific options for cartesia/* models."""

DeepgramParams = TypedDict(
    "DeepgramParams",
    {
        "smart_format": bool,
        "punctuate": bool,
        "endpointing": int,
        "utterance_end_ms": int,
        "vad_events": bool,
        "diarize_model": str,
        "multichannel": bool,
        "keywords": str,
        "eot_threshold": float,
        "eager_eot_threshold": float,
        "eot_timeout_ms": int,
    },
    total=False,
)
"""Provider-specific options for deepgram/* models."""

ElevenlabsParams = TypedDict(
    "ElevenlabsParams",
    {
        "commit_strategy": Literal["manual", "vad"],
        "vad_threshold": float,
        "vad_silence_threshold_secs": float,
        "secondary_languages": list,
        "no_verbatim": bool,
        "filter_background_audio": bool,
        "enable_logging": bool,
        "num_speakers": int,
        "timestamps_granularity": Literal["none", "word", "character"],
        "tag_audio_events": bool,
        "entity_detection": bool,
        "detect_speaker_roles": bool,
    },
    total=False,
)
"""Provider-specific options for elevenlabs/* models."""

GeminiParams = TypedDict(
    "GeminiParams",
    {
        "mode": Literal["VERBATIM", "SMART"],
        "languageCodes": list,
        "customVocabulary": list,
        "realtimeInputConfig": dict,
    },
    total=False,
)
"""Provider-specific options for gemini/* models."""

GoogleParams = TypedDict(
    "GoogleParams",
    {},
    total=False,
)
"""Provider-specific options for google/* models."""

GroqParams = TypedDict(
    "GroqParams",
    {
        "prompt": str,
        "temperature": float,
        "timestamp_granularities[]": Literal["word", "segment"],
    },
    total=False,
)
"""Provider-specific options for groq/* models."""

MetaParams = TypedDict(
    "MetaParams",
    {
        "mode": Literal["ENDPOINTING", "PUSH_TO_TALK", "DIARIZATION"],
        "languageBias": list,
        "keywords": list,
        "zdrOverride": bool,
        "sessionId": str,
    },
    total=False,
)
"""Provider-specific options for meta/* models."""

MistralParams = TypedDict(
    "MistralParams",
    {
        "context_bias": list,
        "timestamp_granularities": Literal["word", "segment"],
        "target_streaming_delay_ms": int,
    },
    total=False,
)
"""Provider-specific options for mistral/* models."""

OpenaiParams = TypedDict(
    "OpenaiParams",
    {
        "prompt": str,
        "temperature": float,
        "timestamp_granularities[]": Literal["word", "segment"],
        "chunking_strategy": str,
        "known_speaker_names[]": list,
        "known_speaker_references[]": list,
        "delay": Literal["minimal", "low", "medium", "high", "xhigh"],
        "turn_detection": dict,
    },
    total=False,
)
"""Provider-specific options for openai/* models."""

PalabraParams = TypedDict(
    "PalabraParams",
    {
        "translate_languages": str,
        "enable_filler_filter": bool,
    },
    total=False,
)
"""Provider-specific options for palabra/* models."""

SonioxParams = TypedDict(
    "SonioxParams",
    {
        "language_hints_strict": bool,
        "enable_language_identification": bool,
        "max_endpoint_delay_ms": int,
        "endpoint_sensitivity": float,
        "endpoint_latency_adjustment_level": int,
        "context": dict,
        "translation": dict,
        "client_reference_id": str,
    },
    total=False,
)
"""Provider-specific options for soniox/* models."""

SpeechmaticsParams = TypedDict(
    "SpeechmaticsParams",
    {
        "max_delay": float,
        "max_delay_mode": Literal["flexible", "fixed"],
        "speaker_diarization_config": dict,
        "additional_vocab": list,
        "enable_entities": bool,
        "punctuation_overrides": dict,
        "conversation_config": dict,
    },
    total=False,
)
"""Provider-specific options for speechmatics/* models."""

TelnyxParams = TypedDict(
    "TelnyxParams",
    {},
    total=False,
)
"""Provider-specific options for telnyx/* models."""

XaiParams = TypedDict(
    "XaiParams",
    {
        "endpointing": int,
        "smart_turn": float,
        "smart_turn_timeout": int,
        "filler_words": bool,
        "vad_threshold": float,
        "format": bool,
        "multichannel": bool,
        "audio_format": Literal["pcm", "mulaw", "alaw"],
        "sample_rate": int,
    },
    total=False,
)
"""Provider-specific options for xai/* models."""

PROVIDER_PARAMS = {
    "assemblyai": AssemblyaiParams,
    "aws": AwsParams,
    "azure": AzureParams,
    "cartesia": CartesiaParams,
    "deepgram": DeepgramParams,
    "elevenlabs": ElevenlabsParams,
    "gemini": GeminiParams,
    "google": GoogleParams,
    "groq": GroqParams,
    "meta": MetaParams,
    "mistral": MistralParams,
    "openai": OpenaiParams,
    "palabra": PalabraParams,
    "soniox": SonioxParams,
    "speechmatics": SpeechmaticsParams,
    "telnyx": TelnyxParams,
    "xai": XaiParams,
}
