from __future__ import annotations

from typing import Any, ClassVar

from griptape_nodes.exe_types.core_types import ParameterMode
from griptape_nodes.exe_types.param_components.artifact_url.public_artifact_url_parameter import (
    PublicArtifactUrlParameter,
)
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.exe_types.param_types.parameter_video import ParameterVideo
try:
    from .griptape_proxy_node import GriptapeProxyNode
except ImportError:
    from griptape_proxy_node import GriptapeProxyNode

__all__ = ["TwelveLabsUploadAsset"]


class TwelveLabsUploadAsset(GriptapeProxyNode):
    """Upload a video to a TwelveLabs index and return the asset ID."""

    MODEL_ID: ClassVar[str] = "twelvelabs-assets-upload"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "API Nodes"
        self.description = "Upload a video to TwelveLabs via Griptape model proxy"

        self.add_parameter(
            ParameterString(
                name="index_id",
                tooltip="Target TwelveLabs index ID",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="e.g., 698ce217f85333c701f7b043",
                ui_options={"display_name": "Index ID"},
            )
        )

        self._public_video_url_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=ParameterVideo(
                name="video",
                tooltip="Video to upload to TwelveLabs",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Video"},
            ),
            disclaimer_message="The TwelveLabs service utilizes this URL to access the video for upload.",
        )
        self._public_video_url_parameter.add_input_parameters()

        self.add_parameter(
            ParameterString(
                name="filename",
                tooltip="Optional filename override",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="optional-filename.mp4",
                ui_options={"display_name": "Filename (Optional)"},
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
                name="asset_id",
                tooltip="Uploaded TwelveLabs asset ID",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about the asset upload result or any errors",
            result_details_placeholder="Asset upload status will appear here.",
            parameter_group_initially_collapsed=True,
        )

    async def aprocess(self) -> None:
        try:
            await super().aprocess()
        finally:
            self._public_video_url_parameter.delete_uploaded_artifact()

    def _get_api_model_id(self) -> str:
        return self.MODEL_ID

    def validate_before_node_run(self) -> list[Exception] | None:
        exceptions = super().validate_before_node_run() or []

        index_id = (self.get_parameter_value("index_id") or "").strip()
        if not index_id:
            exceptions.append(ValueError(f"{self.name}: index_id is required."))

        video = self.get_parameter_value("video")
        if not video:
            exceptions.append(ValueError(f"{self.name}: video is required."))

        return exceptions if exceptions else None

    async def _build_payload(self) -> dict[str, Any]:
        index_id = (self.get_parameter_value("index_id") or "").strip()
        filename = (self.get_parameter_value("filename") or "").strip()
        video = self.get_parameter_value("video")

        if not index_id:
            msg = "index_id is required"
            raise ValueError(msg)
        if not video:
            msg = "video is required"
            raise ValueError(msg)

        public_video_url = self._public_video_url_parameter.get_public_url_for_parameter()
        if not public_video_url:
            msg = "video is required"
            raise ValueError(msg)

        payload: dict[str, Any] = {
            "index_id": index_id,
            "url": public_video_url,
        }
        if filename:
            payload["filename"] = filename
        return payload

    async def _parse_result(self, result_json: dict[str, Any], _generation_id: str) -> None:
        asset_id = result_json.get("_id")

        if not isinstance(asset_id, str) or not asset_id:
            assets = result_json.get("assets")
            if isinstance(assets, list) and assets:
                first_asset = assets[0]
                if isinstance(first_asset, dict):
                    candidate = first_asset.get("_id")
                    if isinstance(candidate, str) and candidate:
                        asset_id = candidate

        if not isinstance(asset_id, str) or not asset_id:
            self._set_safe_defaults()
            self._set_status_results(
                was_successful=False,
                result_details=f"{self.name} completed but response did not include an asset ID.",
            )
            return

        self.parameter_output_values["asset_id"] = asset_id
        self._set_status_results(
            was_successful=True,
            result_details=f"Asset uploaded successfully: {asset_id}",
        )

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["asset_id"] = ""
