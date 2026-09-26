import argparse
import os
import shutil
import tempfile

import numpy as np
from essentia.standard import (
    KeyExtractor,
    MonoLoader,
    Resample,
    RhythmExtractor2013,
    TensorflowPredict2D,
    TensorflowPredictMusiCNN,
)

MODELS_DIR = os.environ.get("MODELS_DIR", "/models")
EMBEDDING_MODEL_PATH = os.path.join(MODELS_DIR, "msd-musicnn-1.pb")

# (model filename, index of the positive/target class in the model's softmax output)
MOOD_MODELS = {
    "mood_happy": ("mood_happy-msd-musicnn-1.pb", 0),
    "mood_aggressive": ("mood_aggressive-msd-musicnn-1.pb", 0),
    "mood_relaxed": ("mood_relaxed-msd-musicnn-1.pb", 1),
    "mood_party": ("mood_party-msd-musicnn-1.pb", 1),
    "danceability": ("danceability-msd-musicnn-1.pb", 0),
}

_embedding_model = None
_mood_models = None  # name -> (TensorflowPredict2D instance, positive_index)


def _load_models():
    global _embedding_model, _mood_models
    if _embedding_model is None:
        _embedding_model = TensorflowPredictMusiCNN(
            graphFilename=EMBEDDING_MODEL_PATH, output="model/dense/BiasAdd"
        )
        _mood_models = {
            name: (
                TensorflowPredict2D(
                    graphFilename=os.path.join(MODELS_DIR, filename), output="model/Softmax"
                ),
                positive_index,
            )
            for name, (filename, positive_index) in MOOD_MODELS.items()
        }
    return _embedding_model, _mood_models


def extract_features(audio_16k: np.ndarray, audio_44k: np.ndarray) -> dict:
    """audio_16k: mono float32 samples at 16000 Hz (MusiCNN input).
    audio_44k: mono float32 samples at 44100 Hz (tempo/key input)."""
    embedding_model, mood_models = _load_models()

    embeddings = embedding_model(audio_16k)
    embedding_vector = np.mean(embeddings, axis=0).astype(np.float32)

    moods = {}
    for name, (model, positive_index) in mood_models.items():
        predictions = model(embeddings)
        moods[name] = float(np.mean(predictions, axis=0)[positive_index])

    rhythm_extractor = RhythmExtractor2013(method="multifeature")
    bpm, _, _, _, _ = rhythm_extractor(audio_44k)

    key_extractor = KeyExtractor()
    key, scale, _ = key_extractor(audio_44k)

    return {
        "bpm": float(bpm),
        "key": f"{key} {scale}",
        "mood_happy": moods["mood_happy"],
        "mood_aggressive": moods["mood_aggressive"],
        "mood_relaxed": moods["mood_relaxed"],
        "mood_party": moods["mood_party"],
        "danceability": moods["danceability"],
        "embedding": embedding_vector,
    }


def load_audio_for_analysis(path: str):
    """Returns (audio_16k, audio_44k) as mono float32 numpy arrays.

    # ponytail: copies to a local tempfile before loading. MP4-container
    # formats (m4a/alac) need random-access seeks to find the moov atom,
    # which fail with EPERM over our emulated/networked Docker mount.
    # Copying first sidesteps that; upgrade to extension-based skipping if
    # the copy overhead ever matters.
    """
    suffix = os.path.splitext(path)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfile(path, tmp.name)
        tmp_path = tmp.name
    try:
        audio_44k = MonoLoader(filename=tmp_path, sampleRate=44100)()
        audio_16k = MonoLoader(filename=tmp_path, sampleRate=16000)()
    finally:
        os.remove(tmp_path)
    return audio_16k, audio_44k


def _make_click_track(duration_seconds: float = 15.0, bpm: float = 120.0, sample_rate: int = 44100) -> np.ndarray:
    samples = np.zeros(int(duration_seconds * sample_rate), dtype=np.float32)
    interval = 60.0 / bpm
    click_length = int(0.01 * sample_rate)
    t = 0.0
    while t < duration_seconds:
        start = int(t * sample_rate)
        end = min(start + click_length, len(samples))
        samples[start:end] = 0.8
        t += interval
    return samples


def self_test() -> None:
    audio_44k = _make_click_track(duration_seconds=15.0, bpm=120.0, sample_rate=44100)
    audio_16k = Resample(inputSampleRate=44100, outputSampleRate=16000)(audio_44k)

    result = extract_features(audio_16k, audio_44k)

    assert 20 <= result["bpm"] <= 300, f"BPM out of range: {result['bpm']}"
    assert result["embedding"].shape == (200,), f"Unexpected embedding shape: {result['embedding'].shape}"
    for mood_key in ("mood_happy", "mood_aggressive", "mood_relaxed", "mood_party", "danceability"):
        value = result[mood_key]
        assert 0.0 <= value <= 1.0, f"{mood_key} out of range: {value}"

    printable = {k: v for k, v in result.items() if k != "embedding"}
    print("Self-test passed:", printable)
    print("Embedding shape:", result["embedding"].shape)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        parser.print_help()
