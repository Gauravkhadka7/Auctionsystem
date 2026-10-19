from django import template

register = template.Library()


@register.filter
def elided_page_range(page_obj):
    """Elide a Page's page numbers around the current page for compact pagination."""
    return page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
