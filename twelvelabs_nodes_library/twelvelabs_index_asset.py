from __future__ import annotations

from typing import Any, ClassVar

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
try:
    from .griptape_proxy_node import GriptapeProxyNode
except ImportError:
    from griptape_proxy_node import GriptapeProxyNode

__all__ = ["TwelveLabsIndexAsset"]


class TwelveLabsIndexAsset(GriptapeProxyNode):
    """Index a previously uploaded TwelveLabs asset and return the indexed video ID."""

    MODEL_ID: ClassVar[str] = "twelvelabs-assets-index"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "API Nodes"
        self.description = "Index a TwelveLabs uploaded asset via Griptape model proxy"

        self.add_parameter(
            ParameterString(
                name="index_id",
                tooltip="Target TwelveLabs index ID",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="e.g., 698ce217f85333c701f7b043",
                ui_options={"display_name": "Index ID"},
            )
        )

        self.add_parameter(
            ParameterString(
                name="asset_id",
                tooltip="Uploaded asset ID to index",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="e.g., 698d11b5fe66d07ab85b0047",
                ui_options={"display_name": "Asset ID"},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="enable_video_stream",
                default_value=False,
                tooltip="Enable video stream for indexed asset",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            ParameterString(
                name="generation_id",
                tooltip="Generation ID from the API",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
                hide=True,
            )
        )

        self.add_parameter(
            ParameterDict(
                name="provider_response",
                tooltip="Verbatim response from Griptape model proxy",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self.add_parameter(
            ParameterString(
                name="video_id",
                tooltip="Indexed TwelveLabs video ID",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self.add_parameter(
            Parameter(
                name="video_ids",
                type="list",
                output_type="list",
                tooltip="Indexed video IDs (for compatibility with batch responses)",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about the asset indexing result or any errors",
            result_details_placeholder="Asset indexing status will appear here.",
            parameter_group_initially_collapsed=True,
        )

    def _get_api_model_id(self) -> str:
        return self.MODEL_ID

    def validate_before_node_run(self) -> list[Exception] | None:
        exceptions = super().validate_before_node_run() or []

        index_id = (self.get_parameter_value("index_id") or "").strip()
        if not index_id:
            exceptions.append(ValueError(f"{self.name}: index_id is required."))

        asset_id = (self.get_parameter_value("asset_id") or "").strip()
        if not asset_id:
            exceptions.append(ValueError(f"{self.name}: asset_id is required."))

        return exceptions if exceptions else None

    async def _build_payload(self) -> dict[str, Any]:
        index_id = (self.get_parameter_value("index_id") or "").strip()
        asset_id = (self.get_parameter_value("asset_id") or "").strip()
        enable_video_stream = bool(self.get_parameter_value("enable_video_stream"))

        if not index_id:
            msg = "index_id is required"
            raise ValueError(msg)
        if not asset_id:
            msg = "asset_id is required"
            raise ValueError(msg)

        return {
            "index_id": index_id,
            "asset_id": asset_id,
            "enable_video_stream": enable_video_stream,
        }

    async def _parse_result(self, result_json: dict[str, Any], _generation_id: str) -> None:
        video_ids: list[str] = []

        single_video_id = result_json.get("_id")
        if isinstance(single_video_id, str) and single_video_id:
            video_ids.append(single_video_id)

        batch_video_ids = result_json.get("indexed_asset_ids")
        if isinstance(batch_video_ids, list):
            for value in batch_video_ids:
                if isinstance(value, str) and value:
                    video_ids.append(value)

        if not video_ids:
            self._set_safe_defaults()
            self._set_status_results(
                was_successful=False,
                result_details=f"{self.name} completed but response did not include a video ID.",
            )
            return

        self.parameter_output_values["video_id"] = video_ids[0]
        self.parameter_output_values["video_ids"] = video_ids
        self._set_status_results(
            was_successful=True,
            result_details=f"Asset indexed successfully: {video_ids[0]}",
        )

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["video_id"] = ""
        self.parameter_output_values["video_ids"] = []
