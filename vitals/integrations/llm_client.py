"""OpenRouter LLM gateway — one provider-agnostic client.

Thin wrapper over the official ``openai`` SDK pointed at OpenRouter
(``base_url`` override). Model ids are per-task and come from config
(``llm_model_digest`` for narrative, ``llm_model_parser`` — vision-capable — for
lab extraction), so switching providers/models is an ``.env`` change, never code.

Two helpers cover the two shapes the product needs:
  * :meth:`complete_text` — free-text narrative (weekly digest, module 10).
  * :meth:`extract_json`  — structured/JSON extraction, optionally from an image
    (lab parser, module 7).

The underlying client is built lazily, so importing this module (and constructing
``LLMClient``) never requires an API key — only an actual call does.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from vitals.config import Config, load_config

logger = logging.getLogger(__name__)

# Hard ceiling on a single LLM request. Lab extraction (`extract_json`) and the
# on-demand digest (`complete_text`) run *inside* an HTTP request, so without this
# a hung upstream would pin the worker for the SDK's ~10-minute default.
_REQUEST_TIMEOUT_SECONDS = 90.0


class LLMNotConfigured(RuntimeError):
    """Raised when a call is attempted without ``VITALS_OPENROUTER_API_KEY``."""


class LLMEmptyResponse(RuntimeError):
    """Raised when the upstream returns a 200 with a blank completion — no
    exception, just nothing to show (observed as an intermittent OpenRouter/
    provider hiccup, not tied to any one model)."""


class LLMClient:
    def __init__(self, config: Optional[Config] = None):
        self._config = config or load_config()
        self._client: Any = None  # lazily constructed AsyncOpenAI

    # ── plumbing ───────────────────────────────────────────────────────────────
    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._config.openrouter_api_key:
            raise LLMNotConfigured("VITALS_OPENROUTER_API_KEY is not set")
        from openai import AsyncOpenAI  # imported lazily

        headers: dict[str, str] = {}
        if self._config.openrouter_http_referer:
            headers["HTTP-Referer"] = self._config.openrouter_http_referer
        if self._config.openrouter_x_title:
            headers["X-Title"] = self._config.openrouter_x_title

        self._client = AsyncOpenAI(
            base_url=self._config.openrouter_base_url,
            api_key=self._config.openrouter_api_key,
            default_headers=headers or None,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            # SDK default is 2 retries -> a paid call can cost 3x on transient errors.
            max_retries=0,
        )
        return self._client

    @property
    def digest_model(self) -> str:
        return self._config.llm_model_digest

    @property
    def parser_model(self) -> str:
        return self._config.llm_model_parser

    @property
    def brief_model(self) -> str:
        """Model for the daily brief; falls back to the digest model when unset."""
        return self._config.llm_model_brief or self.digest_model

    # ── helpers ────────────────────────────────────────────────────────────────
    async def complete_text(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Free-text completion (narrative digest). Returns the message content."""
        client = self._ensure_client()
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await client.chat.completions.create(
            model=model or self.digest_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            # A blank completion isn't an SDK-level error (no exception to catch),
            # so without this the only trace is "content was empty" — log the one
            # field (finish_reason) that hints at why: length/content_filter/stop.
            logger.warning(
                "LLM returned empty content (model=%s, finish_reason=%s)",
                model or self.digest_model, choice.finish_reason,
            )
        elif choice.finish_reason == "length":
            # Truncation is silent otherwise: the caller gets a normal-looking
            # string that stops mid-sentence (hit in prod on a reasoning model,
            # whose thinking tokens eat the same max_tokens budget).
            logger.warning(
                "LLM completion truncated by max_tokens (model=%s, max_tokens=%s)",
                model or self.digest_model, max_tokens,
            )
        return content

    async def extract_json(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        image_url: Optional[str] = None,
        image_urls: Optional[list[str]] = None,
        temperature: float = 0.0,
    ) -> dict:
        """Structured extraction → parsed JSON dict. Pass ``image_url`` (a data: or
        https: URL) or ``image_urls`` (a list of data: or https: URLs) to send lab
        scans to a vision-capable model. If the model returns non-JSON, the raw
        text comes back under ``_unparsed`` (caller decides how to handle). So
        does a reply cut off by the token limit — flagged ``_truncated`` — even
        when the cut happens to leave valid JSON: a list that stops halfway
        would otherwise pass for the whole document."""
        client = self._ensure_client()

        user_content: Any
        if image_urls:
            user_content = [{"type": "text", "text": prompt}]
            for url in image_urls:
                user_content.append({"type": "image_url", "image_url": {"url": url}})
        elif image_url:
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        else:
            user_content = prompt

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})

        resp = await client.chat.completions.create(
            model=model or self.parser_model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0]
        raw = (choice.message.content or "").strip()
        finish_reason = getattr(choice, "finish_reason", None)
        if not raw:
            logger.warning(
                "LLM extract_json returned empty content (model=%s, finish_reason=%s)",
                model or self.parser_model, finish_reason,
            )
            return {"_unparsed": ""}
        if finish_reason == "length":
            logger.warning(
                "LLM extract_json truncated by the token limit (model=%s, %d chars)",
                model or self.parser_model, len(raw),
            )
            return {"_unparsed": raw, "_truncated": True}
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        # Hand the unparsed text back instead of an empty dict: callers store this
        # verbatim in ``raw_payloads``, and {} would throw away the only artefact
        # that makes a failed extraction reviewable and re-parseable later.
        logger.warning("LLM extract_json returned non-JSON content")
        return {"_unparsed": raw}

    async def ping(self) -> bool:
        """Lightweight reachability check (one tiny completion). Returns True on a
        non-empty response, False on any failure. Mocked in tests."""
        try:
            text = await self.complete_text(
                "ping", system="Reply with the single word: pong", max_tokens=5
            )
            return bool(text)
        except Exception:
            logger.warning("LLM ping failed", exc_info=True)
            return False
