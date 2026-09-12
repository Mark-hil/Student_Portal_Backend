"""URL routing for Student Financials & Billing."""
from django.urls import path
from .views import (
    StudentStatementView,
    MoMoPaymentView,
    SubmitBankSlipView,
    PaymentReceiptPDFView,
    BankStudentLookupView,
    BankPaymentNotificationView,
    AdminFinancialsOverviewView,
    AdminVerifySlipView,
    AdminAdjustStatementView,
    AdminFeeStructureView,
    AdminExportStatementsView,
    AdminExportPaymentsView,
    StudentExportStatementView,
)

urlpatterns = [
    # Student endpoints
    path("my-statement/", StudentStatementView.as_view(), name="my_statement"),
    path("statement/export-csv/", StudentExportStatementView.as_view(), name="student_export_statement"),
    path("pay/momo/", MoMoPaymentView.as_view(), name="pay_momo"),
    path("pay/bank-slip/", SubmitBankSlipView.as_view(), name="submit_bank_slip"),
    path("payments/<int:pk>/receipt/", PaymentReceiptPDFView.as_view(), name="payment_receipt_pdf"),

    # Bank Collect Integration & Webhooks
    path("bank/lookup/", BankStudentLookupView.as_view(), name="bank_lookup"),
    path("bank/notify/", BankPaymentNotificationView.as_view(), name="bank_notify"),

    # Bursar / Admin endpoints
    path("admin/overview/", AdminFinancialsOverviewView.as_view(), name="admin_overview"),
    path("admin/export/statements/", AdminExportStatementsView.as_view(), name="admin_export_statements"),
    path("admin/export/payments/", AdminExportPaymentsView.as_view(), name="admin_export_payments"),
    path("admin/verify-slip/<int:pk>/", AdminVerifySlipView.as_view(), name="admin_verify_slip"),
    path("admin/adjust/", AdminAdjustStatementView.as_view(), name="admin_adjust"),
    path("admin/fee-structure/", AdminFeeStructureView.as_view(), name="admin_fee_structure"),
]
