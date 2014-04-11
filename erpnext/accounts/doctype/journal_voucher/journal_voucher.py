# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe.utils import cint, cstr, flt, fmt_money, formatdate, getdate
from frappe import msgprint, _
from erpnext.setup.utils import get_company_currency

from erpnext.controllers.accounts_controller import AccountsController

class JournalVoucher(AccountsController):
	def __init__(self, arg1, arg2=None):
		super(JournalVoucher, self).__init__(arg1, arg2)
		self.is_approving_authority = -1

	def validate(self):
		if not self.is_opening:
			self.is_opening='No'

		self.clearance_date = None

		super(JournalVoucher, self).validate_date_with_fiscal_year()

		self.validate_debit_credit()
		self.validate_cheque_info()
		self.validate_entries_for_advance()
		self.validate_against_jv()

		self.set_against_account()
		self.create_remarks()
		self.set_aging_date()
		self.set_print_format_fields()


	def on_submit(self):
		if self.voucher_type in ['Bank Voucher', 'Contra Voucher', 'Journal Entry']:
			self.check_credit_days()
		self.make_gl_entries()
		self.check_credit_limit()

	def on_cancel(self):
		from erpnext.accounts.utils import remove_against_link_from_jv
		remove_against_link_from_jv(self.doctype, self.name, "against_jv")

		self.make_gl_entries(1)

	def on_trash(self):
		pass
		#if self.amended_from:
		#	frappe.delete_doc("Journal Voucher", self.amended_from)

	def validate_debit_credit(self):
		for d in self.get('entries'):
			if d.debit and d.credit:
				msgprint("You cannot credit and debit same account at the same time.",
				 	raise_exception=1)

	def validate_cheque_info(self):
		if self.voucher_type in ['Bank Voucher']:
			if not self.cheque_no or not self.cheque_date:
				msgprint("Reference No & Reference Date is required for %s" %
				self.voucher_type, raise_exception=1)

		if self.cheque_date and not self.cheque_no:
			msgprint("Reference No is mandatory if you entered Reference Date", raise_exception=1)

	def validate_entries_for_advance(self):
		for d in self.get('entries'):
			if d.party and not (d.is_advance or d.against_voucher or d.against_invoice or d.against_jv):
				customer, supplier = frappe.db.get_value("Party", d.party, ["customer", "supplier"])
				if (customer and flt(d.credit) > 0) or (supplier and flt(d.debit) > 0):
					msgprint("Message: Please check Is Advance as 'Yes' against \
						Account %s if this is an advance entry." % d.account)

	def validate_against_jv(self):
		for d in self.get('entries'):
			if d.against_jv:
				if d.against_jv == self.name:
					msgprint("You can not enter current voucher in 'Against JV' column",
						raise_exception=1)
				elif not frappe.db.sql("""select name from `tabJournal Voucher Detail`
						where account = %s and docstatus = 1 and parent = %s""",
						(d.account, d.against_jv)):
					msgprint("Against JV: %s is not valid." % d.against_jv, raise_exception=1)

	def set_against_account(self):
		# Debit = Credit
		debit, credit = 0.0, 0.0
		debit_list, credit_list = [], []
		for d in self.get('entries'):
			debit += flt(d.debit, 2)
			credit += flt(d.credit, 2)
			if flt(d.debit)>0 and (d.account not in debit_list): debit_list.append(d.account)
			if flt(d.credit)>0 and (d.account not in credit_list): credit_list.append(d.account)

		self.total_debit = debit
		self.total_credit = credit

		if abs(self.total_debit-self.total_credit) > 0.001:
			msgprint("Debit must be equal to Credit. The difference is %s" %
			 	(self.total_debit-self.total_credit), raise_exception=1)

		# update against account
		for d in self.get('entries'):
			if flt(d.debit) > 0: d.against_account = ', '.join(credit_list)
			if flt(d.credit) > 0: d.against_account = ', '.join(debit_list)

	def create_remarks(self):
		r = []
		if self.cheque_no:
			if self.cheque_date:
				r.append('Via Reference #%s dated %s' %
					(self.cheque_no, formatdate(self.cheque_date)))
			else :
				msgprint("Please enter Reference date", raise_exception=1)

		for d in self.get('entries'):
			if d.against_invoice and d.credit:
				currency = frappe.db.get_value("Sales Invoice", d.against_invoice, "currency")
				r.append('%s %s against Invoice: %s' %
					(cstr(currency), fmt_money(flt(d.credit)), d.against_invoice))

			if d.against_voucher and d.debit:
				bill_no = frappe.db.sql("""select bill_no, bill_date, currency
					from `tabPurchase Invoice` where name=%s""", d.against_voucher)
				if bill_no and bill_no[0][0] and bill_no[0][0].lower().strip() \
						not in ['na', 'not applicable', 'none']:
					r.append('%s %s against Bill %s dated %s' %
						(cstr(bill_no[0][2]), fmt_money(flt(d.debit)), bill_no[0][0],
						bill_no[0][1] and formatdate(bill_no[0][1].strftime('%Y-%m-%d')) or ''))

		if self.user_remark:
			r.append("User Remark : %s"%self.user_remark)

		if r:
			self.remark = ("\n").join(r)
		else:
			frappe.msgprint("User Remarks is mandatory", raise_exception=1)

	def set_aging_date(self):
		if self.is_opening != 'Yes':
			self.aging_date = self.posting_date
		else:
			# check account type whether receivable or payable
			receivable_or_payable = False
			for d in self.get('entries'):
				account_type = frappe.db.get_value("Account", d.account, "account_type")
				if account_type in ["Receivable", "Payable"]:
					receivable_or_payable = True
					break

			# If customer/supplier account, aging date is mandatory
			if receivable_or_payable and not self.aging_date:
				msgprint("Aging Date is mandatory for opening entry", raise_exception=1)
			else:
				self.aging_date = self.posting_date

	def set_print_format_fields(self):
		for d in self.get('entries'):
			if d.party and not self.pay_to_recd_from:
				self.pay_to_recd_from = frappe.db.get_value("Party", d.party, "party_name")

			if frappe.db.get_value("Account", d.account, "account_type") in ['Bank', 'Cash']:
				company_currency = get_company_currency(self.company)
				amt = flt(d.debit) or flt(d.credit)
				self.total_amount = company_currency + ' ' + cstr(amt)
				from frappe.utils import money_in_words
				self.total_amount_in_words = money_in_words(amt, company_currency)

	def check_credit_days(self):
		date_diff = 0
		if self.cheque_date:
			date_diff = (getdate(self.cheque_date) - getdate(self.posting_date)).days

		if date_diff <= 0: return

		global_credit_days = cint(frappe.db.get_value("Company", self.company, "credit_days"))
		for d in self.get("entries"):
			if d.party:
				credit_days = cint(frappe.db.get_value("Party", d.party, "credit_days")) or global_credit_days

				if credit_days > 0 and not self.get_authorized_user() and cint(date_diff) > credit_days:
					frappe.throw(_("Can not allow credit more than ") + credit_days + _(" days"))

	def get_authorized_user(self):
		if self.is_approving_authority==-1:
			self.is_approving_authority = 0

			# Fetch credit controller role
			approving_authority = frappe.db.get_value("Global Defaults", None,
				"credit_controller")

			# Check logged-in user is authorized
			if approving_authority in frappe.user.get_roles():
				self.is_approving_authority = 1

		return self.is_approving_authority

	def check_account_against_entries(self):
		for d in self.get("entries"):
			if d.party:
				if d.against_invoice and frappe.db.get_value("Sales Invoice",
						d.against_invoice, "party") != d.party:
					frappe.throw(_("Row #") + cstr(d.idx) +  ": " +
						_("Party is not matching with Party in Sales Invoice"))

				if d.against_voucher and frappe.db.get_value("Purchase Invoice",
						d.against_voucher, "party") != d.party:
					frappe.throw(_("Row #") + cstr(d.idx) + ": " +
						_("Party is not matching with Party in Purchase Invoice"))

	def make_gl_entries(self, cancel=0, adv_adj=0):
		from erpnext.accounts.general_ledger import make_gl_entries

		if not cancel:
			self.check_account_against_entries()

		gl_map = []
		for d in self.get("entries"):
			if d.debit or d.credit:
				gl_map.append(
					self.get_gl_dict({
						"account": d.account,
						"party": d.party,
						"against": d.against_account,
						"debit": d.debit,
						"credit": d.credit,
						"against_voucher_type": ((d.against_voucher and "Purchase Invoice")
							or (d.against_invoice and "Sales Invoice")
							or (d.against_jv and "Journal Voucher")),
						"against_voucher": d.against_voucher or d.against_invoice or d.against_jv,
						"remarks": self.remark,
						"cost_center": d.cost_center
					})
				)
		if gl_map:
			make_gl_entries(gl_map, cancel=cancel, adv_adj=adv_adj)

	def check_credit_limit(self):
		for d in self.get("entries"):
			if d.party:
				frappe.get_doc("Party", d.party).check_credit_limit(self.company)

	def get_balance(self):
		if not self.get('entries'):
			msgprint("Please enter atleast 1 entry in 'GL Entries' table")
		else:
			flag, self.total_debit, self.total_credit = 0, 0, 0
			diff = flt(self.difference, 2)

			# If any row without amount, set the diff on that row
			for d in self.get('entries'):
				if not d.credit and not d.debit and diff != 0:
					if diff>0:
						d.credit = diff
					elif diff<0:
						d.debit = diff
					flag = 1

			# Set the diff in a new row
			if flag == 0 and diff != 0:
				jd = self.append('entries', {})
				if diff>0:
					jd.credit = abs(diff)
				elif diff<0:
					jd.debit = abs(diff)

			# Set the total debit, total credit and difference
			for d in self.get('entries'):
				self.total_debit += flt(d.debit, 2)
				self.total_credit += flt(d.credit, 2)

			self.difference = flt(self.total_debit, 2) - flt(self.total_credit, 2)

	def get_outstanding_invoices(self):
		self.set('entries', [])
		total = 0
		for d in self.get_values():
			total += flt(d.outstanding_amount)
			jd = self.append('entries', {})
			jd.account = cstr(d.account)
			jd.party = cstr(d.party)
			if self.write_off_based_on == 'Accounts Receivable':
				jd.credit = flt(d.outstanding_amount)
				jd.against_invoice = cstr(d.name)
			elif self.write_off_based_on == 'Accounts Payable':
				jd.debit = flt(d.outstanding_amount)
				jd.against_voucher = cstr(d.name)
			jd.save(1)
		jd = self.append('entries', {})
		if self.write_off_based_on == 'Accounts Receivable':
			jd.debit = total
		elif self.write_off_based_on == 'Accounts Payable':
			jd.credit = total
		jd.save(1)

	def get_values(self):
		cond = (' and outstanding_amount <= ' + self.write_off_amount) if flt(self.write_off_amount) else ''
		if self.write_off_based_on == 'Accounts Receivable':
			return frappe.db.sql("""select name, debit_to, party, outstanding_amount
				from `tabSales Invoice` where docstatus = 1 and company = %s
				and outstanding_amount > 0 %s""" % ('%s', cond), self.company, as_dict=1)
		elif self.write_off_based_on == 'Accounts Payable':
			return frappe.db.sql("""select name, credit_to as account, party, outstanding_amount
				from `tabPurchase Invoice` where docstatus = 1 and company = %s
				and outstanding_amount > 0 %s""" % ('%s', cond), self.company, as_dict=1)

@frappe.whitelist()
def get_default_bank_cash_account(company, voucher_type):
	from erpnext.accounts.utils import get_balance_on
	account = frappe.db.get_value("Company", company,
		voucher_type=="Bank Voucher" and "default_bank_account" or "default_cash_account")
	if account:
		return {
			"account": account,
			"balance": get_balance_on(account)
		}

@frappe.whitelist()
def get_payment_entry_from_sales_invoice(sales_invoice):
	from erpnext.accounts.utils import get_balance_on
	si = frappe.get_doc("Sales Invoice", sales_invoice)
	jv = get_payment_entry(si)
	jv.remark = 'Payment received against Sales Invoice {0}. {1}'.format(si.name, si.remarks)

	jv.get("entries")[0].account = si.debit_to
	jv.get("entries")[0].party = si.party
	jv.get("entries")[0].balance = get_balance_on(si.debit_to)
	jv.get("entries")[0].credit = si.outstanding_amount
	jv.get("entries")[0].against_invoice = si.name

	# debit bank
	jv.get("entries")[1].debit = si.outstanding_amount

	return jv.as_dict()

@frappe.whitelist()
def get_payment_entry_from_purchase_invoice(purchase_invoice):
	from erpnext.accounts.utils import get_balance_on
	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	jv = get_payment_entry(pi)
	jv.remark = 'Payment against Purchase Invoice {0}. {1}'.format(pi.name, pi.remarks)

	jv.get("entries")[0].account = pi.credit_to
	jv.get("entries")[0].party = pi.party
	jv.get("entries")[0].balance = get_balance_on(pi.credit_to)
	jv.get("entries")[0].debit = pi.outstanding_amount
	jv.get("entries")[0].against_voucher = pi.name

	# credit bank
	jv.get("entries")[1].credit = pi.outstanding_amount

	return jv.as_dict()

def get_payment_entry(doc):
	bank_account = get_default_bank_cash_account(doc.company, "Bank Voucher")

	jv = frappe.new_doc('Journal Voucher')
	jv.voucher_type = 'Bank Voucher'

	jv.company = doc.company
	jv.fiscal_year = doc.fiscal_year

	jv.append("entries")
	d = jv.append("entries")

	if bank_account:
		d.account = bank_account["account"]
		d.balance = bank_account["balance"]

	return jv

@frappe.whitelist()
def get_opening_accounts(company):
	"""get all balance sheet accounts for opening entry"""
	from erpnext.accounts.utils import get_balance_on
	accounts = frappe.db.sql_list("""select name from tabAccount
		where group_or_ledger='Ledger' and report_type='Profit and Loss' and company=%s""", company)

	return [{"account": a, "balance": get_balance_on(a)} for a in accounts]

def get_against_jv(doctype, txt, searchfield, start, page_len, filters):
	return frappe.db.sql("""select jv.name, jv.posting_date, jv.user_remark
		from `tabJournal Voucher` jv, `tabJournal Voucher Detail` jv_detail
		where jv_detail.parent = jv.name and jv_detail.account = %s and jv.docstatus = 1
		and jv.%s like %s order by jv.name desc limit %s, %s""" %
		("%s", searchfield, "%s", "%s", "%s"),
		(filters["account"], "%%%s%%" % txt, start, page_len))

@frappe.whitelist()
def get_outstanding(args):
	args = eval(args)
	if args.get("doctype") == "Journal Voucher" and args.get("party"):
		against_jv_amount = frappe.db.sql("""
			select sum(ifnull(debit, 0)) - sum(ifnull(credit, 0))
			from `tabJournal Voucher Detail` where parent=%s and party=%s
			and ifnull(against_invoice, '')='' and ifnull(against_voucher, '')=''
			and ifnull(against_jv, '')=''""", (args['docname'], args['party']))

		against_jv_amount = flt(against_jv_amount[0][0]) if against_jv_amount else 0
		if against_jv_amount > 0:
			return {"credit": against_jv_amount}
		else:
			return {"debit": -1* against_jv_amount}

	elif args.get("doctype") == "Sales Invoice":
		return {
			"credit": flt(frappe.db.get_value("Sales Invoice", args["docname"], "outstanding_amount"))
		}
	elif args.get("doctype") == "Purchase Invoice":
		return {
			"debit": flt(frappe.db.get_value("Purchase Invoice", args["docname"], "outstanding_amount"))
		}
