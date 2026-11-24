import calendar
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import (
    Account, Budget, BudgetCategory, BudgetGroupCategory, BudgetItem,
    Debt, SpentCategory, Transaction, total
)
from .services import (
    compute_account_insights, compute_summary, parse_month,
    reconcile_account_balance, resolve_default_account
)
from .templatetags.budget_extras import ACCOUNT_KINDS_META

NAV_TABS = [
    {'id': 'today', 'url_name': 'today', 'label': "Today's Spends"},
    {'id': 'categories', 'url_name': 'categories', 'label': 'Categories'},
    {'id': 'dashboard', 'url_name': 'dashboard', 'label': 'Dashboard'},
    {'id': 'transactions', 'url_name': 'transactions', 'label': 'Transactions'},
    {'id': 'accounts', 'url_name': 'accounts', 'label': 'Accounts'},
    {'id': 'budget', 'url_name': 'budget', 'label': 'Budget Plan'},
    {'id': 'debts', 'url_name': 'debts', 'label': 'Debts'},
]


def _base_context(active_tab):
    return {
        'nav_tabs': NAV_TABS,
        'active_tab': active_tab,
        'currency': getattr(settings, 'CURRENCY', 'KES'),
    }


def _safe_redirect(request, fallback_name):
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback_name)


def _parse_decimal(raw, field_name='amount', allow_zero=False):
    try:
        val = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'Please enter a valid {field_name}.')
    if allow_zero:
        if val < 0:
            raise ValueError(f'{field_name.capitalize()} cannot be negative.')
    elif val <= 0:
        raise ValueError(f'{field_name.capitalize()} must be greater than zero.')
    return val


def _parse_date(raw, default=None):
    if not raw:
        return default or timezone.localdate()
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return default or timezone.localdate()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect('today')
    error = ''
    username = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            nxt = request.POST.get('next') or request.GET.get('next')
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
                return redirect(nxt)
            return redirect('today')
        error = 'Check your username and password.'
    return render(request, 'budget/login.html', {
        'mode': 'login',
        'error': error,
        'username': username,
        'next': request.GET.get('next', ''),
    })


def register_view(request):
    if request.user.is_authenticated:
        return redirect('today')
    error = ''
    username = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        if not username or not password:
            error = 'Username and password are required.'
        elif User.objects.filter(username=username).exists():
            error = 'That username is already taken.'
        else:
            user = User.objects.create_user(username=username, password=password)
            login(request, user)
            return redirect('today')
    return render(request, 'budget/login.html', {
        'mode': 'register',
        'error': error,
        'username': username,
        'next': '',
    })


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


# ---------------------------------------------------------------------------
# Today's Spends (Landing Page)
# ---------------------------------------------------------------------------

@login_required
def today_view(request):
    today = timezone.localdate()
    all_today_txs = list(
        Transaction.objects.filter(user=request.user, transaction_date=today)
        .select_related('account', 'spent_category__budget_category__grouping')
        .order_by('-id')
    )
    categories = list(
        SpentCategory.objects.filter(user=request.user)
        .select_related('budget_category__grouping')
        .order_by('name')
    )
    active_categories = [c for c in categories if c.is_active]
    active_accounts = list(
        Account.objects.filter(user=request.user, is_archived=False)
        .order_by('-is_default', 'name')
    )
    default_account = next((a for a in active_accounts if a.is_default), active_accounts[0] if active_accounts else None)

    search_query = (request.GET.get('q') or '').strip()
    selected_cat_raw = (request.GET.get('category') or '').strip()
    show_deactivated = request.GET.get('show_deactivated') == '1'

    selected_cat_id = int(selected_cat_raw) if selected_cat_raw.isdigit() else None

    filtered_txs = []
    for tx in all_today_txs:
        if not show_deactivated and not tx.is_active:
            continue
        if selected_cat_id and tx.spent_category_id != selected_cat_id:
            continue
        if search_query:
            q = search_query.lower()
            desc = (tx.description or '').lower()
            cat_name = (tx.spent_category.name if tx.spent_category else '').lower()
            cat_path = (tx.spent_category.full_path if tx.spent_category else '').lower()
            if q not in desc and q not in cat_name and q not in cat_path:
                continue
        filtered_txs.append(tx)

    active_count = sum(1 for tx in all_today_txs if tx.is_active)
    deactivated_count = len(all_today_txs) - active_count
    today_total = sum(
        (tx.amount for tx in all_today_txs if tx.is_active and tx.kind == 'expense'),
        Decimal('0')
    )

    # Map active recorded categories by date so modal JS can mark duplicates cleanly
    active_cat_dates = Transaction.objects.filter(
        user=request.user,
        is_active=True,
        spent_category__isnull=False,
    ).values('id', 'spent_category_id', 'transaction_date')
    recorded_map = {}
    for row in active_cat_dates:
        d_str = row['transaction_date'].isoformat()
        recorded_map.setdefault(d_str, []).append({
            'tx_id': row['id'],
            'cat_id': row['spent_category_id'],
        })

    ctx = {
        **_base_context('today'),
        'today': today,
        'today_iso': today.isoformat(),
        'transactions': filtered_txs,
        'categories': categories,
        'active_categories': active_categories,
        'active_accounts': active_accounts,
        'default_account': default_account,
        'search_query': search_query,
        'selected_cat_id': selected_cat_id,
        'show_deactivated': show_deactivated,
        'stats': {
            'total': len(all_today_txs),
            'active': active_count,
            'deactivated': deactivated_count,
        },
        'today_total': today_total,
        'recorded_map_json': json.dumps(recorded_map),
    }
    return render(request, 'budget/today.html', ctx)


@login_required
@require_POST
def today_save(request):
    tx_id = (request.POST.get('id') or '').strip()
    tx_date = _parse_date(request.POST.get('date'))
    cat_id_raw = (request.POST.get('category') or '').strip()
    acct_id_raw = (request.POST.get('account') or '').strip()
    narrative = (request.POST.get('narrative') or '').strip()
    is_active = request.POST.get('is_active') == 'on'

    try:
        amount = _parse_decimal(request.POST.get('amount'), 'amount')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('today')

    spent_category = None
    if cat_id_raw:
        spent_category = get_object_or_404(SpentCategory, pk=cat_id_raw, user=request.user)

    account = None
    if acct_id_raw:
        account = get_object_or_404(Account, pk=acct_id_raw, user=request.user)
    else:
        account = resolve_default_account(request.user)

    instance = None
    if tx_id:
        instance = get_object_or_404(Transaction, pk=tx_id, user=request.user)
    else:
        is_active = True

    # Enforce one active entry per category and date
    if spent_category and is_active:
        dup_qs = Transaction.objects.filter(
            user=request.user,
            transaction_date=tx_date,
            spent_category=spent_category,
            is_active=True,
        )
        if instance:
            dup_qs = dup_qs.exclude(pk=instance.pk)
        existing = dup_qs.first()
        if existing:
            messages.error(
                request,
                f'An entry for category "{spent_category.name}" on {tx_date} already exists (TX-{existing.id}). '
                'Only one entry per category and date is allowed.'
            )
            return redirect('today')

    if instance:
        instance.transaction_date = tx_date
        instance.spent_category = spent_category
        instance.account = account
        instance.amount = amount
        instance.description = narrative
        instance.is_active = is_active
        instance.save()
        messages.success(request, f'Spend TX-{instance.id} updated.')
    else:
        tx = Transaction.objects.create(
            user=request.user,
            kind='expense',
            account=account,
            spent_category=spent_category,
            amount=amount,
            transaction_date=tx_date,
            description=narrative,
            is_active=True,
        )
        messages.success(request, f'Spend TX-{tx.id} recorded.')

    return redirect('today')


# ---------------------------------------------------------------------------
# Categories (3-tier)
# ---------------------------------------------------------------------------

@login_required
def categories_view(request):
    tab = request.GET.get('tab', 'grouping')
    if tab not in ('grouping', 'budget', 'spent'):
        tab = 'grouping'
    search_query = (request.GET.get('q') or '').strip()
    q = search_query.lower()

    groups = list(BudgetGroupCategory.objects.filter(user=request.user).order_by('priority', 'name'))
    budget_cats = list(
        BudgetCategory.objects.filter(user=request.user)
        .select_related('grouping')
        .order_by('grouping__priority', 'name')
    )
    spent_cats = list(
        SpentCategory.objects.filter(user=request.user)
        .select_related('budget_category__grouping')
        .order_by('name')
    )

    filtered_groups = [g for g in groups if not q or q in g.name.lower()]
    filtered_budget_cats = [
        b for b in budget_cats
        if not q or q in b.name.lower() or q in b.grouping.name.lower()
    ]
    filtered_spent_cats = [
        s for s in spent_cats
        if not q or q in s.name.lower() or q in s.full_path.lower()
    ]

    ctx = {
        **_base_context('categories'),
        'current_tab': tab,
        'search_query': search_query,
        'groups': groups,
        'budget_cats': budget_cats,
        'spent_cats': spent_cats,
        'filtered_groups': filtered_groups,
        'filtered_budget_cats': filtered_budget_cats,
        'filtered_spent_cats': filtered_spent_cats,
    }
    return render(request, 'budget/categories.html', ctx)


@login_required
@require_POST
def categories_save(request):
    tier = request.POST.get('tier', 'grouping')
    item_id = (request.POST.get('id') or '').strip()
    name = (request.POST.get('name') or '').strip()

    if not name:
        messages.error(request, 'Category name is required.')
        return redirect(f"{reverse('categories')}?tab={tier}")

    if tier == 'grouping':
        try:
            priority = int(request.POST.get('priority', 1))
            if not (1 <= priority <= 10):
                raise ValueError
        except ValueError:
            messages.error(request, 'Priority must be between 1 and 10.')
            return redirect(f"{reverse('categories')}?tab=grouping")

        if item_id:
            obj = get_object_or_404(BudgetGroupCategory, pk=item_id, user=request.user)
            obj.name = name
            obj.priority = priority
            obj.save()
            messages.success(request, f'Grouping "{obj.name}" updated.')
        else:
            obj = BudgetGroupCategory.objects.create(user=request.user, name=name, priority=priority)
            messages.success(request, f'Grouping "{obj.name}" created.')

    elif tier == 'budget':
        grouping_id = request.POST.get('grouping')
        if not grouping_id:
            messages.error(request, 'Please select a Budget Grouping Category.')
            return redirect(f"{reverse('categories')}?tab=budget")
        grouping = get_object_or_404(BudgetGroupCategory, pk=grouping_id, user=request.user)
        cat_type = request.POST.get('category_type', 'needs')
        if cat_type not in ('needs', 'wants', 'savings'):
            cat_type = 'needs'
        is_active = request.POST.get('is_active') == 'on'

        if item_id:
            obj = get_object_or_404(BudgetCategory, pk=item_id, user=request.user)
            obj.name = name
            obj.grouping = grouping
            obj.category_type = cat_type
            obj.is_active = is_active
            obj.save()
            messages.success(request, f'Budget category "{obj.name}" updated.')
        else:
            obj = BudgetCategory.objects.create(
                user=request.user,
                name=name,
                grouping=grouping,
                category_type=cat_type,
                is_active=is_active if 'is_active_submitted' in request.POST else True,
            )
            messages.success(request, f'Budget category "{obj.name}" created.')

    else:
        bcat_id = (request.POST.get('budget_category') or '').strip()
        bcat = get_object_or_404(BudgetCategory, pk=bcat_id, user=request.user) if bcat_id else None
        is_savings = request.POST.get('is_savings') == 'on'
        is_active = request.POST.get('is_active') == 'on'

        if item_id:
            obj = get_object_or_404(SpentCategory, pk=item_id, user=request.user)
            obj.name = name
            obj.budget_category = bcat
            obj.is_savings = is_savings
            obj.is_active = is_active
            obj.save()
            messages.success(request, f'Spent category "{obj.name}" updated.')
        else:
            obj = SpentCategory.objects.create(
                user=request.user,
                name=name,
                budget_category=bcat,
                is_savings=is_savings,
                is_active=is_active if 'is_active_submitted' in request.POST else True,
            )
            messages.success(request, f'Spent category "{obj.name}" created.')

    return redirect(f"{reverse('categories')}?tab={tier}")


@login_required
@require_POST
def categories_delete(request, tier, pk):
    model_map = {
        'grouping': BudgetGroupCategory,
        'budget': BudgetCategory,
        'spent': SpentCategory,
    }
    model = model_map.get(tier)
    if not model:
        return redirect('categories')
    obj = get_object_or_404(model, pk=pk, user=request.user)
    obj_name = obj.name
    obj.delete()
    messages.success(request, f'"{obj_name}" deleted.')
    return redirect(f"{reverse('categories')}?tab={tier}")


@login_required
@require_POST
def categories_toggle(request, tier, pk):
    model_map = {
        'budget': BudgetCategory,
        'spent': SpentCategory,
    }
    model = model_map.get(tier)
    if not model:
        return redirect('categories')
    obj = get_object_or_404(model, pk=pk, user=request.user)
    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active'])
    state = 'activated' if obj.is_active else 'deactivated'
    messages.success(request, f'"{obj.name}" {state}.')
    return redirect(f"{reverse('categories')}?tab={tier}")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard_view(request):
    month_param = request.GET.get('month')
    summary_data = compute_summary(request.user, month_param)
    ctx = {
        **_base_context('dashboard'),
        's': summary_data,
    }
    return render(request, 'budget/dashboard.html', ctx)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@login_required
def transactions_view(request):
    today = timezone.localdate()
    y, m, month = parse_month(request.GET.get('month'))

    items = list(
        Transaction.objects.filter(
            user=request.user,
            transaction_date__year=y,
            transaction_date__month=m,
        )
        .select_related('account', 'to_account', 'spent_category__budget_category__grouping')
        .order_by('-transaction_date', '-id')
    )
    all_accounts = list(Account.objects.filter(user=request.user).order_by('-is_default', 'name'))
    active_accounts = [a for a in all_accounts if not a.is_archived]
    default_account = next((a for a in active_accounts if a.is_default), active_accounts[0] if active_accounts else None)
    spent_cats = list(
        SpentCategory.objects.filter(user=request.user, is_active=True)
        .select_related('budget_category__grouping')
        .order_by('name')
    )

    accounts_meta = {
        a.id: {
            'name': a.name,
            'balance': float(a.balance),
            'minimum_balance': float(a.minimum_balance),
        }
        for a in active_accounts
    }

    ctx = {
        **_base_context('transactions'),
        'today_iso': today.isoformat(),
        'month': month,
        'items': items,
        'active_accounts': active_accounts,
        'default_account': default_account,
        'spent_categories': spent_cats,
        'accounts_json': json.dumps(accounts_meta),
    }
    return render(request, 'budget/transactions.html', ctx)


@login_required
@require_POST
def transactions_add(request):
    kind = request.POST.get('kind', 'expense')
    if kind not in ('expense', 'income', 'transfer'):
        kind = 'expense'

    acct_id = request.POST.get('account')
    to_acct_id = request.POST.get('to_account')
    cat_id = (request.POST.get('category') or '').strip()
    tx_date = _parse_date(request.POST.get('transaction_date'))
    description = (request.POST.get('description') or '').strip()

    try:
        amount = _parse_decimal(request.POST.get('amount'), 'amount')
        fee_raw = (request.POST.get('fee') or '').strip()
        fee = _parse_decimal(fee_raw, 'fee', allow_zero=True) if fee_raw else Decimal('0')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('transactions')

    account = get_object_or_404(Account, pk=acct_id, user=request.user) if acct_id else resolve_default_account(request.user)
    to_account = None
    spent_category = None

    if kind == 'transfer':
        if not to_acct_id:
            messages.error(request, 'Pick a destination account for the transfer.')
            return redirect('transactions')
        to_account = get_object_or_404(Account, pk=to_acct_id, user=request.user)
        if to_account.pk == account.pk:
            messages.error(request, 'Pick two different accounts for a transfer.')
            return redirect('transactions')
    elif kind == 'expense' and cat_id:
        spent_category = get_object_or_404(SpentCategory, pk=cat_id, user=request.user)
        if Transaction.objects.filter(
            user=request.user,
            transaction_date=tx_date,
            spent_category=spent_category,
            is_active=True,
        ).exists():
            messages.error(
                request,
                f'An entry for category "{spent_category.name}" on {tx_date} already exists. '
                'Only one entry per category and date is allowed.'
            )
            return redirect('transactions')

    if kind == 'income':
        fee = Decimal('0')

    Transaction.objects.create(
        user=request.user,
        kind=kind,
        account=account,
        to_account=to_account,
        spent_category=spent_category,
        amount=amount,
        fee=fee,
        transaction_date=tx_date,
        description=description,
        is_active=True,
    )
    messages.success(request, f'{kind.capitalize()} recorded.')
    return redirect('transactions')


@login_required
@require_POST
def transactions_toggle(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    if tx.is_active:
        tx.is_active = False
        tx.save(update_fields=['is_active'])
        messages.success(request, f'TX-{tx.id} deactivated.')
    else:
        if tx.spent_category:
            dup = Transaction.objects.filter(
                user=request.user,
                transaction_date=tx.transaction_date,
                spent_category=tx.spent_category,
                is_active=True,
            ).exclude(pk=tx.pk).exists()
            if dup:
                messages.error(
                    request,
                    f'Cannot activate: an active transaction for "{tx.spent_category.name}" '
                    f'on {tx.transaction_date} already exists.'
                )
                return _safe_redirect(request, 'today')
        tx.is_active = True
        tx.save(update_fields=['is_active'])
        messages.success(request, f'TX-{tx.id} activated.')
    return _safe_redirect(request, 'today')


@login_required
@require_POST
def transactions_delete(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    tx.delete()
    messages.success(request, 'Transaction deleted.')
    return _safe_redirect(request, 'transactions')


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@login_required
def accounts_view(request):
    today = timezone.localdate()
    all_accounts = list(
        Account.objects.filter(user=request.user)
        .select_related('parent')
        .order_by('is_archived', '-is_default', 'name')
    )
    active_accounts = [a for a in all_accounts if not a.is_archived]
    archived_accounts = [a for a in all_accounts if a.is_archived]
    top_level_active = [a for a in active_accounts if a.parent_id is None]
    top_level_ids = {a.id for a in top_level_active}

    pots_by_parent = {}
    for a in active_accounts:
        if a.parent_id in top_level_ids:
            pots_by_parent.setdefault(a.parent_id, []).append(a)

    for a in top_level_active:
        a.pots_list = pots_by_parent.get(a.id, [])

    standalone_pots = [
        a for a in active_accounts
        if a.is_pot and a.parent_id and a.parent_id not in top_level_ids
    ]

    total_net_worth = sum((a.balance for a in active_accounts), Decimal('0'))
    total_liquid = sum((a.balance for a in active_accounts if not a.is_pot), Decimal('0'))
    total_pots = sum((a.balance for a in active_accounts if a.is_pot), Decimal('0'))
    low_balance_count = sum(1 for a in active_accounts if a.is_low_balance)

    parent_options = [a for a in active_accounts if not a.is_pot]
    show_archived = request.GET.get('show_archived') == '1'

    # Optional server-rendered Insights modal when ?insights=<id>
    insights_account = None
    insights_data = None
    insights_id = (request.GET.get('insights') or '').strip()
    if insights_id.isdigit():
        insights_account = get_object_or_404(Account, pk=int(insights_id), user=request.user)
        timeframe = request.GET.get('timeframe', 'month')
        if timeframe not in ('month', 'all'):
            timeframe = 'month'
        insights_data = compute_account_insights(insights_account, timeframe=timeframe)

    accounts_meta = {
        a.id: {
            'id': a.id,
            'name': a.name,
            'kind': a.kind,
            'account_number': a.account_number,
            'opening_balance': float(a.opening_balance),
            'as_of_date': a.as_of_date.isoformat(),
            'minimum_balance': float(a.minimum_balance),
            'parent': a.parent_id or '',
            'is_pot': a.is_pot,
            'is_default': a.is_default,
            'balance': float(a.balance),
        }
        for a in all_accounts
    }

    account_kinds = [
        {'id': k, 'name': v['name'], 'icon': v['icon']}
        for k, v in ACCOUNT_KINDS_META.items()
    ]

    ctx = {
        **_base_context('accounts'),
        'today_iso': today.isoformat(),
        'active_accounts': active_accounts,
        'archived_accounts': archived_accounts,
        'top_level_active': top_level_active,
        'standalone_pots': standalone_pots,
        'parent_options': parent_options,
        'show_archived': show_archived,
        'total_net_worth': total_net_worth,
        'total_liquid': total_liquid,
        'total_pots': total_pots,
        'low_balance_count': low_balance_count,
        'account_kinds': account_kinds,
        'accounts_json': json.dumps(accounts_meta),
        'insights_account': insights_account,
        'insights_data': insights_data,
    }
    return render(request, 'budget/accounts.html', ctx)


@login_required
@require_POST
def accounts_save(request):
    acct_id = (request.POST.get('id') or '').strip()
    name = (request.POST.get('name') or '').strip()
    kind = request.POST.get('kind', 'bank')
    account_number = (request.POST.get('account_number') or '').strip()
    as_of_date = _parse_date(request.POST.get('as_of_date'))
    parent_id = (request.POST.get('parent') or '').strip()
    is_pot = request.POST.get('is_pot') == 'on'
    is_default = request.POST.get('is_default') == 'on'

    if not name:
        messages.error(request, 'Account name is required.')
        return redirect('accounts')

    if kind not in ACCOUNT_KINDS_META:
        kind = 'bank'

    try:
        op_raw = (request.POST.get('opening_balance') or '').strip()
        opening_balance = Decimal(op_raw) if op_raw else Decimal('0')
        min_raw = (request.POST.get('minimum_balance') or '').strip()
        minimum_balance = _parse_decimal(min_raw, 'minimum balance', allow_zero=True) if min_raw else Decimal('0')
    except (InvalidOperation, ValueError) as exc:
        messages.error(request, str(exc) if isinstance(exc, ValueError) else 'Invalid numeric amount.')
        return redirect('accounts')

    parent = None
    if parent_id:
        parent = get_object_or_404(Account, pk=parent_id, user=request.user)

    if acct_id:
        acct = get_object_or_404(Account, pk=acct_id, user=request.user)
        if parent and parent.pk == acct.pk:
            parent = None
        if is_default:
            Account.objects.filter(user=request.user).exclude(pk=acct.pk).update(is_default=False)
        acct.name = name
        acct.kind = kind
        acct.account_number = account_number
        acct.opening_balance = opening_balance
        acct.as_of_date = as_of_date
        acct.minimum_balance = minimum_balance
        acct.parent = parent
        acct.is_pot = is_pot
        acct.is_default = is_default
        acct.save()
        messages.success(request, f'Account "{acct.name}" updated.')
    else:
        if not Account.objects.filter(user=request.user).exists():
            is_default = True
        elif is_default:
            Account.objects.filter(user=request.user).update(is_default=False)
        acct = Account.objects.create(
            user=request.user,
            name=name,
            kind=kind,
            account_number=account_number,
            opening_balance=opening_balance,
            as_of_date=as_of_date,
            minimum_balance=minimum_balance,
            parent=parent,
            is_pot=is_pot,
            is_default=is_default,
        )
        messages.success(request, f'Account "{acct.name}" created.')

    return redirect('accounts')


@login_required
@require_POST
def accounts_transfer(request):
    from_id = request.POST.get('from_account')
    to_id = request.POST.get('to_account')
    tx_date = _parse_date(request.POST.get('transaction_date'))
    narrative = (request.POST.get('narrative') or '').strip() or 'Account transfer'

    if not from_id or not to_id:
        messages.error(request, 'Please select both source and destination accounts.')
        return redirect('accounts')

    from_acct = get_object_or_404(Account, pk=from_id, user=request.user)
    to_acct = get_object_or_404(Account, pk=to_id, user=request.user)
    if from_acct.pk == to_acct.pk:
        messages.error(request, 'Pick two different accounts for a transfer.')
        return redirect('accounts')

    try:
        amount = _parse_decimal(request.POST.get('amount'), 'transfer amount')
        fee_raw = (request.POST.get('fee') or '').strip()
        fee = _parse_decimal(fee_raw, 'fee', allow_zero=True) if fee_raw else Decimal('0')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('accounts')

    Transaction.objects.create(
        user=request.user,
        kind='transfer',
        account=from_acct,
        to_account=to_acct,
        amount=amount,
        fee=fee,
        transaction_date=tx_date,
        description=narrative,
        is_active=True,
    )
    messages.success(request, f'Transferred {amount} from {from_acct.name} to {to_acct.name}.')
    return redirect('accounts')


@login_required
@require_POST
def accounts_reconcile(request, pk):
    acct = get_object_or_404(Account, pk=pk, user=request.user)
    actual_raw = request.POST.get('actual_balance')
    reconcile_date = _parse_date(request.POST.get('date'))
    notes = (request.POST.get('notes') or '').strip()

    try:
        tx, diff, _ = reconcile_account_balance(
            request.user, acct, actual_raw, reconcile_date=reconcile_date, notes=notes
        )
    except Exception:
        messages.error(request, 'Invalid actual balance amount.')
        return redirect('accounts')

    if tx is None:
        messages.info(request, f'"{acct.name}" balance already matches actual balance. No adjustment needed.')
    else:
        messages.success(request, f'"{acct.name}" reconciled (silent adjustment of {diff:+,.2f} recorded).')
    return redirect('accounts')


@login_required
@require_POST
def accounts_set_default(request, pk):
    acct = get_object_or_404(Account, pk=pk, user=request.user)
    Account.objects.filter(user=request.user).update(is_default=False)
    acct.is_default = True
    acct.save(update_fields=['is_default'])
    messages.success(request, f'"{acct.name}" set as default account.')
    return redirect('accounts')


@login_required
@require_POST
def accounts_archive(request, pk):
    acct = get_object_or_404(Account, pk=pk, user=request.user)
    acct.is_archived = True
    if acct.is_default:
        acct.is_default = False
        other = Account.objects.filter(user=request.user, is_archived=False).exclude(pk=acct.pk).first()
        if other:
            other.is_default = True
            other.save(update_fields=['is_default'])
    acct.save()
    messages.success(request, f'"{acct.name}" archived.')
    return redirect('accounts')


@login_required
@require_POST
def accounts_unarchive(request, pk):
    acct = get_object_or_404(Account, pk=pk, user=request.user)
    acct.is_archived = False
    acct.save(update_fields=['is_archived'])
    messages.success(request, f'"{acct.name}" restored.')
    return redirect(f"{reverse('accounts')}?show_archived=1")


@login_required
@require_POST
def accounts_delete(request, pk):
    acct = get_object_or_404(Account, pk=pk, user=request.user)
    name = acct.name
    acct.delete()
    messages.success(request, f'Account "{name}" deleted.')
    return redirect('accounts')


# ---------------------------------------------------------------------------
# Budget Plan
# ---------------------------------------------------------------------------

@login_required
def budget_view(request):
    today = timezone.localdate()
    budgets = list(Budget.objects.filter(user=request.user).order_by('-start_date', '-id'))
    budget_cats = list(
        BudgetCategory.objects.filter(user=request.user)
        .select_related('grouping')
        .order_by('grouping__priority', 'name')
    )
    group_cats = list(BudgetGroupCategory.objects.filter(user=request.user).order_by('priority', 'name'))

    selected_id_raw = (request.GET.get('budget') or '').strip()
    current_budget = None
    if selected_id_raw.isdigit():
        current_budget = next((b for b in budgets if b.id == int(selected_id_raw)), None)
    if current_budget is None and budgets:
        current_budget = budgets[0]

    grouped_items = []
    actual_spent_period = Decimal('0')

    if current_budget:
        period_expenses = Transaction.objects.filter(
            user=request.user,
            is_active=True,
            kind='expense',
            transaction_date__gte=current_budget.start_date,
            transaction_date__lte=current_budget.end_date,
        )
        actual_spent_period = period_expenses.aggregate(t=Sum('amount'))['t'] or Decimal('0')

        groups_map = {
            g.id: {
                'id': g.id,
                'name': g.name,
                'priority': g.priority,
                'items': [],
                'total_planned': Decimal('0'),
                'total_actual': Decimal('0'),
            }
            for g in group_cats
        }

        items = current_budget.items.select_related('budget_category__grouping').order_by(
            'budget_category__grouping__priority', 'budget_category__name'
        )
        for item in items:
            if item.budget_category:
                spent_ids = item.budget_category.spent_categories.values_list('id', flat=True)
                actual = period_expenses.filter(spent_category_id__in=spent_ids).aggregate(t=Sum('amount'))['t'] or Decimal('0')
                grp_id = item.budget_category.grouping_id
            else:
                actual = Decimal('0')
                grp_id = None

            planned = item.amount or Decimal('0')
            pct = min(100, round(float(actual) / float(planned) * 100)) if planned else 0
            item_row = {
                'id': item.id,
                'budget_id': current_budget.id,
                'budget_category_id': item.budget_category_id,
                'budget_category_name': item.budget_category.name if item.budget_category else 'Unassigned',
                'category_type': item.budget_category.category_type if item.budget_category else 'needs',
                'amount': planned,
                'actual_spent': actual,
                'pct': pct,
                'is_over': actual > planned,
                'reason': item.reason,
            }

            bucket = groups_map.get(grp_id)
            if bucket is None:
                bucket = groups_map.setdefault('other', {
                    'id': 'other',
                    'name': 'General Expenses',
                    'priority': 99,
                    'items': [],
                    'total_planned': Decimal('0'),
                    'total_actual': Decimal('0'),
                })
            bucket['items'].append(item_row)
            bucket['total_planned'] += planned
            bucket['total_actual'] += actual

        grouped_items = [g for g in groups_map.values() if g['items']]

    month_first = today.replace(day=1)
    last_day_num = calendar.monthrange(today.year, today.month)[1]
    month_last = today.replace(day=last_day_num)

    ctx = {
        **_base_context('budget'),
        'today': today,
        'default_budget_name': f'Budget {today.strftime("%Y-%m")}',
        'default_start': month_first.isoformat(),
        'default_end': month_last.isoformat(),
        'budgets': budgets,
        'current_budget': current_budget,
        'budget_categories': budget_cats,
        'grouped_items': grouped_items,
        'actual_spent_period': actual_spent_period,
    }
    return render(request, 'budget/budget.html', ctx)


@login_required
@require_POST
def budget_save(request):
    budget_id = (request.POST.get('id') or '').strip()
    name = (request.POST.get('name') or '').strip()
    description = (request.POST.get('description') or '').strip()
    start_date = _parse_date(request.POST.get('start_date'))
    end_date = _parse_date(request.POST.get('end_date'))

    if not name:
        messages.error(request, 'Budget name is required.')
        return redirect('budget')

    try:
        allocated_amount = _parse_decimal(request.POST.get('allocated_amount'), 'allocated budget amount', allow_zero=True)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('budget')

    if budget_id:
        b = get_object_or_404(Budget, pk=budget_id, user=request.user)
        b.name = name
        b.description = description
        b.start_date = start_date
        b.end_date = end_date
        b.allocated_amount = allocated_amount
        b.save()
        messages.success(request, f'Budget "{b.name}" updated.')
    else:
        b = Budget.objects.create(
            user=request.user,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            allocated_amount=allocated_amount,
        )
        messages.success(request, f'Budget "{b.name}" created.')

    return redirect(f"{reverse('budget')}?budget={b.id}")


@login_required
@require_POST
def budget_item_save(request):
    item_id = (request.POST.get('id') or '').strip()
    budget_id = (request.POST.get('budget') or '').strip()
    bcat_id = (request.POST.get('budget_category') or '').strip()
    reason = (request.POST.get('reason') or '').strip()

    b = get_object_or_404(Budget, pk=budget_id, user=request.user)
    try:
        amount = _parse_decimal(request.POST.get('amount'), 'planned amount')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(f"{reverse('budget')}?budget={b.id}")

    if item_id:
        item = get_object_or_404(BudgetItem, pk=item_id, budget__user=request.user)
        item.amount = amount
        item.reason = reason
        item.save()
        messages.success(request, f'Budget item "{item.budget_category.name}" updated.')
    else:
        if not bcat_id:
            messages.error(request, 'Please select a Budget Category.')
            return redirect(f"{reverse('budget')}?budget={b.id}")
        bcat = get_object_or_404(BudgetCategory, pk=bcat_id, user=request.user)
        try:
            BudgetItem.objects.create(
                budget=b,
                budget_category=bcat,
                amount=amount,
                reason=reason,
            )
            messages.success(request, f'Added "{bcat.name}" to budget.')
        except IntegrityError:
            messages.error(request, f'"{bcat.name}" already has an allocation in this budget. Edit the existing item instead.')

    return redirect(f"{reverse('budget')}?budget={b.id}")


@login_required
@require_POST
def budget_item_delete(request, pk):
    item = get_object_or_404(BudgetItem, pk=pk, budget__user=request.user)
    budget_id = item.budget_id
    item.delete()
    messages.success(request, 'Budget item removed.')
    return redirect(f"{reverse('budget')}?budget={budget_id}")


# ---------------------------------------------------------------------------
# Debts
# ---------------------------------------------------------------------------

@login_required
def debts_view(request):
    debts = list(Debt.objects.filter(user=request.user).order_by('id'))
    for d in debts:
        if d.principal and d.principal > 0:
            pct = float((d.principal - d.balance) / d.principal) * 100
            d.paid_pct = max(0, min(100, round(pct, 1)))
        else:
            d.paid_pct = 0

    active_accounts = list(
        Account.objects.filter(user=request.user, is_archived=False)
        .order_by('-is_default', 'name')
    )
    default_account = next((a for a in active_accounts if a.is_default), active_accounts[0] if active_accounts else None)

    ctx = {
        **_base_context('debts'),
        'debts': debts,
        'active_accounts': active_accounts,
        'default_account': default_account,
    }
    return render(request, 'budget/debts.html', ctx)


@login_required
@require_POST
def debts_add(request):
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, 'Debt name is required.')
        return redirect('debts')

    try:
        principal = _parse_decimal(request.POST.get('principal'), 'principal', allow_zero=True)
        ir_raw = (request.POST.get('interest_rate') or '').strip()
        interest_rate = _parse_decimal(ir_raw, 'interest rate', allow_zero=True) if ir_raw else Decimal('0')
        mp_raw = (request.POST.get('min_payment') or '').strip()
        min_payment = _parse_decimal(mp_raw, 'minimum payment', allow_zero=True) if mp_raw else Decimal('0')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('debts')

    Debt.objects.create(
        user=request.user,
        name=name,
        principal=principal,
        interest_rate=interest_rate,
        min_payment=min_payment,
    )
    messages.success(request, f'Debt "{name}" added.')
    return redirect('debts')


@login_required
@require_POST
def debts_repay(request, pk):
    debt = get_object_or_404(Debt, pk=pk, user=request.user)
    acct_id = request.POST.get('account')
    account = get_object_or_404(Account, pk=acct_id, user=request.user) if acct_id else resolve_default_account(request.user)

    try:
        amount = _parse_decimal(request.POST.get('amount'), 'repayment amount')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('debts')

    Transaction.objects.create(
        user=request.user,
        kind='expense',
        account=account,
        debt=debt,
        amount=amount,
        transaction_date=timezone.localdate(),
        description=f'Repayment: {debt.name}',
        is_active=True,
    )
    messages.success(request, f'Recorded repayment of {amount} for "{debt.name}".')
    return redirect('debts')


@login_required
@require_POST
def debts_delete(request, pk):
    debt = get_object_or_404(Debt, pk=pk, user=request.user)
    name = debt.name
    debt.delete()
    messages.success(request, f'Debt "{name}" deleted.')
    return redirect('debts')
