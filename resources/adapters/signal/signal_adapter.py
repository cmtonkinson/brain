"""In-process Signal adapter implementation over HTTP."""

from __future__ import annotations

import json
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterHealthResult,
    SignalAdapterInternalError,
    SignalWebhookRegistrationResult,
)
from resources.adapters.signal.component import RESOURCE_COMPONENT_ID
from resources.adapters.signal.config import SignalAdapterSettings

_LOGGER = get_logger(__name__)


class HttpSignalAdapter(SignalAdapter):
    """Signal adapter backed by HTTP calls to a Signal runtime endpoint."""

    def __init__(self, *, settings: SignalAdapterSettings) -> None:
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/")

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
    ) -> SignalWebhookRegistrationResult:
        """Register callback URL and shared secret with Signal runtime."""
        payload = {
            "callback_url": callback_url,
            "shared_secret": shared_secret,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            url=f"{self._base_url}/v1/webhooks/register",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        for attempt in range(self._settings.max_retries + 1):
            try:
                with urllib_request.urlopen(
                    request, timeout=self._settings.timeout_seconds
                ) as response:
                    response_payload = json.loads(
                        response.read().decode("utf-8") or "{}"
                    )
                registered = bool(response_payload.get("registered", True))
                detail = str(response_payload.get("detail", "registered"))
                return SignalWebhookRegistrationResult(
                    registered=registered,
                    detail=detail,
                )
            except urllib_error.HTTPError as exc:
                if exc.code >= 500 and attempt < self._settings.max_retries:
                    continue
                raise SignalAdapterDependencyError(
                    f"signal webhook registration failed with status {exc.code}"
                ) from None
            except urllib_error.URLError as exc:
                if attempt < self._settings.max_retries:
                    continue
                raise SignalAdapterDependencyError(
                    str(exc.reason) or "signal webhook registration unavailable"
                ) from None
            except json.JSONDecodeError as exc:
                raise SignalAdapterInternalError(
                    f"signal registration response JSON invalid: {exc}"
                ) from None

        raise SignalAdapterDependencyError("signal webhook registration unavailable")

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> SignalAdapterHealthResult:
        """Return adapter health by probing Signal runtime health endpoint."""
        request = urllib_request.Request(
            url=f"{self._base_url}/health",
            method="GET",
        )
        try:
            with urllib_request.urlopen(
                request, timeout=self._settings.timeout_seconds
            ):
                return SignalAdapterHealthResult(adapter_ready=True, detail="ok")
        except urllib_error.URLError as exc:
            return SignalAdapterHealthResult(
                adapter_ready=False,
                detail=str(exc.reason) or "signal runtime unavailable",
            )
