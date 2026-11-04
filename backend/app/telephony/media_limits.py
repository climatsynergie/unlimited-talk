"""Protocol bounds for stored audio, independent of conversation policy."""

MAX_RECORDING_SECONDS = 30 * 60
MAX_RECORDING_BYTES = (MAX_RECORDING_SECONDS + 1) * 8000 * 2 * 2 + 65536
LEGACY_BUFFER_BYTES = 24 * 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
