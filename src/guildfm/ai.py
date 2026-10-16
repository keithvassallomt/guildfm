"""OpenAI's text models, through the Responses API: song picks and DJ lines as JSON that fits a
schema, and plain text, optionally with a web search, for the music news. Also its image model,
for stations' covers."""

import base64
import json
from typing import Any

import httpx2

from guildfm.health import Health

API = "https://api.openai.com/v1/responses"
IMAGES = "https://api.openai.com/v1/images/generations"
IMAGE_SECONDS = 180  # painting can take a couple of minutes


class AIError(Exception):
    """The AI didn't answer usefully. The message is fit to show people."""


class AIClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        effort: str = "",
        http: httpx2.AsyncClient | None = None,
        *,
        image_model: str = "gpt-image-2.5-flare",
        image_quality: str = "medium",
    ) -> None:
        self._key = api_key
        self._model = model
        self._effort = effort
        self._image_model = image_model
        self._image_quality = image_quality
        self._http = http or httpx2.AsyncClient(timeout=90)
        self.health = Health()

    async def close(self) -> None:
        await self._http.aclose()

    async def _ask(self, body: dict[str, Any]) -> str:
        body = {"model": self._model, **body}
        if self._effort:
            body["reasoning"] = {"effort": self._effort}
        response = await self._post(API, body)
        # The answer is the message among the output items; others are reasoning and searches.
        for item in response.json().get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        return part["text"]
        raise AIError("OpenAI didn't give an answer.")

    async def json(
        self, instructions: str, prompt: str, name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """An answer that fits `schema`, a JSON schema for an object."""
        answer_format = {"type": "json_schema", "name": name, "schema": schema, "strict": True}
        text = await self._ask(
            {"instructions": instructions, "input": prompt, "text": {"format": answer_format}}
        )
        try:
            return json.loads(text)
        except ValueError as error:
            raise AIError("OpenAI's answer didn't make sense.") from error

    async def image(self, prompt: str) -> bytes:
        """A square image painted from `prompt`, as WebP."""
        body = {
            "model": self._image_model,
            "prompt": prompt,
            "size": "1024x1024",
            "quality": self._image_quality,
            "output_format": "webp",
            "output_compression": 80,
        }
        response = await self._post(IMAGES, body, timeout=IMAGE_SECONDS)
        try:
            return base64.b64decode(response.json()["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise AIError("OpenAI didn't send an image.") from error

    async def _post(self, url: str, body: dict[str, Any], **options: Any) -> httpx2.Response:
        try:
            response = await self._send(url, body, **options)
        except AIError as error:
            self.health.failed(str(error))
            raise
        self.health.worked()
        return response

    async def _send(self, url: str, body: dict[str, Any], **options: Any) -> httpx2.Response:
        try:
            response = await self._http.post(
                url, json=body, headers={"Authorization": f"Bearer {self._key}"}, **options
            )
        except httpx2.HTTPError as error:
            raise AIError("Couldn't reach OpenAI. Check the internet connection.") from error
        if response.status_code == 401:
            raise AIError("OpenAI turned GuildFM's key down. Check OPENAI_API_KEY in .env.")
        if response.status_code == 429:
            raise AIError("OpenAI is busy, or the account is out of credit.")
        if response.status_code >= 400:
            raise AIError("OpenAI couldn't answer just now.")
        return response

    async def text(self, instructions: str, prompt: str, web_search: bool = False) -> str:
        body: dict[str, Any] = {"instructions": instructions, "input": prompt}
        if web_search:
            body["tools"] = [{"type": "web_search", "search_context_size": "low"}]
        return await self._ask(body)


def object_schema(**properties: dict[str, Any]) -> dict[str, Any]:
    """A strict JSON schema for an object with every one of `properties` required."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }
