"""Select the authoritative saved desk, including a failed first collection."""
from pathlib import Path


def directory(root):
    root = Path(root)
    regular = root / 'candidate-regular-v1'
    if any((regular / name).exists() for name in ('current.json', 'attempt.json', 'decisions.json')):
        return regular
    return root / 'candidate-desk'
