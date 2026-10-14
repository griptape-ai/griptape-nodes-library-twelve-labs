"""Tests for the errors the TwelveLabs nodes raise, driven through the real nodes and httpx's own transport."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from griptape_nodes.exe_types.core_types import NodeError
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "twelvelabs_nodes_library"
PACKAGE_NAME = "twelvelabs_nodes_library"
NODE_FILES = [
    "twelvelabs_analyze_video",
    "twelvelabs_create_index",
    "twelvelabs_index_asset",
    "twelvelabs_ingest_videos",
    "twelvelabs_search_index",
    "twelvelabs_upload_asset",
]
SECRET_LINK = "#settings-secrets?filter=GT_CLOUD_API_KEY"

# The body Griptape Cloud returns for a rejected token.
TOKEN_REJECTED_BODY = {
    "type": "client_error",
    "errors": [
        {"code": "token_not_valid", "detail": "Given token not valid for any token type", "attr": "detail"},
        {"code": "token_not_valid", "detail": "Token is invalid", "attr": "messages.0.message"},
    ],
}


def _load_node_module(stem: str) -> Any:
    """Load a node file the way the engine does: no parent package, the library folder on sys.path."""
    sys.path.insert(0, str(LIBRARY_DIR))
    saved = {name: sys.modules.get(name) for name in (PACKAGE_NAME, stem, "griptape_proxy_node")}
    sys.modules[PACKAGE_NAME] = None  # type: ignore[assignment]
    sys.modules.pop("griptape_proxy_node", None)
    try:
        spec = importlib.util.spec_from_file_location(f"engine_loaded_{stem}", LIBRARY_DIR / f"{stem}.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(LIBRARY_DIR))
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return module


@pytest.mark.parametrize("stem", NODE_FILES)
def test_node_file_loads_the_way_the_engine_loads_it(stem: str) -> None:
    module = _load_node_module(stem)

    assert module.__all__[0] in vars(module)


Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    """Serve Griptape Cloud from a handler, through httpx's real client and MockTransport."""
    real_client = httpx.AsyncClient

    def install(handler: Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def factory(*_: Any, **kwargs: Any) -> httpx.AsyncClient:
            return real_client(transport=httpx.MockTransport(recording), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return seen

    return install


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = GriptapeNodes.SecretsManager()
    monkeypatch.setattr(secrets, "get_secret", lambda name, **_: "fake-key" if name == "GT_CLOUD_API_KEY" else None)


def _analyze_node() -> Any:
    module = _load_node_module("twelvelabs_analyze_video")
    node = module.TwelveLabsAnalyzeVideo(name="Analyze")
    node.DEFAULT_POLL_INTERVAL = 0
    node.DEFAULT_MAX_ATTEMPTS = 3
    node.set_parameter_value("video_id", "vid1")
    node.set_parameter_value("prompt", "What happens?")
    node._has_outgoing_connections = lambda _param: False
    return node


def _json(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def _run(node: Any) -> None:
    asyncio.run(node.aprocess())


def test_missing_api_key_links_to_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GriptapeNodes.SecretsManager(), "get_secret", lambda *_, **__: None)
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert str(raised.value) == (
        "GT_CLOUD_API_KEY is not set. Add it in Settings → API Keys & Secrets, then run the node again."
    )
    assert [(link.label, link.url) for link in raised.value.links] == [("Add the API key", SECRET_LINK)]


def test_refused_api_key_links_to_update_it_and_attaches_the_body(api_key: None, cloud: Any) -> None:
    cloud(lambda _request: _json(401, TOKEN_REJECTED_BODY, {"x-request-id": "req-123"}))
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    error = raised.value
    assert str(error) == (
        "Griptape Cloud refused GT_CLOUD_API_KEY. Update the key in Settings → API Keys & Secrets, "
        "then run the node again."
    )
    assert error.fields == {"status_code": 401, "request_id": "req-123"}
    assert error.response == TOKEN_REJECTED_BODY
    assert [(link.label, link.url) for link in error.links] == [("Update the API key", SECRET_LINK)]


def test_failed_generation_follows_failed_output_when_wired(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        return _json(200, {"status": "FAILED", "status_detail": {"details": "The video is too short."}})

    cloud(handler)
    node = _analyze_node()
    node._has_outgoing_connections = lambda _param: True

    _run(node)

    assert node._execution_succeeded is False
    assert node.parameter_output_values["result_details"] == "The video is too short."
    assert node.parameter_output_values["analysis_text"] == ""


def test_failed_generation_uses_the_provider_message_and_attaches_the_status(api_key: None, cloud: Any) -> None:
    status_body = {"status": "ERRORED", "status_detail": {"details": "The video is too short."}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        return _json(200, status_body)

    cloud(handler)
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert str(raised.value) == "The video is too short."
    assert raised.value.fields == {"generation_id": "gen-1", "status": "ERRORED"}
    assert raised.value.response == status_body
    assert "Analyze" not in str(raised.value)


def test_failed_generation_without_details_still_raises(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        return _json(200, {"status": "FAILED"})

    cloud(handler)
    node = _analyze_node()

    with pytest.raises(NodeError, match="status FAILED and the API gave no details"):
        _run(node)


def test_submit_rejection_reads_the_message_from_the_error_list(api_key: None, cloud: Any) -> None:
    body = {
        "type": "validation_error",
        "errors": [{"code": "required", "detail": "This field is required.", "attr": "index_id"}],
    }
    cloud(lambda _request: _json(400, body, {"x-request-id": "req-9"}))
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert str(raised.value) == "index_id: This field is required."
    assert raised.value.fields == {"status_code": 400, "request_id": "req-9"}
    assert raised.value.response == body
    assert raised.value.links == []


def test_rate_limit_asks_the_user_to_wait(api_key: None, cloud: Any) -> None:
    cloud(lambda _request: _json(429, {"detail": "slow down"}))
    node = _analyze_node()

    with pytest.raises(NodeError, match="rate-limiting requests") as raised:
        _run(node)

    assert raised.value.fields == {"status_code": 429}


def test_html_error_page_is_attached_as_text(api_key: None, cloud: Any) -> None:
    cloud(lambda _request: httpx.Response(502, text="<html>Bad gateway</html>"))
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert str(raised.value) == "Griptape Cloud returned HTTP 502 while submitting the request."
    assert raised.value.response == {"body": "<html>Bad gateway</html>"}


def test_unreachable_cloud_raises_a_connection_error(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    cloud(handler)
    node = _analyze_node()

    with pytest.raises(NodeError, match="Could not reach Griptape Cloud while submitting the request"):
        _run(node)


def test_missing_generation_id_raises_with_the_response(api_key: None, cloud: Any) -> None:
    cloud(lambda _request: _json(200, {"unexpected": True}))
    node = _analyze_node()

    with pytest.raises(NodeError, match="did not return a generation ID") as raised:
        _run(node)

    assert raised.value.response == {"unexpected": True}


def test_polling_errors_raise_after_the_last_attempt_with_the_generation_id(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        return _json(500, {"detail": "boom"})

    seen = cloud(handler)
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert str(raised.value) == "boom"
    assert raised.value.fields == {"status_code": 500, "generation_id": "gen-1"}
    assert len([r for r in seen if r.method == "GET"]) == 3


def test_generation_that_never_finishes_times_out_with_the_generation_id(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        return _json(200, {"status": "RUNNING"})

    cloud(handler)
    node = _analyze_node()

    with pytest.raises(NodeError, match="did not finish within") as raised:
        _run(node)

    assert raised.value.fields == {"generation_id": "gen-1"}


def test_result_fetch_failure_raises_with_status_and_generation_id(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        if request.url.path.endswith("/result"):
            return _json(404, {"detail": "Result not found."})
        return _json(200, {"status": "COMPLETED"})

    cloud(handler)
    node = _analyze_node()

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert str(raised.value) == "Result not found."
    assert raised.value.fields == {"status_code": 404, "generation_id": "gen-1"}


def test_result_without_an_id_raises_instead_of_stopping_quietly(api_key: None, cloud: Any) -> None:
    module = _load_node_module("twelvelabs_create_index")
    node = module.TwelveLabsCreateIndex(name="Create")
    node.DEFAULT_POLL_INTERVAL = 0
    node._has_outgoing_connections = lambda _param: False

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        if request.url.path.endswith("/result"):
            return _json(200, {"name": "idx"})
        return _json(200, {"status": "COMPLETED"})

    cloud(handler)

    with pytest.raises(NodeError, match="no index ID") as raised:
        _run(node)

    assert raised.value.fields == {"generation_id": "gen-1"}
    assert raised.value.response == {"name": "idx"}


def test_successful_run_still_succeeds(api_key: None, cloud: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json(200, {"generation_id": "gen-1"})
        if request.url.path.endswith("/result"):
            return _json(200, {"data": [{"text": "A cat jumps."}]})
        return _json(200, {"status": "COMPLETED"})

    cloud(handler)
    node = _analyze_node()

    _run(node)

    assert node.parameter_output_values["analysis_text"] == "A cat jumps."


def _problems(node: Any) -> list[NodeError]:
    problems = node.validate_before_node_run() or []
    assert all(isinstance(problem, NodeError) for problem in problems)
    return problems


def test_analyze_video_lists_each_empty_input_by_label() -> None:
    module = _load_node_module("twelvelabs_analyze_video")
    node = module.TwelveLabsAnalyzeVideo(name="Analyze")

    problems = _problems(node)

    assert [str(p) for p in problems] == [
        "'Video ID' is required. Enter the ID of an indexed TwelveLabs video.",
        "'Prompt' is required. Enter what you want to know about the video.",
    ]
    assert [p.fields for p in problems] == [{"parameter": "video_id"}, {"parameter": "prompt"}]


def test_create_index_names_the_parameters_to_fix() -> None:
    module = _load_node_module("twelvelabs_create_index")
    node = module.TwelveLabsCreateIndex(name="Create")
    node.set_parameter_value("marengo_model_name", "")
    node.set_parameter_value("pegasus_model_name", "")
    node.set_parameter_value("visual", False)
    node.set_parameter_value("audio", False)
    node.set_parameter_value("addons_csv", "thumbnail")

    assert [str(p) for p in _problems(node)] == [
        "No model is selected. Choose one in 'Marengo Model' or 'Pegasus Model'.",
        "No model option is turned on. Turn on 'Visual' or 'Audio'.",
        "'Addons (CSV)' needs a Marengo model. Choose one in 'Marengo Model' or clear 'Addons (CSV)'.",
    ]


def test_upload_asset_rejects_both_and_neither_source() -> None:
    module = _load_node_module("twelvelabs_upload_asset")
    node = module.TwelveLabsUploadAsset(name="Upload")
    node.set_parameter_value("index_id", "idx")

    assert [str(p) for p in _problems(node)] == [
        "Nothing to upload. Connect a video to 'Video' or enter a public link in 'Asset URL'."
    ]

    node.set_parameter_value("video", {"type": "VideoUrlArtifact", "value": "http://x/v.mp4"})
    node.set_parameter_value("asset_url", "https://example.com/v.mp4")

    assert [str(p) for p in _problems(node)] == [
        "Both 'Video' and 'Asset URL' are set. Clear one of them and run the node again."
    ]


def test_index_search_and_ingest_name_empty_inputs() -> None:
    index_asset = _load_node_module("twelvelabs_index_asset").TwelveLabsIndexAsset(name="Index")
    search = _load_node_module("twelvelabs_search_index").TwelveLabsSearchIndex(name="Search")
    search.set_parameter_value("search_options_csv", "")
    ingest = _load_node_module("twelvelabs_ingest_videos").TwelveLabsIngestVideos(name="Ingest")

    assert [str(p) for p in _problems(index_asset)] == [
        "'Index ID' is required. Enter the ID of the TwelveLabs index.",
        "'Asset ID' is required. Enter the ID of an uploaded asset, such as the Asset ID output of Upload Asset.",
    ]
    assert [str(p) for p in _problems(search)] == [
        "'Index ID' is required. Enter the ID of the TwelveLabs index to search.",
        "'Query' is required. Enter the text to search for.",
        "'Search Options (CSV)' is required. Enter at least one option, such as visual,conversation.",
    ]
    assert [str(p) for p in _problems(ingest)] == ["No videos to ingest. Connect at least one video to 'Videos'."]


def test_ingest_run_failure_raises_the_node_error_when_failed_is_unwired(api_key: None, cloud: Any) -> None:
    cloud(lambda _request: _json(401, TOKEN_REJECTED_BODY))
    node = _load_node_module("twelvelabs_ingest_videos").TwelveLabsIngestVideos(name="Ingest")
    node._has_outgoing_connections = lambda _param: False

    with pytest.raises(NodeError) as raised:
        _run(node)

    assert raised.value.fields["status_code"] == 401
    assert [link.label for link in raised.value.links] == ["Update the API key"]


def test_ingest_run_failure_follows_failed_when_wired(api_key: None, cloud: Any) -> None:
    cloud(lambda _request: _json(400, {"detail": "Bad index name."}))
    node = _load_node_module("twelvelabs_ingest_videos").TwelveLabsIngestVideos(name="Ingest")
    node._has_outgoing_connections = lambda _param: True

    _run(node)

    assert node._execution_succeeded is False
    assert node.parameter_output_values["video_ids"] == []
    assert json.dumps(node.parameter_output_values["provider_response"]) == "{}"
