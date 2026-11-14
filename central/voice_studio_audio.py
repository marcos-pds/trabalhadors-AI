"""Deterministic local pacing and bounded long-form WAV assembly.

The VoiceStudio /generate endpoint handles [pause] markers, but the OpenAI
/v1/audio/speech compatibility route passes text directly to the TTS engine.
This adapter therefore handles pauses itself so they cannot be spoken aloud.
"""
import io
import re
import wave


PAUSE = re.compile(r"\[pause(?:\s+(\d+(?:\.\d+)?)\s*(ms|s))?\]", re.IGNORECASE)
BAD_PAUSE = re.compile(r"\[pause[^\]]*\]", re.IGNORECASE)
MAX_SEGMENT_CHARS = 650
MAX_PARTS = 30


def _text_chunks(text: str, limit: int = MAX_SEGMENT_CHARS) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= limit:
        return [normalized]
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    parts = []
    buffer = ""
    for sentence in sentences:
        words = sentence.split(" ")
        for word in words:
            if len(word) > limit:
                raise ValueError("O roteiro contém uma palavra maior do que o limite suportado.")
            proposal = (buffer + " " + word).strip()
            if len(proposal) > limit:
                if buffer:
                    parts.append(buffer)
                buffer = word
            else:
                buffer = proposal
        # An ordinary full stop gets to remain in its segment. The segment
        # boundary is at a sentence end unless it exceeds the limit.
        if buffer and len(buffer) > limit * 0.72 and sentence.endswith((".", "!", "?")):
            parts.append(buffer)
            buffer = ""
    if buffer:
        parts.append(buffer)
    return parts


def plan_script(text: str) -> list[tuple[str, str | int]]:
    """Return text and exact silence markers; auto-chunk long text."""
    for marker in BAD_PAUSE.finditer(text):
        if not PAUSE.fullmatch(marker.group()):
            raise ValueError("Use [pause], [pause 500ms] ou [pause 1s].")
    segments = []
    pos = 0

    def add_text(piece):
        chunks = _text_chunks(piece)
        for index, chunk in enumerate(chunks):
            if segments and segments[-1][0] == "text":
                segments.append(("pause", 180))  # sentence boundary between chunks
            segments.append(("text", chunk))

    for marker in PAUSE.finditer(text):
        add_text(text[pos:marker.start()])
        amount = float(marker.group(1)) if marker.group(1) else 350.0
        millis = int(round(amount * (1000 if marker.group(2) == "s" else 1)))
        if millis < 100 or millis > 10000:
            raise ValueError("As pausas devem durar de 100 ms a 10 segundos.")
        segments.append(("pause", millis))
        pos = marker.end()
    add_text(text[pos:])
    if not any(kind == "text" for kind, _ in segments):
        raise ValueError("O roteiro precisa conter texto para narrar.")
    if len(segments) > MAX_PARTS:
        raise ValueError("O roteiro tem muitas pausas. Reduza as marcações.")
    return segments


def stitch_wav(parts: list[tuple[str, bytes | int]]) -> bytes:
    """Join PCM WAVs and exact pauses; reject format drift and unreadable audio."""
    frames = []
    encoding = None
    for kind, piece in parts:
        if kind == "pause":
            if encoding is None:
                frames.append(("pause", piece))
            else:
                frames.append(("pause", piece))
            continue
        try:
            with wave.open(io.BytesIO(piece), "rb") as source:
                fmt = (source.getnchannels(), source.getsampwidth(),
                       source.getframerate(), source.getcomptype())
                if source.getnframes() < 1 or fmt[0] not in (1, 2) or fmt[1] not in (1, 2, 3, 4):
                    raise ValueError("Formato WAV não suportado.")
                content = source.readframes(source.getnframes())
                if not content:
                    raise ValueError("Trecho de áudio vazio.")
        except (wave.Error, EOFError, TypeError, ZeroDivisionError) as exc:
            raise ValueError("O VoiceStudio retornou um WAV inválido.") from exc
        if encoding is None:
            encoding = fmt
        elif fmt != encoding:
            raise ValueError("Os trechos de áudio vieram em formatos WAV diferentes.")
        frames.append(("audio", content))
    if encoding is None:
        raise ValueError("Nenhum áudio foi gerado.")
    nchannels, width, rate, compression = encoding
    if compression != "NONE":
        raise ValueError("É necessário áudio WAV PCM não comprimido.")
    limit = 30 * 1024 * 1024
    size = 0
    output = io.BytesIO()
    with wave.open(output, "wb") as sink:
        sink.setnchannels(nchannels)
        sink.setsampwidth(width)
        sink.setframerate(rate)
        for kind, value in frames:
            data = (b"\0" * (int(round(rate * value / 1000)) * nchannels * width)
                    if kind == "pause" else value)
            size += len(data)
            if size > limit:
                raise ValueError("A narração excedeu o limite de áudio de 30 MB.")
            sink.writeframesraw(data)
    return output.getvalue()
