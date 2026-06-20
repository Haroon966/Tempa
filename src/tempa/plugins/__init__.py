from __future__ import annotations

from typing import Any

import yaml

from tempa.rag.store import COLLECTION_NAME, get_store
from tempa.settings import get_settings


def load_tools_config() -> dict[str, Any]:
    path = get_settings().config_dir / "tools.yaml"
    if not path.exists():
        return {"plugins": {"enabled": [], "builtin": []}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def assert_unified_vector_store(store: Any) -> None:
    """FR-PLUGIN-04: plugins may not create separate vector stores."""
    if getattr(store, "collection", None) is None:
        raise ValueError("Plugin store must expose a Chroma collection")
    if store.collection.name != COLLECTION_NAME:
        raise ValueError(f"Plugins must use unified collection '{COLLECTION_NAME}' only")


def get_plugin_store():
    store = get_store()
    assert_unified_vector_store(store)
    return store
