from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any
from urllib.parse import urljoin

import httpx
from griptape_nodes.exe_types.core_types import NodeError
from griptape_nodes.exe_types.node_types import SuccessFailureNode
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

logger = logging.getLogger("griptape_nodes")

__all__ = ["GriptapeProxyNode"]

API_KEY_NAME = "GT_CLOUD_API_KEY"
API_KEY_URL = "https://cloud.griptape.ai/configuration/api-keys"
PROVIDER = "Griptape Cloud"
HTTP_UNAUTHORIZED = 401


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    """The response body when it is a non-empty JSON object, else None."""
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) and body else None


def _failure_reason(body: dict[str, Any]) -> str | None:
    """The reason text Griptape Cloud gives, which `NodeError.from_http_response` only partly reads.

    Reads `status_detail.details`, `error`, and the `errors` list as "attr: detail".
    """
    status_detail = body.get("status_detail")
    if isinstance(status_detail, dict) and isinstance(details := status_detail.get("details"), str) and details.strip():
        return details.strip()
    error = body.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    errors = body.get("errors")
    entries = (
        [e for e in errors if isinstance(e, dict) and isinstance(e.get("detail"), str)]
        if isinstance(errors, list)
        else []
    )
    problems = [
        f"{e['attr']}: {e['detail']}" if e.get("attr") not in (None, "", "detail") else e["detail"] for e in entries
    ]
    return "; ".join(dict.fromkeys(problems)) or None


def _api_error(response: httpx.Response, **fields: str | int | float | bool) -> NodeError:
    """The error for an HTTP failure. Only a 401 counts as a refused key; a 403 is a permission problem."""
    status = response.status_code
    body = _json_object(response) or {}
    errors = body.get("errors")
    codes = (
        [e["code"] for e in errors if isinstance(e, dict) and isinstance(e.get("code"), str)]
        if isinstance(errors, list)
        else []
    )
    if codes:
        fields = {"error_code": codes[0], **fields}
    error = NodeError.from_http_response(
        response, provider=PROVIDER, secret_name=API_KEY_NAME, key_refused=status == HTTP_UNAUTHORIZED, fields=fields
    )
    reason = _failure_reason(body)
    if reason and status != HTTP_UNAUTHORIZED:
        return NodeError(reason, fields=error.fields, response=error.response, links=error.links)
    return error


def _request_error(exc: httpx.HTTPError, **fields: str | int | float | bool) -> NodeError:
    if isinstance(exc, httpx.HTTPStatusError):
        return _api_error(exc.response, **fields)
    return NodeError.from_request_exception(
        exc, provider=PROVIDER, secret_name=API_KEY_NAME, key_refused=False, fields=fields
    )


def _success_body(response: httpx.Response, **fields: str | int | float | bool) -> dict[str, Any]:
    """The JSON object in a 2xx response. Anything else raises a NodeError, so Failed routing still works."""
    body = _json_object(response)
    if body is None:
        raise NodeError.from_http_response(
            response, provider=PROVIDER, secret_name=API_KEY_NAME, key_refused=False, fields=fields
        )
    return body


class GriptapeProxyNode(SuccessFailureNode, ABC):
    """Base class for nodes that use the Griptape Cloud v2 async model proxy API.

    This class provides common functionality for nodes that:
    1. Submit generation requests to POST /api/proxy/v2/models/{model_id}
    2. Poll generation status via GET /api/proxy/v2/generations/{generation_id}
    3. Handle terminal states (COMPLETED, FAILED, ERRORED)
    4. Fetch final results from GET /api/proxy/v2/generations/{generation_id}/result

    Subclasses must implement:
    - _build_payload(): Build the request payload for generation submission
    - _parse_result(): Parse the model-specific result data
    - _set_safe_defaults(): Clear output parameters on error

    This base class handles all polling logic, API error handling, and status management.
    """

    SERVICE_NAME = "Griptape"

    # Polling configuration
    DEFAULT_POLL_INTERVAL = 5
    DEFAULT_MAX_ATTEMPTS = 120  # 10 minutes with 5s intervals

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # Compute API base once
        base = os.getenv("GT_CLOUD_BASE_URL", "https://cloud.griptape.ai")
        base_slash = base if base.endswith("/") else base + "/"
        api_base = urljoin(base_slash, "api/")
        self._proxy_base = urljoin(api_base, "proxy/v2/")
        self._user_auth_info: str | None = None

    def register_user_auth_info(self, user_auth_info: str | None) -> None:
        """Register optional user auth info to send with generation submissions."""
        self._user_auth_info = user_auth_info

    @abstractmethod
    async def _build_payload(self) -> dict[str, Any]:
        """Build the request payload for generation submission.

        This method must be implemented by subclasses to build the model-specific
        payload that will be sent to POST /api/proxy/v2/models/{model_id}.

        This method is async to support operations like image downloading/encoding.

        Returns:
            dict: The request payload to send to the API
        """

    @abstractmethod
    async def _parse_result(self, result_json: dict[str, Any], generation_id: str) -> None:
        """Parse the model-specific result data and set output parameters.

        This method must be implemented by subclasses to parse the result data
        from GET /api/proxy/v2/generations/{generation_id}/result and set the
        appropriate output parameters.

        Args:
            result_json: The JSON response from the /result endpoint
            generation_id: The generation ID for this request
        """

    @abstractmethod
    def _set_safe_defaults(self) -> None:
        """Clear all output parameters on error.

        This method must be implemented by subclasses to reset all output
        parameters to safe default values when an error occurs.
        """

    def _get_api_model_id(self) -> str:
        """Get the API model ID for this generation.

        Subclasses can override this if they need to map friendly names to API IDs.
        By default, returns the value of the 'model' parameter if it exists.

        Returns:
            str: The model ID to use in the API request
        """
        return self.get_parameter_value("model") or ""

    def _validate_api_key(self) -> str:
        """Return the API key, or raise the missing-key error."""
        api_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_NAME, should_error_on_not_found=False)
        if not api_key:
            raise NodeError.from_missing_secret(API_KEY_NAME, key_url=API_KEY_URL)
        return api_key

    def validate_before_node_run(self) -> list[Exception] | None:
        """Report a missing API key first and on its own, before the node starts."""
        try:
            self._validate_api_key()
        except NodeError as e:
            return [e]
        return super().validate_before_node_run()

    @staticmethod
    def _input_error(message: str, parameter: str) -> NodeError:
        return NodeError(message, fields={"parameter": parameter})

    def _log(self, message: str) -> None:
        """Log a message with error suppression."""
        with suppress(Exception):
            logger.info(message)

    async def _submit_generation(self, payload: dict[str, Any], headers: dict[str, str], api_model_id: str) -> str:
        """Submit the generation request to the v2 API and return its generation ID."""
        proxy_url = urljoin(self._proxy_base, f"models/{api_model_id}")
        self._log(f"Submitting generation request to {proxy_url}")

        try:
            async with httpx.AsyncClient() as client:
                request_headers = headers.copy()
                if self._user_auth_info:
                    request_headers["X-GTC-PROXY-AUTH-INFO"] = self._user_auth_info
                response = await client.post(proxy_url, json=payload, headers=request_headers, timeout=60)
                response.raise_for_status()
        except httpx.HTTPError as e:
            self._log(f"Request failed: {e}")
            raise _request_error(e) from e

        response_json = _success_body(response)
        generation_id = response_json.get("generation_id")
        if not generation_id:
            msg = "Griptape Cloud accepted the request but did not return a generation ID."
            raise NodeError(msg, response=response_json)
        self._log(f"Submitted. generation_id={generation_id}")
        return str(generation_id)

    async def _poll_generation_status(self, generation_id: str, headers: dict[str, str]) -> dict[str, Any]:
        """Poll until the generation completes. Raises if it fails, times out, or polling keeps failing."""
        get_url = urljoin(self._proxy_base, f"generations/{generation_id}")
        max_attempts = self.DEFAULT_MAX_ATTEMPTS
        poll_interval = self.DEFAULT_POLL_INTERVAL

        async with httpx.AsyncClient() as client:
            for attempt in range(max_attempts):
                self._log(f"Polling attempt #{attempt + 1} for generation {generation_id}")
                try:
                    response = await client.get(get_url, headers=headers, timeout=60)
                    response.raise_for_status()
                    result_json = _success_body(response, generation_id=generation_id)
                except (httpx.HTTPError, NodeError) as e:
                    self._log(f"Error while polling: {e}")
                    if attempt < max_attempts - 1:
                        continue
                    if isinstance(e, NodeError):
                        raise
                    raise _request_error(e, generation_id=generation_id) from e

                status = result_json.get("status", "unknown")
                self._log(f"Status: {status}")

                if status == "COMPLETED":
                    return result_json

                if status in ["FAILED", "ERRORED"]:
                    logger.error("%s: Generation failed with status %s: %s", self.name, status, result_json)
                    msg = (
                        _failure_reason(result_json)
                        or f"The generation ended with status {status} and the API gave no details."
                    )
                    raise NodeError(
                        msg, fields={"generation_id": generation_id, "status": status}, response=result_json
                    )

                # Still processing (QUEUED or RUNNING), wait before next poll
                if attempt < max_attempts - 1:
                    await asyncio.sleep(poll_interval)

        msg = f"The generation did not finish within {max_attempts * poll_interval} seconds."
        raise NodeError(msg, fields={"generation_id": generation_id})

    async def _fetch_generation_result(self, generation_id: str) -> dict[str, Any]:
        """Fetch the final result from the /result endpoint, as JSON or raw bytes."""
        result_url = urljoin(self._proxy_base, f"generations/{generation_id}/result")
        self._log(f"Fetching result from {result_url}")

        headers = {"Authorization": f"Bearer {self._validate_api_key()}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(result_url, headers=headers, timeout=300)
                response.raise_for_status()
        except httpx.HTTPError as e:
            self._log(f"Error fetching result: {e}")
            raise _request_error(e, generation_id=generation_id) from e

        # Check Content-Type to determine if response is JSON or binary
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            return _success_body(response, generation_id=generation_id)

        # Handle binary responses (raw audio, video, etc.)
        self._log(f"Result fetched successfully (binary, content-type: {content_type})")
        return {"raw_bytes": response.content}

    def _fail(self, error: Exception) -> None:
        """Clear the outputs and report a failure: follow a wired Failed output, else raise."""
        self._set_safe_defaults()
        self._set_status_results(was_successful=False, result_details=str(error))
        self._handle_failure_exception(error)

    async def _submit_and_poll(self, headers: dict[str, str]) -> str:
        """Submit the generation request, wait for it to complete, and return its generation ID."""
        payload = await self._build_payload()

        api_model_id = self._get_api_model_id()
        if not api_model_id:
            msg = "No model ID is set for this node."
            raise NodeError(msg)

        generation_id = await self._submit_generation(payload, headers, api_model_id)

        # Store generation_id if output parameter exists
        if "generation_id" in self.parameter_output_values:
            self.parameter_output_values["generation_id"] = generation_id

        await self._poll_generation_status(generation_id, headers)
        return generation_id

    async def _run_generation(self) -> None:
        api_key = self._validate_api_key()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        generation_id = await self._submit_and_poll(headers)
        result_json = await self._fetch_generation_result(generation_id)

        # Store provider_response if output parameter exists
        if "provider_response" in self.parameter_output_values:
            self.parameter_output_values["provider_response"] = result_json

        await self._parse_result(result_json, generation_id)

    async def _process_generation(self) -> None:
        """Main processing logic: validate the key, submit, poll, fetch and parse the result."""
        # Clear execution status at the start
        self._clear_execution_status()

        try:
            await self._run_generation()
        except Exception as e:
            self._fail(e)

    async def aprocess(self) -> None:
        """Async processing entry point."""
        await self._process_generation()

    @staticmethod
    async def _download_bytes_from_url(url: str) -> bytes | None:
        """Download bytes from a URL.

        Args:
            url: The URL to download from

        Returns:
            bytes | None: The downloaded bytes, or None if download failed
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=120)
                resp.raise_for_status()
                return resp.content
        except Exception:
            return None
