from django.urls import path
from . import views

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # Today's Spends (default landing page)
    path('', views.today_view, name='today'),
    path('today/save/', views.today_save, name='today_save'),

    # Categories (3-tier)
    path('categories/', views.categories_view, name='categories'),
    path('categories/save/', views.categories_save, name='categories_save'),
    path('categories/<str:tier>/<int:pk>/delete/', views.categories_delete, name='categories_delete'),
    path('categories/<str:tier>/<int:pk>/toggle/', views.categories_toggle, name='categories_toggle'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Transactions
    path('transactions/', views.transactions_view, name='transactions'),
    path('transactions/add/', views.transactions_add, name='transactions_add'),
    path('transactions/<int:pk>/toggle/', views.transactions_toggle, name='transactions_toggle'),
    path('transactions/<int:pk>/delete/', views.transactions_delete, name='transactions_delete'),

    # Accounts
    path('accounts/', views.accounts_view, name='accounts'),
    path('accounts/save/', views.accounts_save, name='accounts_save'),
    path('accounts/transfer/', views.accounts_transfer, name='accounts_transfer'),
    path('accounts/<int:pk>/reconcile/', views.accounts_reconcile, name='accounts_reconcile'),
    path('accounts/<int:pk>/set-default/', views.accounts_set_default, name='accounts_set_default'),
    path('accounts/<int:pk>/archive/', views.accounts_archive, name='accounts_archive'),
    path('accounts/<int:pk>/unarchive/', views.accounts_unarchive, name='accounts_unarchive'),
    path('accounts/<int:pk>/delete/', views.accounts_delete, name='accounts_delete'),

    # Budget Plan
    path('budget/', views.budget_view, name='budget'),
    path('budget/save/', views.budget_save, name='budget_save'),
    path('budget/item/save/', views.budget_item_save, name='budget_item_save'),
    path('budget/item/<int:pk>/delete/', views.budget_item_delete, name='budget_item_delete'),

    # Debts
    path('debts/', views.debts_view, name='debts'),
    path('debts/payments/', views.debts_payments, name='debts_payments'),
    path('debts/analysis/', views.debts_analysis, name='debts_analysis'),
    path('debts/accounts/check/', views.debts_account_check, name='debts_account_check'),
    path('debts/accounts/register/', views.debts_account_register, name='debts_account_register'),
    path('debts/add/', views.debts_add, name='debts_add'),
    path('debts/repay/', views.debts_repay_form, name='debts_repay_form'),
    path('debts/<int:pk>/repay/', views.debts_repay, name='debts_repay'),
    path('debts/<int:pk>/delete/', views.debts_delete, name='debts_delete'),

    # Setup
    path('setup/', views.setup_view, name='setup'),
    path('setup/categories/template/', views.setup_categories_template, name='setup_categories_template'),
    path('setup/categories/upload/', views.setup_categories_upload, name='setup_categories_upload'),
]
