from __future__ import annotations

import time
import uuid
from typing import Any, ClassVar

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.traits.options import Options

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
            "Create a TwelveLabs index via Griptape model proxy. Model configuration is fixed after index creation."
        )

        # Select one model per family (or leave a family empty).
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

        # Available model options/modalities in TwelveLabs v1.3.
        self.add_parameter(
            ParameterBool(
                name="visual",
                default_value=True,
                tooltip=(
                    "Include visual frames in model analysis. Disable to ignore image content and analyze audio only."
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )

        self.add_parameter(
            ParameterBool(
                name="audio",
                default_value=True,
                tooltip=("Include audio track signals in model analysis. Disable to analyze visual content only."),
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

        marengo_model_name = (self.get_parameter_value("marengo_model_name") or "").strip()
        pegasus_model_name = (self.get_parameter_value("pegasus_model_name") or "").strip()
        selected_models = [marengo_model_name, pegasus_model_name]
        if not any(selected_models):
            exceptions.append(ValueError(f"{self.name}: At least one model must be enabled."))

        selected_options = [
            bool(self.get_parameter_value("visual")),
            bool(self.get_parameter_value("audio")),
        ]
        if not any(selected_options):
            exceptions.append(ValueError(f"{self.name}: At least one model option must be enabled."))

        addons_csv = (self.get_parameter_value("addons_csv") or "").strip()
        marengo_enabled = bool(marengo_model_name)
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

        marengo_model_name = (self.get_parameter_value("marengo_model_name") or "").strip()
        pegasus_model_name = (self.get_parameter_value("pegasus_model_name") or "").strip()

        models: list[dict[str, Any]] = []
        if marengo_model_name:
            models.append({"model_name": marengo_model_name, "model_options": model_options})
        if pegasus_model_name:
            models.append({"model_name": pegasus_model_name, "model_options": model_options})

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
                marengo_enabled = any(m["model_name"].startswith("marengo") for m in models)
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
