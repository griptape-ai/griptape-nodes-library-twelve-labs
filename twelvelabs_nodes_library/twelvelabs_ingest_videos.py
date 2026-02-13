from __future__ import annotations

import time
import uuid
from contextlib import suppress
from typing import Any

from griptape.artifacts.url_artifact import UrlArtifact
from griptape_nodes.exe_types.core_types import Parameter, ParameterList, ParameterMode
from griptape_nodes.exe_types.param_components.artifact_url.public_artifact_url_parameter import (
    PublicArtifactUrlParameter,
)
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.exe_types.param_types.parameter_video import ParameterVideo
from griptape_nodes.traits.options import Options

try:
    from .griptape_proxy_node import GriptapeProxyNode
except ImportError:
    from griptape_proxy_node import GriptapeProxyNode

__all__ = ["TwelveLabsIngestVideos"]


class TwelveLabsIngestVideos(GriptapeProxyNode):
    """Create an index, upload N videos, and index those uploaded assets."""

    CREATE_INDEX_MODEL_ID = "twelvelabs-indexes-create"
    UPLOAD_ASSET_MODEL_ID = "twelvelabs-assets-upload"
    INDEX_ASSET_MODEL_ID = "twelvelabs-assets-index"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "API Nodes"
        self.description = (
            "Create a TwelveLabs index, upload one or more videos, then index each uploaded asset. "
            "Model configuration is fixed after index creation."
        )

        self.add_parameter(
            Parameter(
                name="marengo_model_name",
                type="str",
                default_value="marengo3.0",
                tooltip=(
                    "Marengo embedding model family for search/classification. "
                    "Choose one version, or leave empty to disable Marengo for this index."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["", "marengo3.0", "marengo2.7"])},
                ui_options={"display_name": "Marengo Model"},
            )
        )

        self.add_parameter(
            Parameter(
                name="pegasus_model_name",
                type="str",
                default_value="pegasus1.2",
                tooltip=(
                    "Pegasus generative model family for contextual text output. "
                    "Choose one version, or leave empty to disable Pegasus for this index."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["", "pegasus1.2"])},
                ui_options={"display_name": "Pegasus Model"},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="visual",
                default_value=True,
                tooltip=(
                    "Include visual frames in model analysis. "
                    "Disable to ignore image content and analyze audio only."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="audio",
                default_value=True,
                tooltip=(
                    "Include audio track signals in model analysis. "
                    "Disable to analyze visual content only."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            ParameterString(
                name="addons_csv",
                tooltip=(
                    "Optional comma-separated addons (for instance: thumbnail). "
                    "Addons require at least one enabled Marengo model."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="thumbnail",
                ui_options={"display_name": "Addons (CSV)"},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="enable_video_stream",
                default_value=False,
                tooltip="Enable video stream for indexed assets",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            ParameterList(
                name="videos",
                tooltip=(
                    "One or more videos to ingest. Accepts Video artifacts and URL/path inputs. "
                    "Each item is uploaded, then indexed in sequence."
                ),
                input_types=["VideoUrlArtifact", "list[VideoUrlArtifact]", "str", "list[str]", "any"],
                default_value=[],
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Videos"},
            )
        )
        video_upload_helper = ParameterVideo(
            name="video_upload_helper",
            tooltip="Internal helper parameter for public URL staging",
            allowed_modes={ParameterMode.PROPERTY},
            allow_input=False,
            allow_output=False,
            hide=True,
            hide_property=True,
        )
        self.add_parameter(video_upload_helper)
        self._public_video_url_parameter = PublicArtifactUrlParameter(
            node=self,
            artifact_url_parameter=video_upload_helper,
            disclaimer_message="The TwelveLabs service utilizes this URL to access the video for upload.",
            request_timeout=600.0,
        )

        self.add_parameter(
            ParameterString(
                name="index_id",
                tooltip="Created TwelveLabs index ID",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self.asset_ids_list = ParameterList(
            name="asset_ids",
            tooltip="Uploaded TwelveLabs asset IDs (one output per uploaded video)",
            type="str",
            output_type="str",
            default_value=[],
            allowed_modes={ParameterMode.OUTPUT},
            child_prefix="Asset ID",
        )
        self.add_parameter(self.asset_ids_list)

        self.video_ids_list = ParameterList(
            name="video_ids",
            tooltip="Indexed TwelveLabs video IDs (one output per indexed asset)",
            type="str",
            output_type="str",
            default_value=[],
            allowed_modes={ParameterMode.OUTPUT},
            child_prefix="Video ID",
        )
        self.add_parameter(self.video_ids_list)

        self.add_parameter(
            ParameterDict(
                name="provider_response",
                tooltip="Aggregate response objects from create/upload/index operations",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about ingest orchestration success or failure",
            result_details_placeholder="Ingest status will appear here.",
            parameter_group_initially_collapsed=True,
        )

    def _get_api_model_id(self) -> str:
        # Unused by this orchestration node. Kept to satisfy base class contract.
        return self.CREATE_INDEX_MODEL_ID

    async def _build_payload(self) -> dict[str, Any]:
        # Unused by this orchestration node. Kept to satisfy base class contract.
        return {}

    async def _parse_result(self, result_json: dict[str, Any], generation_id: str) -> None:
        # Unused by this orchestration node. Kept to satisfy base class contract.
        _ = (result_json, generation_id)

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["index_id"] = ""
        self.parameter_output_values["asset_ids"] = []
        self.parameter_output_values["video_ids"] = []
        self.parameter_output_values["provider_response"] = {}
        self.asset_ids_list.clear_list()
        self.video_ids_list.clear_list()

    def validate_before_node_run(self) -> list[Exception] | None:
        exceptions = super().validate_before_node_run() or []

        marengo_model_name = (self.get_parameter_value("marengo_model_name") or "").strip()
        pegasus_model_name = (self.get_parameter_value("pegasus_model_name") or "").strip()
        if not any([marengo_model_name, pegasus_model_name]):
            exceptions.append(ValueError(f"{self.name}: At least one model must be enabled."))

        selected_options = [
            bool(self.get_parameter_value("visual")),
            bool(self.get_parameter_value("audio")),
        ]
        if not any(selected_options):
            exceptions.append(ValueError(f"{self.name}: At least one model option must be enabled."))

        addons_csv = (self.get_parameter_value("addons_csv") or "").strip()
        if addons_csv and not marengo_model_name:
            exceptions.append(ValueError(f"{self.name}: addons require a Marengo model to be enabled."))

        videos = self.get_parameter_list_value("videos")
        if len(videos) == 0:
            exceptions.append(ValueError(f"{self.name}: At least one video is required."))

        return exceptions if exceptions else None

    async def aprocess(self) -> None:
        self._clear_execution_status()
        self._set_safe_defaults()

        try:
            api_key = self._validate_api_key()
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

            create_payload = self._build_create_index_payload()
            create_result = await self._run_proxy_operation(
                api_model_id=self.CREATE_INDEX_MODEL_ID,
                payload=create_payload,
                headers=headers,
                step_label="create index",
            )
            index_id = self._extract_index_id(create_result)
            self.parameter_output_values["index_id"] = index_id

            videos = self.get_parameter_list_value("videos")
            asset_ids: list[str] = []
            upload_results: list[dict[str, Any]] = []
            for idx, video_input in enumerate(videos, start=1):
                upload_url = self._resolve_video_input_to_public_url(video_input)
                upload_result = await self._run_proxy_operation(
                    api_model_id=self.UPLOAD_ASSET_MODEL_ID,
                    payload={"index_id": index_id, "url": upload_url},
                    headers=headers,
                    step_label=f"upload asset {idx}/{len(videos)}",
                )
                asset_id = self._extract_asset_id(upload_result)
                asset_ids.append(asset_id)
                upload_results.append(upload_result)
                self._cleanup_current_staged_artifact()

            video_ids: list[str] = []
            index_results: list[dict[str, Any]] = []
            enable_video_stream = bool(self.get_parameter_value("enable_video_stream"))
            for idx, asset_id in enumerate(asset_ids, start=1):
                index_result = await self._run_proxy_operation(
                    api_model_id=self.INDEX_ASSET_MODEL_ID,
                    payload={
                        "index_id": index_id,
                        "asset_id": asset_id,
                        "enable_video_stream": enable_video_stream,
                    },
                    headers=headers,
                    step_label=f"index asset {idx}/{len(asset_ids)}",
                )
                video_id = self._extract_video_id(index_result)
                video_ids.append(video_id)
                index_results.append(index_result)

            self._set_asset_ids_outputs(asset_ids)
            self._set_video_ids_outputs(video_ids)
            self.parameter_output_values["provider_response"] = {
                "create_index": create_result,
                "uploads": upload_results,
                "indexes": index_results,
            }
            self._set_status_results(
                was_successful=True,
                result_details=(
                    f"Created index {index_id}, uploaded {len(asset_ids)} asset(s), "
                    f"and indexed {len(video_ids)} video(s) successfully."
                ),
            )
        except Exception as e:
            self._set_safe_defaults()
            self._set_status_results(was_successful=False, result_details=str(e))
            self._handle_failure_exception(e)
        finally:
            self._cleanup_current_staged_artifact()

    def _build_create_index_payload(self) -> dict[str, Any]:
        model_options: list[str] = []
        if bool(self.get_parameter_value("visual")):
            model_options.append("visual")
        if bool(self.get_parameter_value("audio")):
            model_options.append("audio")
        if not model_options:
            msg = "At least one model option must be enabled."
            raise ValueError(msg)

        marengo_model_name = (self.get_parameter_value("marengo_model_name") or "").strip()
        pegasus_model_name = (self.get_parameter_value("pegasus_model_name") or "").strip()

        models: list[dict[str, Any]] = []
        if marengo_model_name:
            models.append({"model_name": marengo_model_name, "model_options": model_options})
        if pegasus_model_name:
            models.append({"model_name": pegasus_model_name, "model_options": model_options})
        if len(models) == 0:
            msg = "At least one model must be enabled."
            raise ValueError(msg)

        payload: dict[str, Any] = {
            "index_name": f"gt-index-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            "models": models,
        }

        addons_csv = (self.get_parameter_value("addons_csv") or "").strip()
        if addons_csv:
            addons = [part.strip() for part in addons_csv.split(",") if part.strip()]
            if addons:
                if not marengo_model_name:
                    msg = "addons require at least one Marengo model"
                    raise ValueError(msg)
                payload["addons"] = addons
        return payload

    async def _run_proxy_operation(
        self, *, api_model_id: str, payload: dict[str, Any], headers: dict[str, str], step_label: str
    ) -> dict[str, Any]:
        generation_id = await self._submit_generation(payload, headers, api_model_id)
        if not generation_id:
            msg = f"{self.name}: Failed to {step_label}: no generation_id returned."
            raise RuntimeError(msg)

        status_response = await self._poll_generation_status(generation_id, headers)
        if not status_response:
            msg = f"{self.name}: Failed to {step_label}: generation status did not complete."
            raise RuntimeError(msg)

        result = await self._fetch_generation_result(generation_id)
        if not result or not isinstance(result, dict):
            msg = f"{self.name}: Failed to {step_label}: missing or invalid result payload."
            raise RuntimeError(msg)
        return result

    def _extract_index_id(self, result_json: dict[str, Any]) -> str:
        index_id = result_json.get("_id")
        if isinstance(index_id, str) and index_id:
            return index_id
        msg = f"{self.name}: create index completed but response did not include an index ID."
        raise RuntimeError(msg)

    def _extract_asset_id(self, result_json: dict[str, Any]) -> str:
        asset_id = result_json.get("_id")
        if isinstance(asset_id, str) and asset_id:
            return asset_id

        assets = result_json.get("assets")
        if isinstance(assets, list) and assets:
            first_asset = assets[0]
            if isinstance(first_asset, dict):
                candidate = first_asset.get("_id")
                if isinstance(candidate, str) and candidate:
                    return candidate

        msg = f"{self.name}: upload asset completed but response did not include an asset ID."
        raise RuntimeError(msg)

    def _extract_video_id(self, result_json: dict[str, Any]) -> str:
        video_id = result_json.get("_id")
        if isinstance(video_id, str) and video_id:
            return video_id

        indexed_asset_ids = result_json.get("indexed_asset_ids")
        if isinstance(indexed_asset_ids, list):
            for value in indexed_asset_ids:
                if isinstance(value, str) and value:
                    return value

        msg = f"{self.name}: index asset completed but response did not include a video ID."
        raise RuntimeError(msg)

    def _resolve_video_input_to_public_url(self, video_input: Any) -> str:
        url_value = video_input.value if isinstance(video_input, UrlArtifact) else video_input
        if isinstance(url_value, str):
            url_value = url_value.strip()
        if not url_value:
            msg = f"{self.name}: video input must resolve to a non-empty URL or path."
            raise ValueError(msg)

        if isinstance(url_value, str) and url_value.startswith(("http://", "https://")) and "localhost" not in url_value:
            return url_value

        self.set_parameter_value("video_upload_helper", url_value)
        public_url = self._public_video_url_parameter.get_public_url_for_parameter()
        if not public_url:
            msg = f"{self.name}: failed to convert video input to public URL."
            raise ValueError(msg)
        return public_url

    def _cleanup_current_staged_artifact(self) -> None:
        with suppress(Exception):
            self._public_video_url_parameter.delete_uploaded_artifact()
        # PublicArtifactUrlParameter doesn't clear its internal pointer after delete.
        # Clear it here so repeated cleanup calls are no-ops instead of 404 deletes.
        with suppress(Exception):
            self._public_video_url_parameter.gtc_file_path = None

    def _set_asset_ids_outputs(self, asset_ids: list[str]) -> None:
        self.asset_ids_list.clear_list()
        for asset_id in asset_ids:
            child = self.asset_ids_list.add_child_parameter()
            self.set_parameter_value(child.name, asset_id)
            self.publish_update_to_parameter(child.name, asset_id)
            self.parameter_output_values[child.name] = asset_id
        self.parameter_output_values["asset_ids"] = asset_ids

    def _set_video_ids_outputs(self, video_ids: list[str]) -> None:
        self.video_ids_list.clear_list()
        for video_id in video_ids:
            child = self.video_ids_list.add_child_parameter()
            self.set_parameter_value(child.name, video_id)
            self.publish_update_to_parameter(child.name, video_id)
            self.parameter_output_values[child.name] = video_id
        self.parameter_output_values["video_ids"] = video_ids
