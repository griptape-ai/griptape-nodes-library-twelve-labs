from __future__ import annotations

import time
import uuid
from typing import Any, ClassVar

from griptape_nodes.exe_types.core_types import ParameterMode
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
try:
    from .griptape_proxy_node import GriptapeProxyNode
except ImportError:
    from griptape_proxy_node import GriptapeProxyNode

__all__ = ["TwelveLabsCreateIndex"]


class TwelveLabsCreateIndex(GriptapeProxyNode):
    """Create a TwelveLabs index and return the index ID."""

    MODEL_ID: ClassVar[str] = "twelvelabs-indexes-create"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "API Nodes"
        self.description = (
            "Create a TwelveLabs index via Griptape model proxy. "
            "Model configuration is fixed after index creation."
        )

        # Available model families in TwelveLabs v1.3 create-index API.
        self.add_parameter(
            ParameterBool(
                name="use_marengo_3_0",
                default_value=True,
                tooltip=(
                    "Embedding model for search and classification tasks. "
                    "Enable this for stronger semantic retrieval and broader video understanding."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Marengo 3.0"},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="use_marengo_2_7",
                default_value=False,
                tooltip=(
                    "Embedding model focused on multimodal search. "
                    "Enable if you need compatibility with marengo2.7 behavior."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Marengo 2.7"},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="use_pegasus_1_2",
                default_value=True,
                tooltip=(
                    "Generative model that analyzes multiple modalities and returns contextual text. "
                    "Enable this for richer descriptive/generative outputs."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Use Pegasus 1.2"},
            )
        )

        # Available model options/modalities in TwelveLabs v1.3.
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
                name="index_id",
                tooltip="Created TwelveLabs index ID",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about the index creation result or any errors",
            result_details_placeholder="Index creation status will appear here.",
            parameter_group_initially_collapsed=True,
        )

    def _get_api_model_id(self) -> str:
        return self.MODEL_ID

    def validate_before_node_run(self) -> list[Exception] | None:
        exceptions = super().validate_before_node_run() or []

        selected_models = [
            bool(self.get_parameter_value("use_marengo_3_0")),
            bool(self.get_parameter_value("use_marengo_2_7")),
            bool(self.get_parameter_value("use_pegasus_1_2")),
        ]
        if not any(selected_models):
            exceptions.append(ValueError(f"{self.name}: At least one model must be enabled."))

        selected_options = [
            bool(self.get_parameter_value("visual")),
            bool(self.get_parameter_value("audio")),
        ]
        if not any(selected_options):
            exceptions.append(ValueError(f"{self.name}: At least one model option must be enabled."))

        addons_csv = (self.get_parameter_value("addons_csv") or "").strip()
        marengo_enabled = bool(self.get_parameter_value("use_marengo_3_0")) or bool(
            self.get_parameter_value("use_marengo_2_7")
        )
        if addons_csv and not marengo_enabled:
            exceptions.append(ValueError(f"{self.name}: addons require a Marengo model to be enabled."))

        return exceptions if exceptions else None

    async def _build_payload(self) -> dict[str, Any]:
        model_options: list[str] = []
        if bool(self.get_parameter_value("visual")):
            model_options.append("visual")
        if bool(self.get_parameter_value("audio")):
            model_options.append("audio")

        if not model_options:
            msg = "At least one model option must be enabled."
            raise ValueError(msg)

        models: list[dict[str, Any]] = []
        if bool(self.get_parameter_value("use_marengo_3_0")):
            models.append({"name": "marengo3.0", "options": model_options})
        if bool(self.get_parameter_value("use_marengo_2_7")):
            models.append({"name": "marengo2.7", "options": model_options})
        if bool(self.get_parameter_value("use_pegasus_1_2")):
            models.append({"name": "pegasus1.2", "options": model_options})

        if not models:
            msg = "At least one model must be enabled."
            raise ValueError(msg)

        # Keep index names unique to avoid collisions while avoiding exposing this field in the node API.
        index_name = f"gt-index-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

        payload: dict[str, Any] = {
            "index_name": index_name,
            "models": models,
        }

        addons_csv = (self.get_parameter_value("addons_csv") or "").strip()
        if addons_csv:
            addons = [part.strip() for part in addons_csv.split(",") if part.strip()]
            if addons:
                marengo_enabled = any(m["name"].startswith("marengo") for m in models)
                if not marengo_enabled:
                    msg = "addons require at least one Marengo model"
                    raise ValueError(msg)
                payload["addons"] = addons

        return payload

    async def _parse_result(self, result_json: dict[str, Any], _generation_id: str) -> None:
        index_id = result_json.get("_id")
        if not isinstance(index_id, str) or not index_id:
            self._set_safe_defaults()
            self._set_status_results(
                was_successful=False,
                result_details=f"{self.name} completed but response did not include an index ID.",
            )
            return

        self.parameter_output_values["index_id"] = index_id
        self._set_status_results(
            was_successful=True,
            result_details=f"Index created successfully: {index_id}",
        )

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["index_id"] = ""
