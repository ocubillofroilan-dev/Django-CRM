from django import template

register = template.Library()


@register.filter
def render_field(bound_field):
    """Render a form field with Bootstrap validation state and ARIA attributes."""
    classes = bound_field.field.widget.attrs.get("class", "")
    attrs = {}
    described_by = []

    if bound_field.errors:
        classes = f"{classes} is-invalid"
        attrs["aria-invalid"] = "true"
        described_by.append(f"{bound_field.auto_id}_error")
    if bound_field.help_text:
        described_by.append(f"{bound_field.auto_id}_help")
    if described_by:
        attrs["aria-describedby"] = " ".join(described_by)

    attrs["class"] = classes.strip()
    return bound_field.as_widget(attrs=attrs)


@register.filter
def avatar_hue(value):
    """Stable colour bucket (0-11) for an avatar, derived from a name."""
    return sum(ord(char) for char in str(value)) % 12