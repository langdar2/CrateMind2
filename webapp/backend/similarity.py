import numpy as np


def top_similar(seed: dict, tracks: list, limit: int = 30) -> list:
    others = [t for t in tracks if t["path"] != seed["path"]]
    if not others:
        return []

    embeddings = np.stack([t["embedding"] for t in others]).astype(np.float32)
    seed_vec = seed["embedding"].astype(np.float32)

    norms = np.linalg.norm(embeddings, axis=1)
    seed_norm = np.linalg.norm(seed_vec)
    scores = (embeddings @ seed_vec) / (norms * seed_norm + 1e-8)

    order = np.argsort(-scores)
    return [others[i] for i in order[:limit]]
