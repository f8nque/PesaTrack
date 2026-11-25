import calendar
from decimal import Decimal
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from .excel import parse_xlsx
from .models import (
    Account, Budget, BudgetCategory, BudgetGroupCategory, Debt,
    SpentCategory, Transaction, total
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
    qs = Account.objects.filter(user=user, is_archived=False).exclude(kind='debtors')
    acct = qs.filter(is_default=True).first()
    if not acct:
        acct = qs.first()
    if not acct:
        acct = Account.objects.create(user=user, name='Cash', kind='cash', is_default=True)
    return acct


def compute_budget_category_actual(period_tx_qs, budget_category):
    """Sum active expenses, linked debit adjustments, and linked fees for a BudgetCategory."""
    if not budget_category:
        return Decimal('0')
    spent_ids = budget_category.spent_categories.values_list('id', flat=True)
    amount_total = period_tx_qs.filter(
        (
            models.Q(kind='expense')
            & (
                models.Q(spent_category_id__in=spent_ids)
                | models.Q(budget_category_id=budget_category.id)
                | models.Q(budget_category__isnull=True, debt__budget_category_id=budget_category.id)
            )
        )
        | models.Q(kind='adjustment', adjustment_type='debit', budget_category_id=budget_category.id)
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    fee_total = period_tx_qs.filter(
        kind__in=('expense', 'transfer'),
        fee__gt=0,
        fee_budget_category_id=budget_category.id,
    ).aggregate(t=Sum('fee'))['t'] or Decimal('0')
    return amount_total + fee_total


def compute_summary(user, month_str=None):
    """Compute monthly financial state: income -> budget -> actual -> remaining."""
    today = timezone.localdate()
    y, m, month = parse_month(month_str)

    f = lambda qs: float(qs.aggregate(t=Sum('amount'))['t'] or 0)
    tx_qs = Transaction.objects.filter(user=user, is_active=True)
    inm = tx_qs.filter(transaction_date__year=y, transaction_date__month=m)
    exp = inm.filter(kind='expense')
    income = f(inm.filter(kind='income'))
    linked_adj_debit = f(inm.filter(kind='adjustment', adjustment_type='debit', budget_category__isnull=False))
    linked_fees = float(
        inm.filter(kind__in=('expense', 'transfer'), fee__gt=0, fee_budget_category__isnull=False)
        .aggregate(t=Sum('fee'))['t'] or 0
    )
    spent = f(exp.filter(debt__isnull=True)) + linked_adj_debit + linked_fees
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
            actual = float(compute_budget_category_actual(inm, item.budget_category))
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

    active_accounts = Account.objects.filter(user=user, is_archived=False).exclude(kind='debtors')
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


def reconcile_account_balance(user, account, actual_balance, reconcile_date=None, notes='', budget_category=None):
    """Create a reconciliation adjustment transaction (silent unless linked to a budget_category)."""
    actual = Decimal(str(actual_balance))
    current = account.balance
    diff = actual - current
    reconcile_date = reconcile_date or timezone.localdate()

    if diff == 0:
        return None, Decimal('0'), current

    adj_type = 'credit' if diff > 0 else 'debit'
    amt = abs(diff)
    desc = notes or f"Balance Adjustment ({'+' if diff > 0 else '-'}{amt} reconciled to {actual})"
    linked_bcat = budget_category if adj_type == 'debit' else None

    tx = Transaction.objects.create(
        user=user,
        account=account,
        kind='adjustment',
        adjustment_type=adj_type,
        budget_category=linked_bcat,
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


def resolve_or_register_debtor_account(user, account_id=None, debtor_name='', account_number=''):
    """Find an existing debtor account (by id or case-insensitive name) or register a new one."""
    clean_name = (debtor_name or '').strip()
    clean_num = (account_number or '').strip()

    if clean_name:
        existing = Account.objects.filter(
            user=user, kind='debtors', name__iexact=clean_name
        ).first()
        if existing:
            if existing.is_archived:
                existing.is_archived = False
                existing.save(update_fields=['is_archived'])
            return existing, False
        created = Account.objects.create(
            user=user,
            name=clean_name,
            kind='debtors',
            account_number=clean_num,
        )
        return created, True

    if account_id:
        existing = Account.objects.filter(user=user, pk=account_id).first()
        if existing:
            return existing, False

    return None, False


def compute_debt_analysis(user, year=None):
    """Build a Debtors vs Months (Jan-Dec) matrix of loans taken and repayments for a given year."""
    today = timezone.localdate()
    try:
        selected_year = int(year) if year is not None and str(year).strip() else today.year
        if not (1900 <= selected_year <= 2100):
            selected_year = today.year
    except (ValueError, TypeError):
        selected_year = today.year

    debt_years = {d.year for d in Debt.objects.filter(user=user).dates('registration_date', 'year')}
    repay_years = {
        d.year for d in Transaction.objects.filter(
            user=user, debt__isnull=False, is_active=True
        ).dates('transaction_date', 'year')
    }
    available_years = sorted(debt_years | repay_years | {today.year, selected_year}, reverse=True)

    months_meta = [
        {'num': m, 'short': calendar.month_abbr[m], 'full': calendar.month_name[m]}
        for m in range(1, 13)
    ]

    debtor_accounts = list(
        Account.objects.filter(user=user, kind='debtors', is_archived=False).order_by('name')
    )
    debts = list(
        Debt.objects.filter(user=user).select_related('account').order_by('name', 'id')
    )
    repayments = list(
        Transaction.objects.filter(
            user=user, debt__isnull=False, is_active=True
        ).select_related('debt__account')
    )

    rows_map = {}

    def _ensure_row(key, label, account_id=None):
        if key not in rows_map:
            rows_map[key] = {
                'key': key,
                'label': label,
                'account_id': account_id,
                'months': {m: {'taken': Decimal('0'), 'paid': Decimal('0')} for m in range(1, 13)},
                'total_borrowed': Decimal('0'),
                'total_paid': Decimal('0'),
            }
        return rows_map[key]

    for acct in debtor_accounts:
        _ensure_row(('acct', acct.id), acct.name, acct.id)

    debt_row_key = {}
    for d in debts:
        if d.account_id:
            key = ('acct', d.account_id)
            label = d.account.name
            acct_id = d.account_id
        else:
            key = ('legacy', d.name.strip().lower() or f'debt-{d.id}')
            label = d.name
            acct_id = None
        row = _ensure_row(key, label, acct_id)
        debt_row_key[d.id] = key
        row['total_borrowed'] += d.principal
        if d.registration_date and d.registration_date.year == selected_year:
            row['months'][d.registration_date.month]['taken'] += d.principal

    for tx in repayments:
        key = debt_row_key.get(tx.debt_id)
        if not key:
            continue
        row = rows_map[key]
        row['total_paid'] += tx.amount
        if tx.transaction_date and tx.transaction_date.year == selected_year:
            row['months'][tx.transaction_date.month]['paid'] += tx.amount

    monthly_totals = [{'month': m, 'taken': Decimal('0'), 'paid': Decimal('0')} for m in range(1, 13)]
    rows = []
    grand_year_taken = Decimal('0')
    grand_year_paid = Decimal('0')
    grand_balance = Decimal('0')

    for entry in sorted(rows_map.values(), key=lambda r: r['label'].lower()):
        month_cells = []
        year_taken = Decimal('0')
        year_paid = Decimal('0')
        for idx in range(12):
            m = idx + 1
            t_amt = entry['months'][m]['taken']
            p_amt = entry['months'][m]['paid']
            year_taken += t_amt
            year_paid += p_amt
            monthly_totals[idx]['taken'] += t_amt
            monthly_totals[idx]['paid'] += p_amt
            month_cells.append({
                'month': m,
                'taken': float(t_amt),
                'paid': float(p_amt),
            })

        bal = entry['total_borrowed'] - entry['total_paid']
        grand_year_taken += year_taken
        grand_year_paid += year_paid
        grand_balance += bal

        rows.append({
            'label': entry['label'],
            'account_id': entry['account_id'],
            'months': month_cells,
            'year_taken': float(year_taken),
            'year_paid': float(year_paid),
            'total_borrowed': float(entry['total_borrowed']),
            'total_paid': float(entry['total_paid']),
            'balance': float(bal),
        })

    return {
        'selected_year': selected_year,
        'available_years': available_years,
        'months': months_meta,
        'rows': rows,
        'monthly_totals': [
            {
                'month': mt['month'],
                'taken': float(mt['taken']),
                'paid': float(mt['paid']),
            }
            for mt in monthly_totals
        ],
        'grand_year_taken': float(grand_year_taken),
        'grand_year_paid': float(grand_year_paid),
        'grand_net_change': float(grand_year_taken - grand_year_paid),
        'grand_balance': float(grand_balance),
    }


CATEGORY_TEMPLATE_HEADERS = [
    'Budget Grouping',
    'Grouping Priority (1-10)',
    'Budget Category',
    'Category Type (needs/wants/savings)',
    'Budget Active (YES/NO)',
    'Spent Category',
    'As Savings (YES/NO)',
    'Spent Active (YES/NO)',
]

_HEADER_ALIASES = {
    'budget grouping': 'grouping',
    'grouping': 'grouping',
    'grouping name': 'grouping',
    'budget grouping category': 'grouping',
    'grouping priority (1-10)': 'priority',
    'grouping priority': 'priority',
    'priority': 'priority',
    'priority (1-10)': 'priority',
    'budget category': 'budget_category',
    'category type (needs/wants/savings)': 'category_type',
    'category type': 'category_type',
    'type': 'category_type',
    'budget active (yes/no)': 'budget_active',
    'budget active': 'budget_active',
    'spent category': 'spent_category',
    'as savings (yes/no)': 'is_savings',
    'as savings': 'is_savings',
    'spent active (yes/no)': 'spent_active',
    'spent active': 'spent_active',
}

_TRUE_VALS = {'yes', 'y', 'true', '1', 'active'}
_FALSE_VALS = {'no', 'n', 'false', '0', 'inactive'}


def _parse_bool_cell(raw, default, field_label, row_num, errors):
    val = str(raw or '').strip().lower()
    if not val:
        return default, False
    if val in _TRUE_VALS:
        return True, True
    if val in _FALSE_VALS:
        return False, True
    errors.append(f'Row {row_num}: "{raw}" is not a valid {field_label} value (use YES or NO).')
    return default, False


def build_categories_template_sheets(user):
    """Build workbook sheets [(sheet_name, rows), ...] for the category Excel template."""
    data_rows = [list(CATEGORY_TEMPLATE_HEADERS)]

    groups = (
        BudgetGroupCategory.objects.filter(user=user)
        .prefetch_related('budget_categories__spent_categories')
        .order_by('priority', 'name')
    )
    for grp in groups:
        bcats = list(grp.budget_categories.all().order_by('name'))
        if not bcats:
            data_rows.append([grp.name, grp.priority, '', '', '', '', '', ''])
            continue
        for bcat in bcats:
            bcat_active = 'YES' if bcat.is_active else 'NO'
            scats = list(bcat.spent_categories.all().order_by('name'))
            if not scats:
                data_rows.append([
                    grp.name, grp.priority, bcat.name, bcat.category_type, bcat_active, '', '', ''
                ])
                continue
            for scat in scats:
                data_rows.append([
                    grp.name,
                    grp.priority,
                    bcat.name,
                    bcat.category_type,
                    bcat_active,
                    scat.name,
                    'YES' if scat.is_savings else 'NO',
                    'YES' if scat.is_active else 'NO',
                ])

    unassigned = SpentCategory.objects.filter(user=user, budget_category__isnull=True).order_by('name')
    for scat in unassigned:
        data_rows.append([
            '', '', '', '', '',
            scat.name,
            'YES' if scat.is_savings else 'NO',
            'YES' if scat.is_active else 'NO',
        ])

    guide_rows = [
        ['Column', 'Required', 'Allowed Values / Format', 'Example'],
        ['Budget Grouping', 'Yes (for Budget Categories)', 'Text up to 80 chars (Level 1 grouping)', 'UPKEEP'],
        ['Grouping Priority (1-10)', 'No (defaults to 1)', 'Integer from 1 (highest) to 10 (lowest)', 1],
        ['Budget Category', 'No (optional if only adding groupings)', 'Text up to 80 chars (Level 2 category)', 'Shopping'],
        ['Category Type (needs/wants/savings)', 'No (defaults to wants)', 'needs, wants, or savings', 'needs'],
        ['Budget Active (YES/NO)', 'No (defaults to YES)', 'YES or NO', 'YES'],
        ['Spent Category', 'No (optional)', 'Text up to 80 chars (Level 3 spent item)', 'Supermarket'],
        ['As Savings (YES/NO)', 'No (defaults to NO)', 'YES or NO', 'NO'],
        ['Spent Active (YES/NO)', 'No (defaults to YES)', 'YES or NO', 'YES'],
        [],
        ['Sample Rows (copy format into the Categories sheet):'],
        list(CATEGORY_TEMPLATE_HEADERS),
        ['UPKEEP', 1, 'Shopping', 'needs', 'YES', 'Supermarket', 'NO', 'YES'],
        ['UPKEEP', 1, 'Shopping', 'needs', 'YES', 'Meat', 'NO', 'YES'],
        ['HOUSING', 2, 'Rent & Utilities', 'needs', 'YES', 'Electricity', 'NO', 'YES'],
        ['SAVINGS', 3, 'Emergency Fund', 'savings', 'YES', 'MMF Deposit', 'YES', 'YES'],
    ]

    return [
        ('Categories', data_rows),
        ('Guide', guide_rows),
    ]


def import_categories_from_xlsx(user, file_obj):
    """Parse and atomically import 3-tier categories from an uploaded .xlsx file."""
    sheets = parse_xlsx(file_obj)
    target_rows = None
    for name, rows in sheets:
        if name.strip().lower() == 'categories':
            target_rows = rows
            break
    if target_rows is None:
        target_rows = sheets[0][1]

    if not target_rows:
        return None, ['The uploaded worksheet is empty. Download the template and add your categories.']

    header_row = [str(c).strip() for c in target_rows[0]]
    col_map = {}
    for idx, h in enumerate(header_row):
        canonical = _HEADER_ALIASES.get(h.lower())
        if canonical and canonical not in col_map:
            col_map[canonical] = idx

    if not any(k in col_map for k in ('grouping', 'budget_category', 'spent_category')):
        return None, [
            'Unrecognized header row. Please use the downloaded Excel template columns '
            '(Budget Grouping, Grouping Priority (1-10), Budget Category, Category Type, Budget Active, '
            'Spent Category, As Savings, Spent Active).'
        ]

    def cell(row, key):
        idx = col_map.get(key)
        if idx is None or idx >= len(row):
            return ''
        return str(row[idx] or '').strip()

    errors = []
    parsed_entries = []
    known_bcat_names = set(
        b.lower() for b in BudgetCategory.objects.filter(user=user).values_list('name', flat=True)
    )

    for row_num, row in enumerate(target_rows[1:], start=2):
        if not any(str(c).strip() for c in row):
            continue

        grp_name = cell(row, 'grouping')
        priority_raw = cell(row, 'priority')
        bcat_name = cell(row, 'budget_category')
        cat_type_raw = cell(row, 'category_type')
        bcat_active_raw = cell(row, 'budget_active')
        scat_name = cell(row, 'spent_category')
        is_savings_raw = cell(row, 'is_savings')
        spent_active_raw = cell(row, 'spent_active')

        if not grp_name and not bcat_name and not scat_name:
            continue

        for label, val in (
            ('Budget Grouping', grp_name),
            ('Budget Category', bcat_name),
            ('Spent Category', scat_name),
        ):
            if len(val) > 80:
                errors.append(f'Row {row_num}: {label} "{val[:20]}..." exceeds 80 characters.')

        priority = 1
        priority_provided = False
        if priority_raw:
            try:
                p_num = int(float(priority_raw))
                if not (1 <= p_num <= 10) or float(priority_raw) != p_num:
                    raise ValueError
                priority = p_num
                priority_provided = True
            except ValueError:
                errors.append(f'Row {row_num}: Grouping Priority "{priority_raw}" must be an integer between 1 and 10.')

        cat_type = 'wants'
        cat_type_provided = False
        if cat_type_raw:
            normalized_type = cat_type_raw.lower()
            if normalized_type not in ('needs', 'wants', 'savings'):
                errors.append(
                    f'Row {row_num}: Category Type "{cat_type_raw}" must be needs, wants, or savings.'
                )
            else:
                cat_type = normalized_type
                cat_type_provided = True

        bcat_active, bcat_active_provided = _parse_bool_cell(
            bcat_active_raw, True, 'Budget Active', row_num, errors
        )
        is_savings, is_savings_provided = _parse_bool_cell(
            is_savings_raw, False, 'As Savings', row_num, errors
        )
        spent_active, spent_active_provided = _parse_bool_cell(
            spent_active_raw, True, 'Spent Active', row_num, errors
        )

        if bcat_name:
            if grp_name:
                known_bcat_names.add(bcat_name.lower())
            elif bcat_name.lower() not in known_bcat_names:
                errors.append(
                    f'Row {row_num}: Budget Grouping is required for new Budget Category "{bcat_name}".'
                )

        parsed_entries.append({
            'row_num': row_num,
            'grp_name': grp_name,
            'priority': priority,
            'priority_provided': priority_provided,
            'bcat_name': bcat_name,
            'cat_type': cat_type,
            'cat_type_provided': cat_type_provided,
            'bcat_active': bcat_active,
            'bcat_active_provided': bcat_active_provided,
            'scat_name': scat_name,
            'is_savings': is_savings,
            'is_savings_provided': is_savings_provided,
            'spent_active': spent_active,
            'spent_active_provided': spent_active_provided,
        })

    if not parsed_entries and not errors:
        return None, ['No category rows found in the uploaded file. Fill in at least one row below the header.']

    if errors:
        return None, errors

    stats = {
        'rows_processed': len(parsed_entries),
        'groups_created': 0,
        'groups_updated': 0,
        'budget_created': 0,
        'budget_updated': 0,
        'spent_created': 0,
        'spent_updated': 0,
    }

    with transaction.atomic():
        groups_by_key = {
            g.name.lower(): g for g in BudgetGroupCategory.objects.filter(user=user)
        }
        bcats_by_key = {
            (b.grouping_id, b.name.lower()): b for b in BudgetCategory.objects.filter(user=user)
        }
        bcats_by_name = {}
        for b in bcats_by_key.values():
            bcats_by_name.setdefault(b.name.lower(), b)
        scats_by_key = {
            s.name.lower(): s for s in SpentCategory.objects.filter(user=user)
        }

        updated_group_ids = set()
        updated_bcat_ids = set()
        updated_scat_ids = set()

        for entry in parsed_entries:
            grp = None
            if entry['grp_name']:
                g_key = entry['grp_name'].lower()
                grp = groups_by_key.get(g_key)
                if grp is None:
                    grp = BudgetGroupCategory.objects.create(
                        user=user,
                        name=entry['grp_name'],
                        priority=entry['priority'],
                    )
                    groups_by_key[g_key] = grp
                    stats['groups_created'] += 1
                elif entry['priority_provided'] and grp.priority != entry['priority']:
                    grp.priority = entry['priority']
                    grp.save(update_fields=['priority', 'updated_at'])
                    if grp.id not in updated_group_ids:
                        updated_group_ids.add(grp.id)
                        stats['groups_updated'] += 1

            bcat = None
            if entry['bcat_name']:
                b_name_key = entry['bcat_name'].lower()
                if grp is not None:
                    bcat = bcats_by_key.get((grp.id, b_name_key))
                else:
                    bcat = bcats_by_name.get(b_name_key)

                if bcat is None:
                    bcat = BudgetCategory.objects.create(
                        user=user,
                        grouping=grp,
                        name=entry['bcat_name'],
                        category_type=entry['cat_type'],
                        is_active=entry['bcat_active'],
                    )
                    bcats_by_key[(grp.id, b_name_key)] = bcat
                    bcats_by_name.setdefault(b_name_key, bcat)
                    stats['budget_created'] += 1
                else:
                    changed_fields = []
                    if entry['cat_type_provided'] and bcat.category_type != entry['cat_type']:
                        bcat.category_type = entry['cat_type']
                        changed_fields.append('category_type')
                    if entry['bcat_active_provided'] and bcat.is_active != entry['bcat_active']:
                        bcat.is_active = entry['bcat_active']
                        changed_fields.append('is_active')
                    if changed_fields:
                        changed_fields.append('updated_at')
                        bcat.save(update_fields=changed_fields)
                        if bcat.id not in updated_bcat_ids:
                            updated_bcat_ids.add(bcat.id)
                            stats['budget_updated'] += 1

            if entry['scat_name']:
                s_key = entry['scat_name'].lower()
                scat = scats_by_key.get(s_key)
                if scat is None:
                    scat = SpentCategory.objects.create(
                        user=user,
                        budget_category=bcat,
                        name=entry['scat_name'],
                        is_savings=entry['is_savings'],
                        is_active=entry['spent_active'],
                    )
                    scats_by_key[s_key] = scat
                    stats['spent_created'] += 1
                else:
                    changed_fields = []
                    if bcat is not None and scat.budget_category_id != bcat.id:
                        scat.budget_category = bcat
                        changed_fields.append('budget_category')
                    if entry['is_savings_provided'] and scat.is_savings != entry['is_savings']:
                        scat.is_savings = entry['is_savings']
                        changed_fields.append('is_savings')
                    if entry['spent_active_provided'] and scat.is_active != entry['spent_active']:
                        scat.is_active = entry['spent_active']
                        changed_fields.append('is_active')
                    if changed_fields:
                        changed_fields.append('updated_at')
                        scat.save(update_fields=changed_fields)
                        if scat.id not in updated_scat_ids:
                            updated_scat_ids.add(scat.id)
                            stats['spent_updated'] += 1

    return stats, []
