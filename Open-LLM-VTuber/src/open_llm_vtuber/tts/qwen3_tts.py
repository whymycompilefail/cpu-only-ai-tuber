"""Qwen3-TTS engine backed by our own llama.cpp build (llama-tts).

Why a resident process instead of one subprocess per sentence:

    A cold `llama-tts` start has to load the backbone + mmproj (about 1.4 GB of
    weights). Measured on this machine that is ~3.4 s on top of every single
    utterance. The vocoder itself (~5 s) is per-call and CANNOT be amortised --
    that was measured, not assumed: five sentences in one process gave 5.26 /
    5.08 / 5.00 / 4.99 / 4.87 s. So residency buys the model load and nothing
    more. Do not promise more than that.

    The resident mode is `LLAMA_TTS_LOOP=1`, added to tools/tts/tts.cpp in this
    fork: read one prompt per line from stdin, generate each into
    <out>_<index>.wav, print `[i] wrote <path>` after each.
"""

import atexit
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from loguru import logger

from .tts_interface import TTSInterface

# `0.13.901.111 I [0] wrote D:/.../tts_pipe_0.wav`
WROTE_RE = re.compile(r"\[\d+\] wrote (.*?)\s*$")

# The first generation in a fresh process pays an extra ~2 s on top of the
# per-call vocoder tax (code predictor + allocator warm up). Measured: first
# utterance 7.3 s vs 4.3 s for the second one of similar length. Burn it at
# startup instead of on the user's first sentence.
WARMUP_TEXT = "嗯，我在。"

# Process-wide singleton.
#
# The resident process only pays off if it outlives a single call. But the
# backend builds a fresh ServiceContext per websocket connection, which means a
# fresh TTSEngine per connection -- and the old object's __del__ killed the
# resident process as soon as the previous conversation was garbage collected
# (verified: no llama-tts.exe alive after the probe disconnected). So every new
# browser session was paying the ~3.4 s model load again. Keep one engine for
# the lifetime of the Python process instead.
_SINGLETON: dict[str, object] = {"engine": None, "key": None}


class TTSEngine(TTSInterface):
    # Shared across every instance (including the lightweight copies handed to
    # new ServiceContexts), so there is exactly one process and one lock no
    # matter how many times the engine gets constructed.
    _proc = None
    _shared_lock = None

    @property
    def _lock(self) -> threading.Lock:
        if TTSEngine._shared_lock is None:
            TTSEngine._shared_lock = threading.Lock()
        return TTSEngine._shared_lock

    @property
    def _proc(self):
        return TTSEngine._proc

    @_proc.setter
    def _proc(self, value):
        TTSEngine._proc = value

    def __init__(
        self,
        llama_tts_bin: str = "<PROJECT_ROOT>/llama.cpp/build/bin/llama-tts.exe",
        backbone_model: str = "<PROJECT_ROOT>/models/Qwen3-TTS-0.6B-q8_0.gguf",
        mmproj_model: str = "<PROJECT_ROOT>/models/mmproj-Qwen3-TTS-0.6B-q8_0.gguf",
        lang: str = "zh",
        threads: int = 12,
        speaker_file: str = "",
        max_new_tokens: int = 0,
        tmp_dir: str = "cache/qwen3_tts",
        keep_resident: bool = True,
        seed: int = -1,
        pitch_semitones: float = 0.0,
    ):
        self.llama_tts_bin = llama_tts_bin
        self.backbone_model = backbone_model
        self.mmproj_model = mmproj_model
        self.lang = lang
        self.threads = threads
        self.speaker_file = speaker_file
        self.max_new_tokens = max_new_tokens
        # must be absolute: the resident process runs with cwd next to the
        # binary, so a relative tmp_dir would resolve somewhere else entirely
        # and llama-tts would fail to open its output file
        self.tmp_dir = os.path.abspath(tmp_dir)
        self.keep_resident = keep_resident
        self.seed = seed
        self.pitch_semitones = float(pitch_semitones)

        if abs(self.pitch_semitones) > 1e-6:
            # import once at construction so a missing librosa fails loudly at
            # startup instead of mid-utterance
            from ..utils.pitch import shift_semitones  # noqa: F401

        for p in (self.llama_tts_bin, self.backbone_model, self.mmproj_model):
            if not os.path.exists(p):
                raise FileNotFoundError(f"Qwen3-TTS: path not found: {p}")
        if self.speaker_file and not os.path.exists(self.speaker_file):
            raise FileNotFoundError(
                f"Qwen3-TTS: speaker reference not found: {self.speaker_file}")

        key = (self.llama_tts_bin, self.backbone_model, self.mmproj_model,
               self.speaker_file, self.threads, self.seed, self.max_new_tokens)
        prev = _SINGLETON["engine"]
        if isinstance(prev, TTSEngine) and _SINGLETON["key"] == key:
            # Same setup: adopt the already-running engine instead of spawning
            # a second one that would compete for the same CPU.
            logger.debug("Qwen3-TTS: reusing resident engine")
            self.__dict__.update(vars(prev))
            return
        if isinstance(prev, TTSEngine):
            logger.warning("Qwen3-TTS: engine config changed; replacing resident process")
            prev._shutdown()

        os.makedirs(self.tmp_dir, exist_ok=True)

        # one resident process, guarded by a lock: the stdin/stdout protocol is
        # strictly request/response and cannot be interleaved
        if self.keep_resident:
            self._spawn()
            _SINGLETON["engine"] = self
            _SINGLETON["key"] = key
            atexit.register(self._shutdown)
            threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self):
        """Pay the first-call overhead at startup, not on the user's sentence."""
        try:
            with self._lock:
                path = self._synth_once(WARMUP_TEXT)
            try:
                os.remove(path)
            except OSError:
                pass
            logger.info("Qwen3-TTS: warmup done, resident engine ready")
        except Exception as e:
            logger.warning(f"Qwen3-TTS: warmup failed (harmless): {e}")

    # ------------------------------------------------------------------ process

    def _spawn(self):
        out_base = os.path.join(self.tmp_dir, "tts_pipe.wav")
        cmd = [
            self.llama_tts_bin,
            "-m", self.backbone_model,
            "-mm", self.mmproj_model,
            "--tts-lang", self.lang,
            "-t", str(self.threads),
            "-o", out_base,
        ]
        if self.speaker_file:
            cmd += ["--tts-speaker-file", self.speaker_file]
        if self.max_new_tokens > 0:
            cmd += ["-n", str(self.max_new_tokens)]
        if self.seed >= 0:
            cmd += ["-s", str(self.seed)]

        env = dict(os.environ)
        env["LLAMA_TTS_LOOP"] = "1"

        # logged so the resident process we actually got can be checked later
        # with `wmic process where "name='llama-tts.exe'" get commandline`
        logger.info("Qwen3-TTS: starting resident llama-tts (%d threads, %s)"
                    % (self.threads, " ".join(cmd[1:])))
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=os.path.dirname(self.llama_tts_bin) or None,
        )

    def _restart(self):
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        self._spawn()

    def _synth_once(self, text: str) -> str:
        """Send one line to the resident process, return the wav path it wrote."""
        if self._proc is None or self._proc.poll() is not None:
            self._restart()

        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(text + "\n")
        self._proc.stdin.flush()

        # read until the engine reports the file it wrote
        for _ in range(4096):
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("llama-tts exited while generating audio")
            m = WROTE_RE.search(line)
            if m:
                return m.group(1)
            if "loop mode" in line:
                continue
        raise RuntimeError("llama-tts produced no output line for this prompt")

    def _synth_cold(self, text: str) -> str:
        """One-shot fallback: a fresh process per utterance (slower, no state)."""
        out_path = os.path.join(self.tmp_dir, f"tts_cold_{uuid.uuid4().hex}.wav")
        cmd = [
            self.llama_tts_bin,
            "-m", self.backbone_model,
            "-mm", self.mmproj_model,
            "--tts-lang", self.lang,
            "-t", str(self.threads),
            "-o", out_path,
            "-p", text,
        ]
        if self.speaker_file:
            cmd += ["--tts-speaker-file", self.speaker_file]
        if self.max_new_tokens > 0:
            cmd += ["-n", str(self.max_new_tokens)]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        if not os.path.exists(out_path):
            raise RuntimeError(f"llama-tts failed: {r.stdout[-800:]}")
        return out_path

    # ------------------------------------------------------------------ public

    def generate_audio(self, text: str, file_name_no_ext: str | None = None) -> str | None:
        file_name = self.generate_cache_file_name(file_name_no_ext)

        # the protocol is one prompt per line -- newlines would desync it
        clean = " ".join(text.split())
        if not clean:
            logger.warning("Qwen3-TTS: empty text, skipping")
            return None

        try:
            if self.keep_resident:
                with self._lock:
                    src = self._synth_once(clean)
            else:
                src = self._synth_cold(clean)

            if not os.path.exists(src):
                raise FileNotFoundError(f"llama-tts reported {src} but it does not exist")

            if os.path.abspath(src) != os.path.abspath(file_name):
                shutil.move(src, file_name)
                try:
                    os.remove(src)
                except OSError:
                    pass

            if abs(self.pitch_semitones) > 1e-6:
                self._transpose_in_place(file_name)

            logger.debug(f"Qwen3-TTS: wrote {file_name}")
            return file_name

        except Exception as e:
            logger.critical(f"Qwen3-TTS: unable to generate audio: {e}")
            # a dead resident process should not poison every later sentence
            if self.keep_resident:
                try:
                    with self._lock:
                        self._restart()
                except Exception as re_:
                    logger.critical(f"Qwen3-TTS: restart failed: {re_}")
            return None

    def _transpose_in_place(self, path: str) -> None:
        """Rewrite `path` pitched up by `pitch_semitones`, keeping its length.

        Done after synthesis rather than to the speaker reference because cloning
        discards the reference's pitch anyway (see ctest/voice_ab.py).
        """
        import soundfile as sf

        from ..utils.pitch import shift_semitones

        data, sr = sf.read(path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        t0 = time.time()
        y = shift_semitones(data, self.pitch_semitones, sr=sr)
        sf.write(path, y, sr, subtype="PCM_16")
        logger.debug(f"Qwen3-TTS: pitch {self.pitch_semitones:+.1f} "
                     f"semitones in {time.time() - t0:.2f}s")

    def _shutdown(self):
        """Only the singleton's process exists; kill it at interpreter exit."""
        proc = getattr(self, "_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def __del__(self):
        # Deliberately does nothing: copies share the singleton's Popen, and
        # killing it here would drag the resident process down with every
        # websocket connection that gets garbage collected. _shutdown handles
        # cleanup once, at process exit.
        pass
