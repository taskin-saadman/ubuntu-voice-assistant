# Runtime dependency compatibility

## faster-whisper 1.2.1 and PyAV

The project constrains `av>=18,<19` while using faster-whisper 1.2.1.
PyAV is faster-whisper's existing audio-decoding dependency; this constraint
does not introduce another decoder.

PyAV 19 removed the `metadata_errors` keyword from `av.open`. faster-whisper
1.2.1 still supplies it, so dependency resolution without an upper bound can
produce a model that loads successfully but fails before audio transcription:

```text
TypeError: open() got an unexpected keyword argument 'metadata_errors'
```

Sources: [PyAV 19 release notes](https://github.com/PyAV-Org/PyAV/releases/tag/v19.0.0)
and [faster-whisper upstream issue](https://github.com/SYSTRAN/faster-whisper/issues/1589).

Use `uv sync --locked` to reproduce the working dependency resolution in
`uv.lock`. Revisit this constraint when upgrading faster-whisper to a release
that handles the changed PyAV API. Verify audio decoding and CPU/int8
transcription before removing it. Do not patch files inside `.venv`.

The original error was reproduced using an in-memory synthetic WAV, without
reading or saving user audio. The same decode check should pass after the
dependency correction. Model loading alone is not a transcription test.
