"""STT adapter factory."""

from tempa.meet.stt.base import STTStreamingAdapter
from tempa.meet.stt.deepgram import DeepgramStreamingAdapter
from tempa.meet.stt.groq_whisper import GroqWhisperAdapter

_REGISTRY: dict[str, type[STTStreamingAdapter]] = {
    "groq": GroqWhisperAdapter,
    "whisper": GroqWhisperAdapter,
    "deepgram": DeepgramStreamingAdapter,
}


def register_stt(name: str, cls: type[STTStreamingAdapter]) -> None:
    _REGISTRY[name] = cls


def create_stt_adapter(provider: str, **kwargs) -> STTStreamingAdapter:
    cls = _REGISTRY.get(provider)
    if not cls:
        raise ValueError(f"Unknown STT provider: {provider}. Available: {list(_REGISTRY)}")
    return cls(**kwargs)
