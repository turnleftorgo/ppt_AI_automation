"""
YAML template loader and registry.

Reads all .yaml/.yml files from the templates/ directory and provides
a dict-based registry keyed by template_id.
"""
import os
import yaml
from typing import Dict, Optional


class YAMLLoader:
    def __init__(self, templates_dir: str):
        self.templates_dir = templates_dir
        self._registry: Dict[str, dict] = {}

    def load_all(self) -> Dict[str, dict]:
        """Scan templates/ for .yaml files, parse and validate each."""
        self._registry.clear()
        for fname in os.listdir(self.templates_dir):
            if not fname.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(self.templates_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            self._validate(config, fname)
            tid = config["template_id"]
            self._registry[tid] = config
        return self._registry

    def get(self, template_id: str) -> Optional[dict]:
        return self._registry.get(template_id)

    def list_all(self) -> list:
        """Return summary list for /api/templates."""
        return [
            {
                "template_id": cfg["template_id"],
                "template_name": cfg["template_name"],
                "description": cfg.get("description", ""),
            }
            for cfg in self._registry.values()
        ]

    def _validate(self, config: dict, filename: str):
        """Raise ValueError if YAML is missing required fields."""
        required = ["template_id", "template_name", "ppt_file_path"]
        for field in required:
            if field not in config:
                raise ValueError(f"YAML '{filename}' missing required field: {field}")
        # Validate ppt_file_path exists
        ppt_path = os.path.join(self.templates_dir, config["ppt_file_path"])
        if not os.path.exists(ppt_path):
            raise ValueError(
                f"YAML '{filename}' references non-existent PPTX: {config['ppt_file_path']}"
            )
