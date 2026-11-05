from __future__ import annotations

from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMessage, ParameterMode
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.traits.button import Button

__all__ = ["add_pegasus_model_parameter", "migrate_deprecated_pegasus_model"]

PEGASUS_MODEL_PARAMETER = "pegasus_model_name"
PEGASUS_DEPRECATION_NOTICE = "pegasus_model_deprecation_notice"

# TwelveLabs no longer indexes with these. No Pegasus model can be indexed, so each migrates to
# Pegasus disabled.
DEPRECATED_PEGASUS_MODELS: frozenset[str] = frozenset({"pegasus1.2"})


def add_pegasus_model_parameter(node: BaseNode) -> None:
    """Add the Pegasus model parameter and the notice shown when a saved value is deprecated.

    The parameter stays so saved workflows that set it still load, but it is hidden and has no
    choices: with every Pegasus model deprecated for indexing, the only option left is Pegasus
    disabled. A choices list would also coerce a saved deprecated value to empty before
    `migrate_deprecated_pegasus_model` could see it and show the notice.
    """
    node.add_parameter(
        Parameter(
            name=PEGASUS_MODEL_PARAMETER,
            type="str",
            default_value="",
            tooltip=(
                "Pegasus generative model family for contextual text output. "
                "TwelveLabs no longer indexes with Pegasus, so leave this empty."
            ),
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            ui_options={"display_name": "Pegasus Model"},
            hide=True,
        )
    )

    node.add_node_element(
        ParameterMessage(
            name=PEGASUS_DEPRECATION_NOTICE,
            title="Model Deprecation Notice",
            variant="info",
            value="",
            traits={
                Button(
                    full_width=True,
                    on_click=lambda _, __: node.hide_message_by_name(PEGASUS_DEPRECATION_NOTICE),
                )
            },
            button_text="Dismiss",
            hide=True,
        )
    )


def migrate_deprecated_pegasus_model(node: BaseNode, parameter: Parameter, value: Any) -> Any:
    """Replace a deprecated Pegasus model with Pegasus disabled and show the deprecation notice."""
    if parameter.name != PEGASUS_MODEL_PARAMETER or value not in DEPRECATED_PEGASUS_MODELS:
        return value

    message = node.get_message_by_name_or_element_id(PEGASUS_DEPRECATION_NOTICE)
    if message is not None:
        message.value = (
            f"TwelveLabs has sunset '{value}' and no longer indexes with it. "
            "Pegasus has been disabled for this node. Indexes use Marengo only, so select a Marengo "
            "model, then save your workflow to apply this change."
        )
        node.show_message_by_name(PEGASUS_DEPRECATION_NOTICE)
    return ""
