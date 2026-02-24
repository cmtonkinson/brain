"""In-process Signal adapter implementation over HTTP."""

from __future__ import annotations

from packages.brain_shared.http import (
    HttpClient,
    HttpJsonDecodeError,
    HttpRequestError,
    HttpStatusError,
)
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
        self._client = HttpClient(
            base_url=settings.base_url.rstrip("/"),
            timeout_seconds=settings.timeout_seconds,
            headers={"Content-Type": "application/json"},
        )

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
        for attempt in range(self._settings.max_retries + 1):
            try:
                response_payload = self._client.post_json(
                    "/v1/webhooks/register",
                    json=payload,
                )
                registered = bool(response_payload.get("registered", True))
                detail = str(response_payload.get("detail", "registered"))
                return SignalWebhookRegistrationResult(
                    registered=registered,
                    detail=detail,
                )
            except HttpStatusError as exc:
                if exc.retryable and attempt < self._settings.max_retries:
                    continue
                raise SignalAdapterDependencyError(
                    (
                        "signal webhook registration failed with status "
                        f"{exc.status_code}"
                    )
                ) from None
            except HttpRequestError as exc:
                if attempt < self._settings.max_retries:
                    continue
                raise SignalAdapterDependencyError(
                    str(exc) or "signal webhook registration unavailable"
                ) from None
            except HttpJsonDecodeError as exc:
                raise SignalAdapterInternalError(
                    f"signal registration response JSON invalid: {exc}"
                ) from None

        raise SignalAdapterDependencyError("signal webhook registration unavailable")

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> SignalAdapterHealthResult:
        """Return adapter health by probing Signal runtime health endpoint."""
        try:
            self._client.get("/health")
            return SignalAdapterHealthResult(adapter_ready=True, detail="ok")
        except (HttpRequestError, HttpStatusError, HttpJsonDecodeError) as exc:
            return SignalAdapterHealthResult(
                adapter_ready=False,
                detail=str(exc) or "signal runtime unavailable",
            )
