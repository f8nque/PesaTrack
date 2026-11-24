import calendar
from decimal import Decimal
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from .models import (
    Account, Budget, Debt, Transaction, total
)


def parse_month(month_str=None):
    """Parse 'YYYY-MM' into (year, month, normalized_str), defaulting to current month."""
    today = timezone.localdate()
    raw = month_str or today.strftime('%Y-%m')
    try:
        y, m = map(int, raw.split('-'))
        if not (1 <= m <= 12):
            raise ValueError
        return y, m, f"{y:04d}-{m:02d}"
    except (ValueError, AttributeError):
        return today.year, today.month, today.strftime('%Y-%m')


def resolve_default_account(user):
    """Return user's active default account, first active account, or create a Cash account."""
    acct = Account.objects.filter(user=user, is_default=True, is_archived=False).first()
    if not acct:
        acct = Account.objects.filter(user=user, is_archived=False).first()
    if not acct:
        acct = Account.objects.create(user=user, name='Cash', kind='cash', is_default=True)
    return acct


def compute_summary(user, month_str=None):
    """Compute monthly financial state: income -> budget -> actual -> remaining."""
    today = timezone.localdate()
    y, m, month = parse_month(month_str)

    f = lambda qs: float(qs.aggregate(t=Sum('amount'))['t'] or 0)
    tx_qs = Transaction.objects.filter(user=user, is_active=True)
    inm = tx_qs.filter(transaction_date__year=y, transaction_date__month=m)
    exp = inm.filter(kind='expense')
    income = f(inm.filter(kind='income'))
    spent = f(exp.filter(debt__isnull=True))
    debt_paid = f(exp.filter(debt__isnull=False))

    active_budget = Budget.objects.filter(
        user=user, start_date__year=y, start_date__month=m
    ).first()

    budget_items = []
    allocated_amount = 0.0
    total_planned = 0.0

    if active_budget:
        allocated_amount = float(active_budget.allocated_amount)
        items = active_budget.items.select_related('budget_category__grouping').order_by(
            'budget_category__grouping__priority', 'budget_category__name'
        )
        for item in items:
            spent_ids = item.budget_category.spent_categories.values_list('id', flat=True)
            actual = f(exp.filter(spent_category_id__in=spent_ids))
            planned = float(item.amount)
            budget_items.append({
                'id': item.id,
                'category_id': item.budget_category_id,
                'name': item.budget_category.name,
                'grouping': item.budget_category.grouping.name,
                'grouping_priority': item.budget_category.grouping.priority,
                'category_type': item.budget_category.category_type,
                'planned': planned,
                'actual': actual,
                'remaining': planned - actual,
                'pct': min(100, round((actual / planned) * 100)) if planned else 0,
                'is_over': actual > planned,
                'reason': item.reason,
            })
        total_planned = sum(b['planned'] for b in budget_items)

    fees = float(inm.exclude(fee=0).aggregate(t=Sum('fee'))['t'] or 0)
    left = income - spent - debt_paid

    active_accounts = Account.objects.filter(user=user, is_archived=False)
    liquid_balance = float(sum(a.balance for a in active_accounts.filter(is_pot=False)))
    total_balance = float(sum(a.balance for a in active_accounts))
    pots_balance = float(sum(a.balance for a in active_accounts.filter(is_pot=True)))

    return {
        'month': month,
        'income': income,
        'spent': spent,
        'debt_paid': debt_paid,
        'fees': fees,
        'left': left,
        'allocated_budget': allocated_amount,
        'planned': total_planned,
        'unallocated': allocated_amount - total_planned,
        'savings_rate': round(left / income * 100, 1) if income else 0,
        'today_spent': f(tx_qs.filter(kind='expense', transaction_date=today)),
        'budget': budget_items,
        'budget_id': active_budget.id if active_budget else None,
        'budget_name': active_budget.name if active_budget else None,
        'total_balance': total_balance,
        'liquid_balance': liquid_balance,
        'pots_balance': pots_balance,
        'debt_balance': float(sum(d.balance for d in Debt.objects.filter(user=user))),
    }


def reconcile_account_balance(user, account, actual_balance, reconcile_date=None, notes=''):
    """Create a silent adjustment transaction to reconcile account balance to actual_balance."""
    actual = Decimal(str(actual_balance))
    current = account.balance
    diff = actual - current
    reconcile_date = reconcile_date or timezone.localdate()

    if diff == 0:
        return None, Decimal('0'), current

    adj_type = 'credit' if diff > 0 else 'debit'
    amt = abs(diff)
    desc = notes or f"Balance Adjustment ({'+' if diff > 0 else '-'}{amt} reconciled to {actual})"

    tx = Transaction.objects.create(
        user=user,
        account=account,
        kind='adjustment',
        adjustment_type=adj_type,
        amount=amt,
        transaction_date=reconcile_date,
        description=desc,
        is_active=True,
    )
    account.refresh_from_db()
    return tx, diff, account.balance


def compute_account_insights(account, month_str=None, timeframe='month'):
    """Compute inflow, outflow, net flow, daily average, top categories, pots, and recent txs for an account."""
    today = timezone.localdate()
    y, m, month = parse_month(month_str)

    tx_out = account.transactions.filter(is_active=True)
    tx_in = account.incoming.filter(is_active=True, kind='transfer')

    if timeframe == 'month':
        tx_out_period = tx_out.filter(transaction_date__year=y, transaction_date__month=m)
        tx_in_period = tx_in.filter(transaction_date__year=y, transaction_date__month=m)
    else:
        tx_out_period = tx_out
        tx_in_period = tx_in

    f = lambda qs, field='amount': float(qs.aggregate(t=Sum(field))['t'] or 0)

    income_amt = f(tx_out_period.filter(kind='income'))
    transfers_in_amt = f(tx_in_period)
    adj_credit_amt = f(tx_out_period.filter(kind='adjustment', adjustment_type='credit'))
    total_inflow = income_amt + transfers_in_amt + adj_credit_amt

    expenses_amt = f(tx_out_period.filter(kind='expense'))
    transfers_out_amt = f(tx_out_period.filter(kind='transfer'))
    fees_amt = f(tx_out_period.exclude(fee=0), 'fee')
    adj_debit_amt = f(tx_out_period.filter(kind='adjustment', adjustment_type='debit'))
    total_outflow = expenses_amt + transfers_out_amt + fees_amt + adj_debit_amt

    net_flow = total_inflow - total_outflow

    if timeframe == 'month':
        days_count = max(today.day, 1) if (y == today.year and m == today.month) else calendar.monthrange(y, m)[1]
    else:
        first_tx = tx_out.order_by('transaction_date').first()
        days_count = max((today - first_tx.transaction_date).days, 1) if first_tx else 1

    avg_daily_spend = round((expenses_amt + fees_amt) / days_count, 2)

    cat_expenses = (
        tx_out_period.filter(kind='expense', spent_category__isnull=False)
        .values('spent_category__id', 'spent_category__name', 'spent_category__budget_category__name')
        .annotate(total_spent=Sum('amount'))
        .order_by('-total_spent')[:8]
    )
    total_cat_spent = expenses_amt or 1.0
    top_categories = []
    for c in cat_expenses:
        amt = float(c['total_spent'] or 0)
        pct = round((amt / total_cat_spent) * 100, 1)
        top_categories.append({
            'category_id': c['spent_category__id'],
            'name': c['spent_category__name'],
            'budget_category': c['spent_category__budget_category__name'],
            'total_spent': amt,
            'percentage': pct,
        })

    recent_qs = Transaction.objects.filter(
        models.Q(account=account) | models.Q(to_account=account),
        is_active=True
    ).select_related('account', 'to_account', 'spent_category').order_by('-transaction_date', '-id')[:15]

    pots = [
        {
            'id': pot.id,
            'name': pot.name,
            'kind': pot.kind,
            'balance': float(pot.balance),
            'is_pot': pot.is_pot,
        }
        for pot in account.sub_accounts.filter(is_archived=False)
    ]

    flow_total = (total_inflow + total_outflow) or 1.0
    return {
        'timeframe': timeframe,
        'month': month,
        'inflow': {
            'income': income_amt,
            'transfers_in': transfers_in_amt,
            'adjustments_credit': adj_credit_amt,
            'total': total_inflow,
            'pct': round((total_inflow / flow_total) * 100, 1),
        },
        'outflow': {
            'expenses': expenses_amt,
            'transfers_out': transfers_out_amt,
            'fees': fees_amt,
            'adjustments_debit': adj_debit_amt,
            'total': total_outflow,
            'pct': round((total_outflow / flow_total) * 100, 1),
        },
        'net_flow': net_flow,
        'average_daily_spend': avg_daily_spend,
        'top_categories': top_categories,
        'recent_qs': recent_qs,
        'pots': pots,
    }
