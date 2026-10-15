from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from griptape_nodes.exe_types.core_types import NodeError, NodeErrorLink
from griptape_nodes.exe_types.node_types import SuccessFailureNode
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

logger = logging.getLogger("griptape_nodes")

__all__ = ["GriptapeProxyNode"]

# NodeError drops a response over 16 KB, so attach at most this many characters of it.
MAX_RESPONSE_CHARS = 12000


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
    API_KEY_NAME = "GT_CLOUD_API_KEY"

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

    def _extract_error_message(self, response_json: dict[str, Any]) -> str | None:
        """Extract the provider's own error message from an error or failed-generation body.

        Looks, in order, at:
        1. status_detail.details (user-oriented message)
        2. a string status_detail
        3. the top-level error field
        4. the errors list used by Griptape Cloud error responses
        5. top-level detail or message fields

        Subclasses can override this to add model-specific error extraction logic.

        Args:
            response_json: The parsed JSON body of an error or failed-generation response

        Returns:
            str | None: The message, or None when the body holds no usable text
        """
        if not isinstance(response_json, dict):
            return None

        status_detail = response_json.get("status_detail")
        if isinstance(status_detail, dict):
            details = status_detail.get("details")
            if details:
                return str(details)
        elif isinstance(status_detail, str) and status_detail.strip():
            return status_detail.strip()

        error = response_json.get("error")
        if isinstance(error, dict):
            error_msg = error.get("message") or error.get("error")
            if error_msg:
                return str(error_msg)
        elif error:
            return str(error)

        errors_message = self._join_error_list(response_json.get("errors"))
        if errors_message:
            return errors_message

        for key in ("detail", "message"):
            value = response_json.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    @staticmethod
    def _join_error_list(errors: Any) -> str | None:
        """Join the detail strings of a Griptape Cloud style `errors` list."""
        if not isinstance(errors, list):
            return None

        messages: list[str] = []
        for item in errors:
            if not isinstance(item, dict):
                continue
            detail = item.get("detail")
            if not isinstance(detail, str) or not detail.strip():
                continue
            attr = item.get("attr")
            text = detail.strip()
            if isinstance(attr, str) and attr and attr not in ("detail", "code", "non_field_errors"):
                text = f"{attr}: {text}"
            if text not in messages:
                messages.append(text)
        return " ".join(messages) if messages else None

    def _get_api_model_id(self) -> str:
        """Get the API model ID for this generation.

        Subclasses can override this if they need to map friendly names to API IDs.
        By default, returns the value of the 'model' parameter if it exists.

        Returns:
            str: The model ID to use in the API request
        """
        return self.get_parameter_value("model") or ""

    def _api_key_link(self, label: str) -> NodeErrorLink:
        return NodeErrorLink(label=label, url=f"#settings-secrets?filter={quote(self.API_KEY_NAME)}")

    def _validate_api_key(self) -> str:
        """Validate and return the API key.

        Returns:
            str: The API key

        Raises:
            NodeError: If the API key is missing
        """
        api_key = GriptapeNodes.SecretsManager().get_secret(self.API_KEY_NAME)
        if not api_key:
            msg = f"{self.API_KEY_NAME} is not set. Add it in Settings → API Keys & Secrets, then run the node again."
            raise NodeError(msg, links=[self._api_key_link("Add the API key")])
        return api_key

    def _log(self, message: str) -> None:
        """Log a message with error suppression."""
        with suppress(Exception):
            logger.info(message)

    @staticmethod
    def _bounded_response(body: dict[str, Any] | None, text: str = "") -> dict[str, Any]:
        """Return a response dict that fits the NodeError size limit."""
        if body is not None:
            serialized = json.dumps(body, default=str)
            if len(serialized) <= MAX_RESPONSE_CHARS:
                return body
            return {"truncated_body": serialized[:MAX_RESPONSE_CHARS]}
        return {"body": text[:MAX_RESPONSE_CHARS]}

    @staticmethod
    def _response_fields(response: httpx.Response, generation_id: str | None) -> dict[str, str | int | float | bool]:
        """The status code, request ID and generation ID that identify a response."""
        fields: dict[str, str | int | float | bool] = {"status_code": response.status_code}
        request_id = response.headers.get("x-request-id")
        if request_id:
            fields["request_id"] = request_id
        if generation_id:
            fields["generation_id"] = generation_id
        return fields

    def _json_object(
        self, response: httpx.Response, *, action: str, generation_id: str | None = None
    ) -> dict[str, Any]:
        """Return the JSON object in a successful response, or raise a NodeError when the body is something else.

        Args:
            response: The response, which has already passed `raise_for_status`
            action: What the node was doing, as a gerund phrase such as "submitting the request"
            generation_id: The generation this request belongs to, when there is one
        """
        try:
            parsed = response.json()
        except ValueError as e:
            error = self._not_json_error(response, action=action, generation_id=generation_id)
            raise error from e
        if not isinstance(parsed, dict):
            raise self._not_json_error(response, action=action, generation_id=generation_id)
        return parsed

    def _not_json_error(self, response: httpx.Response, *, action: str, generation_id: str | None) -> NodeError:
        """Build a NodeError for a successful response whose body is not a JSON object."""
        msg = f"Griptape Cloud answered with something other than JSON while {action}. Run the node again."
        return NodeError(
            msg,
            fields=self._response_fields(response, generation_id),
            response=self._bounded_response(None, response.text),
        )

    def _http_error(self, response: httpx.Response, *, action: str, generation_id: str | None = None) -> NodeError:
        """Build a NodeError from a failed Griptape Cloud HTTP response.

        Args:
            response: The failed response
            action: What the node was doing, as a gerund phrase such as "submitting the request"
            generation_id: The generation this request belongs to, when there is one
        """
        status_code = response.status_code
        fields = self._response_fields(response, generation_id)

        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        body = parsed if isinstance(parsed, dict) else None
        attached = self._bounded_response(body, response.text)

        if status_code in (401, 403):
            msg = (
                f"Griptape Cloud refused {self.API_KEY_NAME}. "
                "Update the key in Settings → API Keys & Secrets, then run the node again."
            )
            return NodeError(msg, fields=fields, response=attached, links=[self._api_key_link("Update the API key")])

        if status_code == 429:
            msg = "Griptape Cloud is rate-limiting requests. Wait a minute and run the node again."
            return NodeError(msg, fields=fields, response=attached)

        provider_message = self._extract_error_message(body) if body else None
        msg = provider_message or f"Griptape Cloud returned HTTP {status_code} while {action}."
        return NodeError(msg, fields=fields, response=attached)

    @staticmethod
    def _connection_error(error: Exception, *, action: str, generation_id: str | None = None) -> NodeError:
        """Build a NodeError for a request that never got an HTTP response."""
        fields: dict[str, str | int | float | bool] = {}
        if generation_id:
            fields["generation_id"] = generation_id
        detail = str(error) or type(error).__name__
        msg = f"Could not reach Griptape Cloud while {action} ({detail}). Check your connection and run the node again."
        return NodeError(msg, fields=fields)

    async def _submit_generation(self, payload: dict[str, Any], headers: dict[str, str], api_model_id: str) -> str:
        """Submit generation request to the v2 API.

        Args:
            payload: The request payload
            headers: HTTP headers including Authorization
            api_model_id: The model ID to use in the URL

        Returns:
            str: The generation ID

        Raises:
            NodeError: If the request fails or the response has no generation ID
        """
        proxy_url = urljoin(self._proxy_base, f"models/{api_model_id}")
        self._log(f"Submitting generation request to {proxy_url}")

        action = "submitting the request"
        try:
            async with httpx.AsyncClient() as client:
                request_headers = headers.copy()
                if self._user_auth_info:
                    request_headers["X-GTC-PROXY-AUTH-INFO"] = self._user_auth_info
                response = await client.post(proxy_url, json=payload, headers=request_headers, timeout=60)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._log(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise self._http_error(e.response, action=action) from e
        except Exception as e:
            self._log(f"Request failed: {e}")
            raise self._connection_error(e, action=action) from e

        response_json = self._json_object(response, action=action)
        self._log("Request submitted successfully")

        generation_id = response_json.get("generation_id")
        if generation_id:
            self._log(f"Submitted. generation_id={generation_id}")
            return str(generation_id)

        self._log("No generation_id returned from POST response")
        msg = "Griptape Cloud accepted the request but did not return a generation ID. Run the node again."
        raise NodeError(msg, response=self._bounded_response(response_json))

    async def _poll_generation_status(self, generation_id: str, headers: dict[str, str]) -> dict[str, Any]:
        """Poll generation status until terminal state is reached.

        Args:
            generation_id: The generation ID to poll
            headers: HTTP headers including Authorization

        Returns:
            dict: The final status response

        Raises:
            NodeError: If the generation fails, polling keeps failing, or the generation times out
        """
        get_url = urljoin(self._proxy_base, f"generations/{generation_id}")
        max_attempts = self.DEFAULT_MAX_ATTEMPTS
        poll_interval = self.DEFAULT_POLL_INTERVAL
        action = "checking the generation status"

        async with httpx.AsyncClient() as client:
            for attempt in range(max_attempts):
                self._log(f"Polling attempt #{attempt + 1} for generation {generation_id}")
                try:
                    response = await client.get(get_url, headers=headers, timeout=60)
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    self._log(f"HTTP error while polling: {e.response.status_code} - {e.response.text}")
                    if attempt == max_attempts - 1:
                        raise self._http_error(e.response, action=action, generation_id=generation_id) from e
                    continue
                except Exception as e:
                    self._log(f"Error while polling: {e}")
                    if attempt == max_attempts - 1:
                        raise self._connection_error(e, action=action, generation_id=generation_id) from e
                    continue

                try:
                    result_json = self._json_object(response, action=action, generation_id=generation_id)
                except NodeError as e:
                    self._log(f"Unreadable response while polling: {e}")
                    if attempt == max_attempts - 1:
                        raise
                    continue

                status = result_json.get("status", "unknown")
                self._log(f"Status: {status}")

                if status == "COMPLETED":
                    return result_json

                if status in ["FAILED", "ERRORED"]:
                    logger.error("Generation %s failed with status %s: %s", generation_id, status, result_json)
                    msg = self._extract_error_message(result_json) or (
                        f"The generation ended with status {status} and the API gave no details."
                    )
                    raise NodeError(
                        msg,
                        fields={"generation_id": generation_id, "status": status},
                        response=self._bounded_response(result_json),
                    )

                # Still processing (QUEUED or RUNNING), wait before next poll
                if attempt < max_attempts - 1:
                    await asyncio.sleep(poll_interval)

        self._log("Polling timed out waiting for result")
        msg = (
            f"The generation did not finish within {max_attempts * poll_interval} seconds. "
            "Run the node again. If it keeps happening, contact support with the generation ID."
        )
        raise NodeError(msg, fields={"generation_id": generation_id})

    async def _fetch_generation_result(self, generation_id: str) -> dict[str, Any]:
        """Fetch the final result from the /result endpoint.

        Args:
            generation_id: The generation ID

        Returns:
            dict: The result JSON, or a dict holding the raw bytes for a binary result

        Raises:
            NodeError: If the API key is missing, the fetch fails, or the result is empty
        """
        result_url = urljoin(self._proxy_base, f"generations/{generation_id}/result")
        self._log(f"Fetching result from {result_url}")

        api_key = self._validate_api_key()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        action = "fetching the generation result"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(result_url, headers=headers, timeout=300)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._log(f"HTTP error fetching result: {e.response.status_code} - {e.response.text}")
            raise self._http_error(e.response, action=action, generation_id=generation_id) from e
        except Exception as e:
            self._log(f"Error fetching result: {e}")
            raise self._connection_error(e, action=action, generation_id=generation_id) from e

        # Check Content-Type to determine if response is JSON or binary
        content_type = response.headers.get("content-type", "").lower()

        if "application/json" in content_type:
            result_json = self._json_object(response, action=action, generation_id=generation_id)
            self._log("Result fetched successfully (JSON)")
            if not result_json:
                msg = "Griptape Cloud returned an empty result. Run the node again."
                raise NodeError(msg, fields={"generation_id": generation_id})
            return result_json

        # Handle binary responses (raw audio, video, etc.)
        self._log(f"Result fetched successfully (binary, content-type: {content_type})")
        return {"raw_bytes": response.content}

    def _fail(self, error: Exception) -> None:
        """Report a failure: clear outputs, set status, and follow Failed or raise."""
        self._log(f"Node failed: {error}")
        self._set_safe_defaults()
        self._set_status_results(was_successful=False, result_details=str(error))
        self._handle_failure_exception(error)

    async def _generate(self) -> None:
        """Run the generation flow. Any failure raises."""
        api_key = self._validate_api_key()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        payload = await self._build_payload()

        api_model_id = self._get_api_model_id()
        if not api_model_id:
            msg = "No model is selected. Choose one in 'Model' and run the node again."
            raise NodeError(msg, fields={"parameter": "model"})

        generation_id = await self._submit_generation(payload, headers, api_model_id)

        # Store generation_id if output parameter exists
        if "generation_id" in self.parameter_output_values:
            self.parameter_output_values["generation_id"] = generation_id

        await self._poll_generation_status(generation_id, headers)

        result_json = await self._fetch_generation_result(generation_id)

        # Store provider_response if output parameter exists
        if "provider_response" in self.parameter_output_values:
            self.parameter_output_values["provider_response"] = result_json

        await self._parse_result(result_json, generation_id)

    async def _process_generation(self) -> None:
        """Main processing logic that orchestrates the generation flow.

        This method handles:
        1. API key validation
        2. Payload building
        3. Generation submission
        4. Status polling
        5. Result fetching and parsing

        Every failure goes through `_fail`.
        """
        # Clear execution status at the start
        self._clear_execution_status()

        try:
            await self._generate()
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
