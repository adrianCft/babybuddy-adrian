from django import template
from django.urls import reverse

from core.navigation import contextual_url

register = template.Library()


@register.simple_tag(takes_context=True)
def context_url(context, target, *args, **kwargs):
    request = context.get("request")
    if request is None:
        return reverse(target, args=args, kwargs=kwargs)
    return contextual_url(request, target, *args, **kwargs)
