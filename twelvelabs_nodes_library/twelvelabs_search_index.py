from __future__ import annotations

from typing import Any, ClassVar

from griptape_nodes.exe_types.core_types import ParameterMode
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_int import ParameterInt
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
try:
    from .griptape_proxy_node import GriptapeProxyNode
except ImportError:
    from griptape_proxy_node import GriptapeProxyNode

__all__ = ["TwelveLabsSearchIndex"]


class TwelveLabsSearchIndex(GriptapeProxyNode):
    """Search indexed TwelveLabs videos using a text query."""

    MODEL_ID: ClassVar[str] = "twelvelabs-search"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "API Nodes"
        self.description = "Search indexed videos in TwelveLabs via Griptape model proxy"

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
                name="query_text",
                tooltip="Search query text",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                multiline=True,
                placeholder_text="Describe what to search for...",
                ui_options={"display_name": "Query"},
            )
        )

        self.add_parameter(
            ParameterString(
                name="search_options_csv",
                default_value="visual,conversation",
                tooltip="Comma-separated search options",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                placeholder_text="visual,conversation",
                ui_options={"display_name": "Search Options (CSV)"},
            )
        )

        self.add_parameter(
            ParameterInt(
                name="page_limit",
                default_value=10,
                min_val=1,
                max_val=100,
                slider=True,
                tooltip="Maximum number of results to return",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Page Limit"},
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
                name="search_results",
                tooltip="Search response payload",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self.add_parameter(
            ParameterInt(
                name="result_count",
                tooltip="Number of result items found in the top-level data field",
                allowed_modes={ParameterMode.OUTPUT},
                hide_property=True,
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about the search result or any errors",
            result_details_placeholder="Search status will appear here.",
            parameter_group_initially_collapsed=True,
        )

    def _get_api_model_id(self) -> str:
        return self.MODEL_ID

    def validate_before_node_run(self) -> list[Exception] | None:
        exceptions = super().validate_before_node_run() or []

        index_id = (self.get_parameter_value("index_id") or "").strip()
        if not index_id:
            exceptions.append(ValueError(f"{self.name}: index_id is required."))

        query_text = (self.get_parameter_value("query_text") or "").strip()
        if not query_text:
            exceptions.append(ValueError(f"{self.name}: query_text is required."))

        search_options_csv = (self.get_parameter_value("search_options_csv") or "").strip()
        if not search_options_csv:
            exceptions.append(ValueError(f"{self.name}: search_options_csv is required."))

        return exceptions if exceptions else None

    async def _build_payload(self) -> dict[str, Any]:
        index_id = (self.get_parameter_value("index_id") or "").strip()
        query_text = (self.get_parameter_value("query_text") or "").strip()
        search_options_csv = (self.get_parameter_value("search_options_csv") or "").strip()
        page_limit = int(self.get_parameter_value("page_limit") or 10)

        if not index_id:
            msg = "index_id is required"
            raise ValueError(msg)
        if not query_text:
            msg = "query_text is required"
            raise ValueError(msg)

        search_options = [part.strip() for part in search_options_csv.split(",") if part.strip()]
        if not search_options:
            msg = "search_options_csv must include at least one option"
            raise ValueError(msg)

        return {
            "index_id": index_id,
            "search_options": search_options,
            "query_text": query_text,
            "page_limit": page_limit,
        }

    async def _parse_result(self, result_json: dict[str, Any], _generation_id: str) -> None:
        self.parameter_output_values["search_results"] = result_json

        data = result_json.get("data")
        result_count = len(data) if isinstance(data, list) else 0
        self.parameter_output_values["result_count"] = result_count

        self._set_status_results(
            was_successful=True,
            result_details=f"Search completed successfully with {result_count} result(s).",
        )

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["search_results"] = {}
        self.parameter_output_values["result_count"] = 0
