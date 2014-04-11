# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe.utils import flt, fmt_money, getdate
from frappe import _

from frappe.model.document import Document

class GLEntry(Document):

	def validate(self):
		self.check_mandatory()
		self.pl_must_have_cost_center()
		self.validate_posting_date()
		self.check_pl_account()
		self.validate_cost_center()

	def on_update_with_args(self, adv_adj, update_outstanding = 'Yes'):
		self.validate_account_details(adv_adj)
		validate_frozen_account(self.account, adv_adj)
		check_freezing_date(self.posting_date, adv_adj)
		validate_balance_type(self.account, adv_adj)

		# Update outstanding amt on against voucher
		if self.against_voucher and update_outstanding == 'Yes':
			update_outstanding_amt(self.party, self.against_voucher_type, self.against_voucher)

	def check_mandatory(self):
		mandatory = ['account','remarks','voucher_type','voucher_no','fiscal_year','company']
		for k in mandatory:
			if not self.get(k):
				frappe.throw(k + _(" is mandatory for GL Entry"))

		# Zero value transaction is not allowed
		if not (flt(self.debit) or flt(self.credit)):
			frappe.throw(_("GL Entry: Debit or Credit amount is mandatory for ") +
				self.account)

	def pl_must_have_cost_center(self):
		if frappe.db.get_value("Account", self.account, "report_type") == "Profit and Loss":
			if not self.cost_center and self.voucher_type != 'Period Closing Voucher':
				frappe.throw(_("Cost Center must be specified for Profit and Loss type account: ")
					+ self.account)
		elif self.cost_center:
			self.cost_center = None

	def validate_posting_date(self):
		from erpnext.accounts.utils import validate_fiscal_year
		validate_fiscal_year(self.posting_date, self.fiscal_year, "Posting Date")

	def check_pl_account(self):
		if self.is_opening=='Yes' and \
				frappe.db.get_value("Account", self.account, "report_type")=="Profit and Loss":
			frappe.throw(_("For opening balance entry, account can not be \
				a Profit and Loss type account"))

	def validate_account_details(self, adv_adj):
		"""Account must be ledger, active and not freezed"""

		ret = frappe.db.sql("""select group_or_ledger, docstatus, company
			from tabAccount where name=%s""", self.account, as_dict=1)[0]

		if ret.group_or_ledger=='Group':
			frappe.throw(_("Account") + ": " + self.account + _(" is not a ledger"))

		if ret.docstatus==2:
			frappe.throw(_("Account") + ": " + self.account + _(" is not active"))

		if ret.company != self.company:
			frappe.throw(_("Account") + ": " + self.account +
				_(" does not belong to the company") + ": " + self.company)

		if frappe.db.get_value("Party", self.party, "docstatus") == 2:
			frappe.throw(_("Party") + ": " + self.party + _(" is not active"))

	def validate_cost_center(self):
		if not hasattr(self, "cost_center_company"):
			self.cost_center_company = {}

		def _get_cost_center_company():
			if not self.cost_center_company.get(self.cost_center):
				self.cost_center_company[self.cost_center] = frappe.db.get_value(
					"Cost Center", self.cost_center, "company")

			return self.cost_center_company[self.cost_center]

		if self.cost_center and _get_cost_center_company() != self.company:
				frappe.throw(_("Cost Center") + ": " + self.cost_center +
					_(" does not belong to the company") + ": " + self.company)

def validate_balance_type(account, adv_adj=False):
	if not adv_adj and account:
		balance_must_be = frappe.db.get_value("Account", account, "balance_must_be")
		if balance_must_be:
			balance = frappe.db.sql("""select sum(ifnull(debit, 0)) - sum(ifnull(credit, 0))
				from `tabGL Entry` where account = %s""", account)[0][0]

			if (balance_must_be=="Debit" and flt(balance) < 0) or \
				(balance_must_be=="Credit" and flt(balance) > 0):
					frappe.throw("Credit" if balance_must_be=="Debit" else "Credit"
						+ _(" balance is not allowed for account ") + account)

def check_freezing_date(posting_date, adv_adj=False):
	"""
		Nobody can do GL Entries where posting date is before freezing date
		except authorized person
	"""
	if not adv_adj:
		acc_frozen_upto = frappe.db.get_value('Accounts Settings', None, 'acc_frozen_upto')
		if acc_frozen_upto:
			bde_auth_role = frappe.db.get_value( 'Accounts Settings', None,'bde_auth_role')
			if getdate(posting_date) <= getdate(acc_frozen_upto) \
					and not bde_auth_role in frappe.user.get_roles():
				frappe.throw(_("You are not authorized to do/modify back dated entries before ")
					+ getdate(acc_frozen_upto).strftime('%d-%m-%Y'))

def update_outstanding_amt(party, against_voucher_type, against_voucher, on_cancel=False):
	# get final outstanding amt
	bal = flt(frappe.db.sql("""select sum(ifnull(debit, 0)) - sum(ifnull(credit, 0))
		from `tabGL Entry`
		where against_voucher_type=%s and against_voucher=%s and party = %s""",
		(against_voucher_type, against_voucher, party))[0][0] or 0.0)

	if against_voucher_type == 'Purchase Invoice':
		bal = -bal
	elif against_voucher_type == "Journal Voucher":
		against_voucher_amount = flt(frappe.db.sql("""
			select sum(ifnull(debit, 0)) - sum(ifnull(credit, 0))
			from `tabGL Entry` where voucher_type = 'Journal Voucher' and voucher_no = %s
			and party = %s and ifnull(against_voucher, '') = ''""",
			(against_voucher, party))[0][0])
		bal = against_voucher_amount + bal
		if against_voucher_amount < 0:
			bal = -bal

	# Validation : Outstanding can not be negative
	if bal < 0 and not on_cancel:
		frappe.throw(_("Outstanding for Voucher ") + against_voucher + _(" will become ") +
			fmt_money(bal) + _(". Outstanding cannot be less than zero. \
			 	Please match exact outstanding."))

	# Update outstanding amt on against voucher
	if against_voucher_type in ["Sales Invoice", "Purchase Invoice"]:
		frappe.db.sql("update `tab%s` set outstanding_amount=%s where name=%s" %
			(against_voucher_type, '%s', '%s'),	(bal, against_voucher))

def validate_frozen_account(account, adv_adj=None):
	frozen_account = frappe.db.get_value("Account", account, "freeze_account")
	if frozen_account == 'Yes' and not adv_adj:
		frozen_accounts_modifier = frappe.db.get_value( 'Accounts Settings', None,
			'frozen_accounts_modifier')

		if not frozen_accounts_modifier:
			frappe.throw(account + _(" is a frozen account. Either make the account active or assign role in Accounts Settings who can create / modify entries against this account"))
		elif frozen_accounts_modifier not in frappe.user.get_roles():
			frappe.throw(account + _(" is a frozen account. To create / edit transactions against this account, you need role") \
				+ ": " +  frozen_accounts_modifier)
