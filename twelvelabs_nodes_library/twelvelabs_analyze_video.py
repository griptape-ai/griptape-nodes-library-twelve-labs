from __future__ import annotations

import json
from typing import Any, ClassVar

from griptape_nodes.exe_types.core_types import ParameterMode
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_float import ParameterFloat
from griptape_nodes.exe_types.param_types.parameter_int import ParameterInt
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
try:
    from .griptape_proxy_node import GriptapeProxyNode
except ImportError:
    from griptape_proxy_node import GriptapeProxyNode

__all__ = ["TwelveLabsAnalyzeVideo"]


class TwelveLabsAnalyzeVideo(GriptapeProxyNode):
    """Run open-ended analysis against an indexed TwelveLabs video."""

    MODEL_ID: ClassVar[str] = "twelvelabs-analyze"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "API Nodes"
        self.description = "Analyze an indexed video in TwelveLabs via Griptape model proxy"

        self.add_parameter(
            ParameterString(
                name="video_id",
                tooltip="Indexed TwelveLabs video ID",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="e.g., 698d1221dc4c5f389959f2a9",
                ui_options={"display_name": "Video ID"},
            )
        )

        self.add_parameter(
            ParameterString(
                name="prompt",
                tooltip="Analysis prompt",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                multiline=True,
                placeholder_text="What is happening in this video?",
                ui_options={"display_name": "Prompt"},
            )
        )

        self.add_parameter(
            ParameterFloat(
                name="temperature",
                default_value=0.2,
                min_val=0.0,
                max_val=1.0,
                slider=True,
                tooltip="Sampling temperature (0 to 1)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Temperature"},
            )
        )

        self.add_parameter(
            ParameterInt(
                name="max_tokens",
                default_value=1024,
                min_val=1,
                max_val=4096,
                slider=True,
                tooltip="Maximum output tokens",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Max Tokens"},
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
            ParameterDict(
                name="analysis_result",
                tooltip="Analysis response payload",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self.add_parameter(
            ParameterString(
                name="analysis_text",
                tooltip="Best-effort extracted analysis text",
                allowed_modes={ParameterMode.OUTPUT},
                multiline=True,
                ui_options={"display_name": "Analysis Text", "multiline": True},
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about the analysis result or any errors",
            result_details_placeholder="Analysis status will appear here.",
            parameter_group_initially_collapsed=True,
        )

    def _get_api_model_id(self) -> str:
        return self.MODEL_ID

    def validate_before_node_run(self) -> list[Exception] | None:
        exceptions = super().validate_before_node_run() or []

        video_id = (self.get_parameter_value("video_id") or "").strip()
        if not video_id:
            exceptions.append(ValueError(f"{self.name}: video_id is required."))

        prompt = (self.get_parameter_value("prompt") or "").strip()
        if not prompt:
            exceptions.append(ValueError(f"{self.name}: prompt is required."))

        return exceptions if exceptions else None

    async def _build_payload(self) -> dict[str, Any]:
        video_id = (self.get_parameter_value("video_id") or "").strip()
        prompt = (self.get_parameter_value("prompt") or "").strip()
        temperature = float(self.get_parameter_value("temperature") or 0.2)
        max_tokens = int(self.get_parameter_value("max_tokens") or 1024)

        if not video_id:
            msg = "video_id is required"
            raise ValueError(msg)
        if not prompt:
            msg = "prompt is required"
            raise ValueError(msg)

        return {
            "video_id": video_id,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _extract_text(self, value: Any) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None

        if isinstance(value, list):
            for item in value:
                extracted = self._extract_text(item)
                if extracted:
                    return extracted
            return None

        if isinstance(value, dict):
            for key in ["text", "analysis", "summary", "result", "output", "content"]:
                if key in value:
                    extracted = self._extract_text(value[key])
                    if extracted:
                        return extracted

            choices = value.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        extracted = self._extract_text(message.get("content"))
                        if extracted:
                            return extracted
                    extracted = self._extract_text(first.get("text"))
                    if extracted:
                        return extracted

            data = value.get("data")
            if data is not None:
                extracted = self._extract_text(data)
                if extracted:
                    return extracted

        return None

    async def _parse_result(self, result_json: dict[str, Any], _generation_id: str) -> None:
        self.parameter_output_values["analysis_result"] = result_json

        analysis_text = self._extract_text(result_json)
        if not analysis_text:
            analysis_text = json.dumps(result_json, indent=2)

        self.parameter_output_values["analysis_text"] = analysis_text
        self._set_status_results(
            was_successful=True,
            result_details="Video analysis completed successfully.",
        )

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["analysis_result"] = {}
        self.parameter_output_values["analysis_text"] = ""
