import requests
from config.settings import OLLAMA_BASE_URL, OLLAMA_CLEAN_MODEL


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_CLEAN_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(self, prompt: str, system: str = None, options: dict = None, timeout: int = 60) -> str:
        """
        Sends a generation request to the Ollama server.
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options

        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json().get("response", "")

    def verify_connection(self, timeout: int = 10) -> bool:
        """
        Checks if the Ollama server is reachable and active.
        """
        try:
            response = requests.get(self.base_url, timeout=timeout)
            return response.status_code == 200 and "Ollama is running" in response.text
        except requests.RequestException:
            return False


# Expose a default instance for convenience
local_llm = OllamaClient()
