from decimal import Decimal, InvalidOperation
from django import template
from django.conf import settings

register = template.Library()

ACCOUNT_KINDS_META = {
    'bank': {'name': 'Bank Account', 'icon': '🏦'},
    'mpesa': {'name': 'M-Pesa Mobile Money', 'icon': '📱'},
    'cash': {'name': 'Cash Wallet', 'icon': '💵'},
    'sacco': {'name': 'SACCO Account', 'icon': '🤝'},
    'mmf': {'name': 'Money Market Fund (MMF)', 'icon': '📈'},
    'investment': {'name': 'Investment / Stocks', 'icon': '💎'},
    'credit_card': {'name': 'Credit Card', 'icon': '💳'},
    'debtors': {'name': 'Debtors', 'icon': '🧾'},
}


@register.filter
def money(value):
    """Format a numeric value with the configured currency (default KES)."""
    currency = getattr(settings, 'CURRENCY', 'KES')
    try:
        num = Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        num = Decimal('0')
    sign = '-' if num < 0 else ''
    return f"{sign}{currency} {abs(num):,.2f}"


@register.filter
def abs_val(value):
    """Return the absolute numeric value."""
    try:
        return abs(Decimal(str(value or 0)))
    except (InvalidOperation, ValueError, TypeError):
        return 0


@register.filter
def kind_icon(kind):
    """Return emoji icon for an account kind."""
    return ACCOUNT_KINDS_META.get(kind, {}).get('icon', '💰')


@register.filter
def kind_name(kind):
    """Return human-readable label for an account kind."""
    return ACCOUNT_KINDS_META.get(kind, {}).get('name', str(kind))


@register.filter
def get_item(mapping, key):
    """Lookup a key in a dict from a template."""
    if isinstance(mapping, dict):
        return mapping.get(key)
    return None
