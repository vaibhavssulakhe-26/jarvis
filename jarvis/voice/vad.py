"""Where speech starts and ends. Silero (onnxruntime, the model shipped with openwakeword or models/silero_vad.onnx) is used when it loads,
then webrtcvad, then a plain loudness test. The Endpointer is the end-of-speech rule and knows nothing about audio."""
import numpy as np

from ..core import config

BLOCK_SECONDS = 0.08
SILENCE_SECONDS = 0.8
CROWD_PROB = 0.7
NORMAL_PROB = 0.5


def max_record_seconds():
    try:
        return max(2.0, float(config.get("MAX_RECORD_SECONDS", "12")))
    except ValueError:
        return 12.0


class Detector:
    """is_speech(block, rms, floor_gate) for one 80 ms int16 block. `backend` names what is in use."""

    def __init__(self, backend=None):
        self.backend = "energy"
        self._model = None
        self._web = None
        if backend in (None, "silero"):
            self._model = self._load_silero()
            if self._model is not None:
                self.backend = "silero"
        if self._model is None and backend in (None, "webrtc"):
            self._web = self._load_webrtc()
            if self._web is not None:
                self.backend = "webrtc"

    @staticmethod
    def _load_silero():
        try:
            from openwakeword.vad import VAD
            own = config.MODELS / "silero_vad.onnx"
            return VAD(str(own)) if own.exists() else VAD()
        except Exception:
            return None

    @staticmethod
    def _load_webrtc():
        try:
            import webrtcvad
            return webrtcvad.Vad(2)
        except Exception:
            return None

    def reset(self):
        if self._model is not None:
            self._model.reset_states()

    def probability(self, block):
        """0 to 1 for the silero backend, 1.0 or 0.0 for webrtc, None for the loudness fallback."""
        if self._model is not None:
            return float(self._model.predict(block, frame_size=640))
        if self._web is not None:
            frame = 320
            votes = [self._web.is_speech(block[i:i + frame].tobytes(), 16000) for i in range(0, len(block) - frame + 1, frame)]
            return float(sum(votes) / max(1, len(votes)))
        return None

    def is_speech(self, block, rms, gate, crowd=False):
        """`gate` is the loudness a block must exceed; in crowd mode the model also has to be more sure."""
        prob = self.probability(block)
        if prob is None:
            return rms > gate
        need = CROWD_PROB if crowd else NORMAL_PROB
        return prob >= need and (rms > gate * 0.5 or not crowd)


class Endpointer:
    """Ends a recording after `silence` seconds without speech, or at `cap` seconds. feed() gives None, 'silence' or 'cap'."""

    def __init__(self, silence=SILENCE_SECONDS, cap=None):
        self.need = max(1, round(silence / BLOCK_SECONDS))
        self.limit = max(1, round((cap if cap is not None else max_record_seconds()) / BLOCK_SECONDS))
        self.quiet = 0
        self.blocks = 0
        self.heard = False

    def feed(self, speech):
        self.blocks += 1
        if speech:
            self.heard = True
            self.quiet = 0
        else:
            self.quiet += 1
        if self.blocks >= self.limit:
            return "cap"
        if self.quiet >= self.need:
            return "silence"
        return None


def denoise(audio, sr=16000):
    """A light spectral gate for NOISE_SUPPRESS: the quietest frames set a noise profile, bins near it are turned down (never to zero)."""
    from scipy.signal import istft, stft
    if len(audio) < sr // 4:
        return audio
    _, _, z = stft(audio, sr, nperseg=512)
    mag = np.abs(z)
    energy = mag.sum(axis=0)
    quiet = energy <= np.percentile(energy, 15)
    noise = mag[:, quiet].mean(axis=1, keepdims=True)
    gain = np.clip(1.0 - 1.5 * noise / np.maximum(mag, 1e-9), 0.15, 1.0)
    _, out = istft(z * gain, sr, nperseg=512)
    out = out[: len(audio)].astype(np.float32)
    return np.pad(out, (0, len(audio) - len(out)))
