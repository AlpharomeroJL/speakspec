"""Phase 7 ASR verification: transcribe a known-text TTS WAV.

Gates:

* transcript word count within 20% of the ground-truth text,
* the technical-vocabulary pass ran (corrections list present),
* an edited transcript actually feeds Stage 1 (the pipeline runs on the
  edited text, not the raw ASR output).

Run ``gen_tts_sample.ps1`` first to produce ``fixtures/tts_sample.wav``.
"""

import sys
import threading
import time
from pathlib import Path

from speakspec.asr import detect_hardware, handle_transcribe
from speakspec.rpc import RequestContext, RpcServer

FIXTURES = Path(__file__).parent / "fixtures"


class _NullServer(RpcServer):
    """RequestContext host that swallows progress lines for offline runs."""

    def __init__(self) -> None:
        self.progress: list[dict] = []
        self._stdout_lock = threading.Lock()
        self._contexts = {}
        self._contexts_lock = threading.Lock()

    def emit(self, msg) -> None:  # noqa: ANN001 - matches base signature
        if msg.type == "progress" and msg.data is not None:
            self.progress.append(msg.data)


def main() -> int:
    """Transcribe the TTS sample and print the verdicts."""
    sys.stdout.reconfigure(line_buffering=True)
    wav = FIXTURES / "tts_sample.wav"
    truth = (FIXTURES / "sample_transcript.txt").read_text(encoding="utf-8")
    if not wav.is_file():
        print("FATAL: run gen_tts_sample.ps1 first to create tts_sample.wav")
        return 2

    print(f"hardware: {detect_hardware()}")
    server = _NullServer()
    ctx = RequestContext(server, "asr-check")
    t0 = time.time()
    result = handle_transcribe({"audio_path": str(wav)}, ctx)
    elapsed = time.time() - t0

    truth_words = len(truth.split())
    got_words = len(result["transcript"].split())
    ratio = got_words / truth_words
    duration = result["duration"]
    print(
        f"device={result['device']} model={result['model']} "
        f"audio={duration:.0f}s transcribed in {elapsed:.0f}s "
        f"({duration / max(elapsed, 0.001):.1f}x real-time)"
    )
    print(f"words: truth={truth_words} got={got_words} ratio={ratio:.2f}")
    print(f"progress events: {len(server.progress)}")
    print(f"vocab corrections applied: {len(result['corrections'])}")
    print(f"transcript head: {result['transcript'][:160]}…")

    word_gate = 0.8 <= ratio <= 1.2
    progress_gate = len(server.progress) >= 2
    # Simulated edit: the pipeline must receive the edited text verbatim.
    edited = result["transcript"] + " EDITED-MARKER-XYZZY"
    from speakspec.pipeline import stage1_message

    edit_gate = "EDITED-MARKER-XYZZY" in stage1_message(edited, "")

    print(f"word count within 20%: {word_gate}")
    print(f"progress streamed: {progress_gate}")
    print(f"edited transcript feeds Stage 1 verbatim: {edit_gate}")
    ok = word_gate and progress_gate and edit_gate
    print(f"ASR CHECK: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
