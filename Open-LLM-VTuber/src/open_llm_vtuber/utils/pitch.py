"""Pitch shifting for synthesised speech.

Why this exists
---------------
The obvious lever for "make her sound younger" is the speaker reference -- it
does NOT work. Measured with ctest/voice_ab.py, cloning pulls pitch towards the
model's own prior and largely ignores the reference:

    reference F0   258.4 (spk_1)       -> output F0 288.1
    reference F0   309.5 (spk_2)       -> output F0 285.0
    reference F0   300.5 (fix_noref_2) -> output F0 237.1

Every clone lands in ~237-294 Hz whatever its source, so swapping reference
files cannot move the voice out of "adult woman". Transposing what the engine
already produces is the only local knob left.

Why librosa and not our own OLA
-------------------------------
A hand-rolled resample + plain overlap-add time stretch was written first and
verified against synthesised sine tones. It failed: a 220 Hz sine came back at
~270 Hz for +2, +3 and +4 semitones alike (expected 246.9 / 261.6 / 277.2),
because OLA with a fixed hop does not align waveform phase and turns a tone
into comb-filtered mush. Do not reinstate that implementation without first
running the same sine check (see ctest/check_pitch_shift.py).
"""
import numpy as np

try:
    import librosa
except ImportError as _e:  # pragma: no cover
    librosa = None
    _IMPORT_ERR = _e


def shift_semitones(x: np.ndarray, semitones: float, sr: int = 24000,
                    keep_duration: bool = True) -> np.ndarray:
    """Shift pitch by `semitones`. Duration is preserved by construction.

    Implemented as resample (transpose) + STFT time-stretch back to the original
    length, which is what librosa.effects.pitch_shift does internally.
    """
    if librosa is None:
        raise RuntimeError(
            "librosa is required for pitch shifting: %s" % _IMPORT_ERR)
    if abs(semitones) < 1e-6:
        return np.asarray(x, dtype=np.float32)

    if x.ndim > 1:
        x = x.mean(axis=1)
    x = np.asarray(x, dtype=np.float32)

    if keep_duration:
        return librosa.effects.pitch_shift(x, sr=sr, n_steps=semitones)

    # pitch and tempo together: plain resampling
    ratio = 2.0 ** (semitones / 12.0)
    target = max(1, int(round(len(x) / ratio)))
    return librosa.resample(x, orig_sr=len(x), target_sr=target)
