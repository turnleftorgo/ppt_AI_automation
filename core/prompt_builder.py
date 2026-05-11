"""
Jinja2-based prompt builder for LLM tasks.

Substitutes {{variable}} placeholders in prompt templates with
actual user input values.
"""
from jinja2 import Template, UndefinedError


def build_prompt(prompt_template: str, user_inputs: dict) -> str:
    """
    Render a Jinja2 template string with user input values.

    Args:
        prompt_template: The raw prompt from YAML (contains {{var}} placeholders)
        user_inputs: Dict of user_input_id -> value

    Returns:
        Rendered prompt string
    """
    # Use undefined defaults to handle missing vars gracefully
    template = Template(prompt_template)
    try:
        return template.render(**user_inputs)
    except UndefinedError:
        # Fill missing variables with placeholder text
        safe_inputs = dict(user_inputs)
        # Extract all variable names from the template source
        import re
        for var in re.findall(r"\{\{(\w+)\}\}", prompt_template):
            if var not in safe_inputs:
                safe_inputs[var] = "[未提供]"
        return Template(prompt_template).render(**safe_inputs)
