"""
Function Registry — maps natural-language commands to website actions.

Each registered site has a JSON file describing its available functions.
The AI engine selects which function to call; the bridge executes it.

Registry file format (JSON):
{
  "site": "https://example.com",
  "name": "Example Site",
  "functions": [
    {
      "name": "toggle_dark_mode",
      "description": "Toggle dark mode on or off",
      "params": {},
      "action_type": "js",
      "action": "document.body.classList.toggle('dark')"
    },
    {
      "name": "navigate_to",
      "description": "Navigate to a page on the site",
      "params": {"page": "string — the page name or URL path"},
      "action_type": "navigate",
      "action": "/{{page}}"
    },
    {
      "name": "search_docs",
      "description": "Search the documentation for a query",
      "params": {"query": "string — the search query"},
      "action_type": "ai_scrape",
      "action": "/docs?search={{query}}"
    }
  ]
}
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional


class FunctionRegistry:
    def __init__(self, settings):
        self.settings = settings
        self.registry_dir = Path.home() / ".aria-assistant" / "registries"
        self.registry_dir.mkdir(exist_ok=True)
        self._active: Optional[dict] = None
        self._load_builtin_registries()

    def _load_builtin_registries(self):
        """Write the built-in test-website registry if it doesn't exist."""
        builtin = self.registry_dir / "novasuite.json"
        if not builtin.exists():
            payload = {
                "site": "http://localhost:5500",
                "name": "NovaSuite (test site)",
                "functions": [
                    {
                        "name": "toggle_dark_mode",
                        "description": "Toggle dark or light mode",
                        "params": {},
                        "action_type": "js",
                        "action": "window.__aria?.toggleDark()",
                    },
                    {
                        "name": "go_to_pricing",
                        "description": "Navigate to the pricing page",
                        "params": {},
                        "action_type": "navigate",
                        "action": "/pages/pricing.html",
                    },
                    {
                        "name": "go_to_docs",
                        "description": "Navigate to the documentation page",
                        "params": {},
                        "action_type": "navigate",
                        "action": "/pages/docs.html",
                    },
                    {
                        "name": "go_to_home",
                        "description": "Go to the home page",
                        "params": {},
                        "action_type": "navigate",
                        "action": "/index.html",
                    },
                    {
                        "name": "go_to_settings",
                        "description": "Navigate to the account settings page",
                        "params": {},
                        "action_type": "navigate",
                        "action": "/pages/settings.html",
                    },
                    {
                        "name": "go_to_onboarding",
                        "description": "Navigate to the onboarding / get-started wizard",
                        "params": {},
                        "action_type": "navigate",
                        "action": "/pages/onboarding.html",
                    },
                    {
                        "name": "go_to_appearance_settings",
                        "description": "Go directly to the appearance/theme settings where dark mode is toggled",
                        "params": {},
                        "action_type": "js",
                        "action": "window.location.href='/pages/settings.html'; setTimeout(()=>window.__aria?.goToAppearance?.(),800)",
                    },
                    {
                        "name": "recommend_plan",
                        "description": "Recommend the best pricing plan based on requirements",
                        "params": {"requirements": "string describing user needs"},
                        "action_type": "ai_reason",
                        "action": "scrape_pricing_and_reason",
                    },
                    {
                        "name": "search_docs",
                        "description": "Search the documentation for an answer",
                        "params": {"query": "string — what to search for"},
                        "action_type": "ai_reason",
                        "action": "scrape_docs_and_reason",
                    },
                ],
            }
            builtin.write_text(json.dumps(payload, indent=2))

    def list_registries(self) -> list[dict]:
        registries = []
        for f in self.registry_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                registries.append({"file": str(f), "name": data.get("name", f.stem), "site": data.get("site", "")})
            except Exception:
                pass
        return registries

    def load(self, registry_path: str) -> bool:
        try:
            self._active = json.loads(Path(registry_path).read_text())
            self.settings.set("active_site_registry", registry_path)
            self.settings.set("active_site_url", self._active.get("site", ""))
            return True
        except Exception:
            return False

    def get_active(self) -> Optional[dict]:
        return self._active

    def get_function_descriptions(self) -> str:
        if not self._active:
            return ""
        lines = []
        for fn in self._active.get("functions", []):
            desc = fn["description"]
            params = fn.get("params", {})
            param_str = ", ".join(f"{k}: {v}" for k, v in params.items())
            lines.append(f"- {fn['name']}({param_str}): {desc}")
        return "\n".join(lines)

    def get_system_prompt(self) -> str:
        if not self._active:
            return ""
        name = self.settings.assistant_name
        site_name = self._active.get("name", "this website")
        functions = self.get_function_descriptions()
        system_functions = "- toggle_hand_tracking(enable: boolean): Turn visual hand gesture tracking on or off"
        return (
            f"You are {name}, an assistant integrated into {site_name}.\n"
            f"Available website actions:\n{functions}\n"
            f"Available system actions:\n{system_functions}\n\n"
            "When the user asks you to do something, reply with a JSON block "
            "on its own line: {\"action\": \"<name>\", \"params\": {\"key\": \"value\"}} "
            "followed by a short confirmation message. "
            "If no action is needed, just answer in plain text."
        )
