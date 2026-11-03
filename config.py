import os
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

DEFAULT_CONFIG = {
    "audio": {
        "stream_playback": True,
        "pause_between_chunks_ms": 200,
        "crossfade_ms": 30,
        "keep_partial_on_cancel": False,
        "max_chunk_chars": 250,
        "target_sample_rate": 24000,
    },
    "generation": {
        "default_language": "hi",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
    },
    "server": {
        "host": "127.0.0.1",
        "port": 7860,
    },
}


def load_config() -> dict:
    """Loads configuration from config.yaml, creating it with defaults if absent."""
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            # Merge defaults for any missing keys
            config = DEFAULT_CONFIG.copy()
            for section, values in data.items():
                if section in config and isinstance(values, dict):
                    config[section].update(values)
                else:
                    config[section] = values
            return config
    except Exception as e:
        print(f"[Config] Error loading config.yaml, using defaults: {e}")
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> bool:
    """Saves dictionary configuration back to config.yaml."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        print(f"[Config] Error saving config.yaml: {e}")
        return False
