"""Node error behaviour, driven through the real nodes with the HTTP layer mocked at httpx."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from griptape_nodes.exe_types.core_types import NodeError
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

LIBRARY = Path(__file__).resolve().parents[3] / "twelvelabs_nodes_library"
REAL_ASYNC_CLIENT = httpx.AsyncClient

NODES = {
    "twelvelabs_analyze_video": "TwelveLabsAnalyzeVideo",
    "twelvelabs_create_index": "TwelveLabsCreateIndex",
    "twelvelabs_index_asset": "TwelveLabsIndexAsset",
    "twelvelabs_ingest_videos": "TwelveLabsIngestVideos",
    "twelvelabs_search_index": "TwelveLabsSearchIndex",
    "twelvelabs_upload_asset": "TwelveLabsUploadAsset",
}

# The body Griptape Cloud returned to a request with a made-up key.
CLOUD_401 = {
    "type": "client_error",
    "errors": [
        {"code": "token_not_valid", "detail": "Given token not valid for any token type", "attr": "detail"},
        {"code": "token_not_valid", "detail": "Token is invalid", "attr": "messages.0.message"},
    ],
}
KEY_LINK = "#settings-secrets?filter=GT_CLOUD_API_KEY"


def load_node_class(module_name: str):
    """Load a node file the way the engine does: standalone, with only the library folder on sys.path."""
    sys.path.insert(0, str(LIBRARY))
    saved = sys.modules.get("twelvelabs_nodes_library")
    sys.modules["twelvelabs_nodes_library"] = None  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(f"engine_style_{module_name}", LIBRARY / f"{module_name}.py")
        assert spec
        assert spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(LIBRARY))
        if saved is None:
            sys.modules.pop("twelvelabs_nodes_library", None)
        else:
            sys.modules["twelvelabs_nodes_library"] = saved
    return getattr(module, NODES[module_name])


class FakeSecrets:
    def __init__(self, key: str | None) -> None:
        self.key = key

    def get_secret(self, name: str, **_: Any) -> str | None:
        return self.key if name == "GT_CLOUD_API_KEY" else None


@pytest.fixture
def set_key(monkeypatch: pytest.MonkeyPatch):
    # Building the upload and ingest nodes reads the real credential, so the environment must hold one.
    # The node's own key check goes through the fake below.
    monkeypatch.setenv("GT_CLOUD_API_KEY", "a-key")

    def _set(key: str | None) -> None:
        monkeypatch.setattr(GriptapeNodes, "SecretsManager", lambda: FakeSecrets(key))

    _set("a-key")
    return _set


class Cloud:
    """A fake Griptape Cloud proxy. Each stage is a (status, body) pair, or a callable returning a response."""

    def __init__(self) -> None:
        self.submit: Any = (200, {"generation_id": "gen-1"})
        self.poll: Any = (200, {"status": "COMPLETED"})
        self.result: Any = (200, {"data": [{"id": "x"}]})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            stage = self.submit
        elif path.endswith("/result"):
            stage = self.result
        else:
            stage = self.poll
        if callable(stage):
            return cast("httpx.Response", stage(request))
        status, body = stage
        headers = {"x-request-id": "req-1"}
        if isinstance(body, bytes | str):
            content = body.encode() if isinstance(body, str) else body
            return httpx.Response(status, content=content, headers={**headers, "content-type": "text/html"})
        return httpx.Response(status, json=body, headers=headers)


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch, set_key) -> Cloud:
    fake = Cloud()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(fake), **kw))
    return fake


def make_node(monkeypatch: pytest.MonkeyPatch, *, failed_wired: bool = False):
    node = load_node_class("twelvelabs_analyze_video")(name="analyze")
    node.set_parameter_value("video_id", "video-1")
    node.set_parameter_value("prompt", "What happens?")
    node.DEFAULT_POLL_INTERVAL = 0
    node.DEFAULT_MAX_ATTEMPTS = 3
    monkeypatch.setattr(node, "_has_outgoing_connections", lambda _output: failed_wired)
    return node


def run(node) -> None:
    asyncio.run(node.aprocess())


@pytest.mark.parametrize("module_name", NODES)
def test_node_file_loads_engine_style(module_name: str) -> None:
    node_class = load_node_class(module_name)
    assert node_class.__name__ == NODES[module_name]


@pytest.mark.parametrize("module_name", NODES)
def test_missing_key_is_the_only_error(module_name: str, set_key) -> None:
    set_key(None)
    node = load_node_class(module_name)(name="node")
    errors = node.validate_before_node_run()
    assert errors is not None
    assert len(errors) == 1
    assert isinstance(errors[0], NodeError)
    assert str(errors[0]).startswith("GT_CLOUD_API_KEY is not set.")
    assert KEY_LINK in [link.url for link in errors[0].links]


def test_input_problems_name_the_parameter_by_label(set_key) -> None:
    node = load_node_class("twelvelabs_analyze_video")(name="analyze")
    errors = node.validate_before_node_run()
    assert errors is not None
    assert [e.fields["parameter"] for e in errors if isinstance(e, NodeError)] == ["video_id", "prompt"]
    assert "'Video ID'" in str(errors[0])
    assert "analyze" not in str(errors[0])


def test_missing_key_at_run_time_raises(monkeypatch: pytest.MonkeyPatch, cloud: Cloud, set_key) -> None:
    node = make_node(monkeypatch)
    set_key(None)
    with pytest.raises(NodeError) as caught:
        run(node)
    assert KEY_LINK in [link.url for link in caught.value.links]


def test_successful_run(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    node = make_node(monkeypatch)
    run(node)
    assert node._execution_succeeded is True
    assert node.parameter_output_values["analysis_result"] == {"data": [{"id": "x"}]}


def test_401_is_a_refused_key_with_a_settings_link(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    cloud.submit = (401, CLOUD_401)
    with pytest.raises(NodeError) as caught:
        run(make_node(monkeypatch))
    error = caught.value
    assert "refused the API key" in str(error)
    assert error.fields["status_code"] == 401
    assert error.fields["request_id"] == "req-1"
    assert error.response == CLOUD_401
    assert [(link.label, link.url) for link in error.links] == [("Update the API key", KEY_LINK)]


def test_403_is_not_a_refused_key(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    body = {"type": "client_error", "errors": [{"code": "permission_denied", "detail": "No access.", "attr": "detail"}]}
    cloud.submit = (403, body)
    with pytest.raises(NodeError) as caught:
        run(make_node(monkeypatch))
    assert str(caught.value) == "No access."
    assert caught.value.fields["status_code"] == 403
    assert caught.value.fields["error_code"] == "permission_denied"
    assert caught.value.links == []


def test_validation_problems_in_the_errors_list_become_the_message(
    monkeypatch: pytest.MonkeyPatch, cloud: Cloud
) -> None:
    cloud.submit = (400, {"errors": [{"code": "required", "detail": "This field is required.", "attr": "index_id"}]})
    with pytest.raises(NodeError) as caught:
        run(make_node(monkeypatch))
    assert str(caught.value) == "index_id: This field is required."
    assert caught.value.links == []


def test_connection_failure_is_a_node_error(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    cloud.submit = refuse
    with pytest.raises(NodeError, match="Could not reach Griptape Cloud"):
        run(make_node(monkeypatch))


def test_submit_without_generation_id(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    cloud.submit = (200, {"something": "else"})
    with pytest.raises(NodeError, match="did not return a generation ID") as caught:
        run(make_node(monkeypatch))
    assert caught.value.response == {"something": "else"}


@pytest.mark.parametrize("wired", [False, True])
def test_failed_generation(monkeypatch: pytest.MonkeyPatch, cloud: Cloud, wired: bool) -> None:
    body = {"status": "FAILED", "status_detail": {"details": "The video is too short."}}
    cloud.poll = (200, body)
    node = make_node(monkeypatch, failed_wired=wired)
    if wired:
        run(node)
        assert node.parameter_output_values["analysis_text"] == ""
        assert node._execution_succeeded is False
        return
    with pytest.raises(NodeError) as caught:
        run(node)
    assert str(caught.value) == "The video is too short."
    assert caught.value.fields == {"generation_id": "gen-1", "status": "FAILED"}
    assert caught.value.response == body


def test_failed_generation_without_details(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    cloud.poll = (200, {"status": "ERRORED"})
    with pytest.raises(NodeError, match="ended with status ERRORED and the API gave no details"):
        run(make_node(monkeypatch))


def test_polling_that_fails_on_every_attempt_raises_the_last_error(
    monkeypatch: pytest.MonkeyPatch, cloud: Cloud
) -> None:
    cloud.poll = (500, {"error": "Upstream is down."})
    with pytest.raises(NodeError) as caught:
        run(make_node(monkeypatch))
    assert str(caught.value) == "Upstream is down."
    assert caught.value.fields["generation_id"] == "gen-1"


def test_polling_that_never_finishes_times_out(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    cloud.poll = (200, {"status": "RUNNING"})
    with pytest.raises(NodeError, match="did not finish") as caught:
        run(make_node(monkeypatch))
    assert caught.value.fields["generation_id"] == "gen-1"


BAD_BODIES = {"html": "<html>Bad gateway</html>", "empty": "", "list": [1, 2]}


@pytest.mark.parametrize("stage", ["submit", "poll", "result"])
@pytest.mark.parametrize("kind", BAD_BODIES)
@pytest.mark.parametrize("wired", [False, True])
def test_a_2xx_body_that_is_not_a_json_object_is_a_node_error(
    monkeypatch: pytest.MonkeyPatch, cloud: Cloud, stage: str, kind: str, wired: bool
) -> None:
    """json() raises ValueError for HTML and empty bodies, and a list has no .get; neither may skip Failed."""
    body = BAD_BODIES[kind]
    if stage == "result":
        # Only a JSON content type is parsed; anything else is returned as bytes.
        def result(_: httpx.Request) -> httpx.Response:
            content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            return httpx.Response(
                200, content=content, headers={"content-type": "application/json", "x-request-id": "req-1"}
            )

        cloud.result = result
    else:
        setattr(cloud, stage, (200, body))

    node = make_node(monkeypatch, failed_wired=wired)
    if wired:
        run(node)
        assert node._execution_succeeded is False
        return
    with pytest.raises(NodeError, match="could not read") as caught:
        run(node)
    assert caught.value.fields["status_code"] == 200
    assert caught.value.fields["request_id"] == "req-1"


def test_ingest_step_is_attached_to_a_failure(monkeypatch: pytest.MonkeyPatch, cloud: Cloud) -> None:
    cloud.submit = (400, {"errors": [{"code": "bad", "detail": "No.", "attr": "detail"}]})
    node = load_node_class("twelvelabs_ingest_videos")(name="ingest")
    with pytest.raises(NodeError) as caught:
        asyncio.run(node._run_proxy_operation(api_model_id="m", payload={}, headers={}, step_label="create index"))
    assert caught.value.fields["step"] == "create index"
