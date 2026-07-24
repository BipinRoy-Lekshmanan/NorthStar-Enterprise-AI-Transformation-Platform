"""Generic, `input_schema`-driven workflow form renderer (Milestone 7).

One function renders a usable form for any of the 5 catalog workflows
from its `input_schema` (`{field_name: {type, required, enum_values?}}`,
already returned as-is by `GET /workflows/{workflow_id}`) -- rather than
hand-building 5 separate forms. Only 3 field types exist across the
real catalog today (`string`, `list`, `enum`); an unrecognized type
falls back to a plain text input rather than raising, so a future
workflow with a new field type still gets a usable (if unstyled) field.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_workflow_form(workflow_id: str, input_schema: dict[str, Any], prefill: dict[str, Any] | None = None) -> dict | None:
    """Renders the form; returns the collected `inputs` dict only on the
    submit click, `None` otherwise (Streamlit reruns the whole script on
    every interaction, so the caller checks for `None`)."""
    prefill = prefill or {}

    with st.form(key=f"workflow_form_{workflow_id}"):
        values: dict[str, Any] = {}
        for field_name, spec in input_schema.items():
            field_type = spec.get("type", "string")
            required = spec.get("required", False)
            label = f"{field_name} {'*' if required else '(optional)'}"
            widget_key = f"wf_{workflow_id}_{field_name}"
            default = prefill.get(field_name)

            if field_type == "enum":
                options = spec.get("enum_values", [])
                index = options.index(default) if default in options else 0
                values[field_name] = st.selectbox(label, options, index=index, key=widget_key)
            elif field_type == "list":
                default_text = "\n".join(default) if isinstance(default, list) else ""
                raw = st.text_area(label + " (one per line)", value=default_text, key=widget_key)
                values[field_name] = [line.strip() for line in raw.splitlines() if line.strip()]
            else:
                values[field_name] = st.text_area(label, value=default or "", key=widget_key, height=80)

        submitted = st.form_submit_button("Execute workflow", type="primary")

    if not submitted:
        return None

    missing = [
        field_name for field_name, spec in input_schema.items()
        if spec.get("required") and not values.get(field_name)
    ]
    if missing:
        st.error(f"Missing required field(s): {', '.join(missing)}")
        return None

    return values
