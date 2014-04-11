# Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
import frappe.utils

from frappe.utils import cstr, flt, getdate

from frappe import msgprint
from frappe.model.mapper import get_mapped_doc

from erpnext.controllers.selling_controller import SellingController

class SalesOrder(SellingController):
	tname = 'Sales Order Item'
	fname = 'sales_order_details'
	person_tname = 'Target Detail'
	partner_tname = 'Partner Target Detail'
	territory_tname = 'Territory Target Detail'

	def validate_mandatory(self):
		# validate transaction date v/s delivery date
		if self.delivery_date:
			if getdate(self.transaction_date) > getdate(self.delivery_date):
				msgprint("Expected Delivery Date cannot be before Sales Order Date")
				raise Exception

	def validate_po(self):
		# validate p.o date v/s delivery date
		if self.po_date and self.delivery_date and getdate(self.po_date) > getdate(self.delivery_date):
			msgprint("Expected Delivery Date cannot be before Purchase Order Date")
			raise Exception

		if self.po_no and self.party:
			so = frappe.db.sql("select name from `tabSales Order` \
				where ifnull(po_no, '') = %s and name != %s and docstatus < 2\
				and party = %s", (self.po_no, self.name, self.party))
			if so and so[0][0]:
				msgprint("""Another Sales Order (%s) exists against same PO No and Customer.
					Please be sure, you are not making duplicate entry.""" % so[0][0])

	def validate_for_items(self):
		check_list, flag = [], 0
		chk_dupl_itm = []
		for d in self.get('sales_order_details'):
			e = [d.item_code, d.description, d.warehouse, d.prevdoc_docname or '']
			f = [d.item_code, d.description]

			if frappe.db.get_value("Item", d.item_code, "is_stock_item") == 'Yes':
				if not d.warehouse:
					msgprint("""Please enter Reserved Warehouse for item %s
						as it is stock Item""" % d.item_code, raise_exception=1)

				if e in check_list:
					msgprint("Item %s has been entered twice." % d.item_code)
				else:
					check_list.append(e)
			else:
				if f in chk_dupl_itm:
					msgprint("Item %s has been entered twice." % d.item_code)
				else:
					chk_dupl_itm.append(f)

			# used for production plan
			d.transaction_date = self.transaction_date

			tot_avail_qty = frappe.db.sql("select projected_qty from `tabBin` \
				where item_code = %s and warehouse = %s", (d.item_code,d.warehouse))
			d.projected_qty = tot_avail_qty and flt(tot_avail_qty[0][0]) or 0

	def validate_sales_mntc_quotation(self):
		for d in self.get('sales_order_details'):
			if d.prevdoc_docname:
				res = frappe.db.sql("select name from `tabQuotation` where name=%s and order_type = %s", (d.prevdoc_docname, self.order_type))
				if not res:
					msgprint("""Order Type (%s) should be same in Quotation: %s \
						and current Sales Order""" % (self.order_type, d.prevdoc_docname))

	def validate_order_type(self):
		super(SalesOrder, self).validate_order_type()

	def validate_delivery_date(self):
		if self.order_type == 'Sales' and not self.delivery_date:
			msgprint("Please enter 'Expected Delivery Date'")
			raise Exception

		self.validate_sales_mntc_quotation()

	def validate_proj_cust(self):
		if self.project_name and self.party_name:
			res = frappe.db.sql("""select name from `tabProject` where name = %s
				and (party = %s or ifnull(party,'')='')""", (self.project_name, self.party))
			if not res:
				frappe.throw("""Customer - %s does not belong to project - %s. \n
					If you want to use project for multiple customers then please make customer \
					details blank in project - %s.""" % (self.party, self.project_name, self.project_name))

	def validate(self):
		super(SalesOrder, self).validate()

		self.validate_order_type()
		self.validate_delivery_date()
		self.validate_mandatory()
		self.validate_proj_cust()
		self.validate_po()
		self.validate_uom_is_integer("stock_uom", "qty")
		self.validate_for_items()
		self.validate_warehouse()

		from erpnext.stock.doctype.packed_item.packed_item import make_packing_list

		make_packing_list(self,'sales_order_details')

		self.validate_with_previous_doc()

		if not self.status:
			self.status = "Draft"

		from erpnext.utilities import validate_status
		validate_status(self.status, ["Draft", "Submitted", "Stopped",
			"Cancelled"])

		if not self.billing_status: self.billing_status = 'Not Billed'
		if not self.delivery_status: self.delivery_status = 'Not Delivered'

	def validate_warehouse(self):
		from erpnext.stock.utils import validate_warehouse_company

		warehouses = list(set([d.warehouse for d in
			self.get(self.fname) if d.warehouse]))

		for w in warehouses:
			validate_warehouse_company(w, self.company)

	def validate_with_previous_doc(self):
		super(SalesOrder, self).validate_with_previous_doc(self.tname, {
			"Quotation": {
				"ref_dn_field": "prevdoc_docname",
				"compare_fields": [["company", "="], ["currency", "="]]
			}
		})


	def update_enquiry_status(self, prevdoc, flag):
		enq = frappe.db.sql("select t2.prevdoc_docname from `tabQuotation` t1, `tabQuotation Item` t2 where t2.parent = t1.name and t1.name=%s", prevdoc)
		if enq:
			frappe.db.sql("update `tabOpportunity` set status = %s where name=%s",(flag,enq[0][0]))

	def update_prevdoc_status(self, flag):
		for quotation in list(set([d.prevdoc_docname for d in self.get(self.fname)])):
			if quotation:
				doc = frappe.get_doc("Quotation", quotation)
				if doc.docstatus==2:
					frappe.throw(quotation + ": " + frappe._("Quotation is cancelled."))

				doc.set_status(update=True)

	def on_submit(self):
		self.update_stock_ledger(update_stock = 1)

		frappe.get_doc("Party", self.party).check_credit_limit(self.company, self.grand_total)

		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype, self.grand_total, self)

		self.update_prevdoc_status('submit')
		frappe.db.set(self, 'status', 'Submitted')

	def on_cancel(self):
		# Cannot cancel stopped SO
		if self.status == 'Stopped':
			msgprint("Sales Order : '%s' cannot be cancelled as it is Stopped. Unstop it for any further transactions" %(self.name))
			raise Exception
		self.check_nextdoc_docstatus()
		self.update_stock_ledger(update_stock = -1)

		self.update_prevdoc_status('cancel')

		frappe.db.set(self, 'status', 'Cancelled')

	def check_nextdoc_docstatus(self):
		# Checks Delivery Note
		submit_dn = frappe.db.sql("select t1.name from `tabDelivery Note` t1,`tabDelivery Note Item` t2 where t1.name = t2.parent and t2.against_sales_order = %s and t1.docstatus = 1", self.name)
		if submit_dn:
			msgprint("Delivery Note : " + cstr(submit_dn[0][0]) + " has been submitted against " + cstr(self.doctype) + ". Please cancel Delivery Note : " + cstr(submit_dn[0][0]) + " first and then cancel "+ cstr(self.doctype), raise_exception = 1)

		# Checks Sales Invoice
		submit_rv = frappe.db.sql("""select t1.name
			from `tabSales Invoice` t1,`tabSales Invoice Item` t2
			where t1.name = t2.parent and t2.sales_order = %s and t1.docstatus = 1""",
			self.name)
		if submit_rv:
			msgprint("Sales Invoice : " + cstr(submit_rv[0][0]) + " has already been submitted against " +cstr(self.doctype)+ ". Please cancel Sales Invoice : "+ cstr(submit_rv[0][0]) + " first and then cancel "+ cstr(self.doctype), raise_exception = 1)

		#check maintenance schedule
		submit_ms = frappe.db.sql("select t1.name from `tabMaintenance Schedule` t1, `tabMaintenance Schedule Item` t2 where t2.parent=t1.name and t2.prevdoc_docname = %s and t1.docstatus = 1",self.name)
		if submit_ms:
			msgprint("Maintenance Schedule : " + cstr(submit_ms[0][0]) + " has already been submitted against " +cstr(self.doctype)+ ". Please cancel Maintenance Schedule : "+ cstr(submit_ms[0][0]) + " first and then cancel "+ cstr(self.doctype), raise_exception = 1)

		# check maintenance visit
		submit_mv = frappe.db.sql("select t1.name from `tabMaintenance Visit` t1, `tabMaintenance Visit Purpose` t2 where t2.parent=t1.name and t2.prevdoc_docname = %s and t1.docstatus = 1",self.name)
		if submit_mv:
			msgprint("Maintenance Visit : " + cstr(submit_mv[0][0]) + " has already been submitted against " +cstr(self.doctype)+ ". Please cancel Maintenance Visit : " + cstr(submit_mv[0][0]) + " first and then cancel "+ cstr(self.doctype), raise_exception = 1)

		# check production order
		pro_order = frappe.db.sql("""select name from `tabProduction Order` where sales_order = %s and docstatus = 1""", self.name)
		if pro_order:
			msgprint("""Production Order: %s exists against this sales order.
				Please cancel production order first and then cancel this sales order""" %
				pro_order[0][0], raise_exception=1)

	def check_modified_date(self):
		mod_db = frappe.db.get_value("Sales Order", self.name, "modified")
		date_diff = frappe.db.sql("select TIMEDIFF('%s', '%s')" %
			( mod_db, cstr(self.modified)))
		if date_diff and date_diff[0][0]:
			msgprint("%s: %s has been modified after you have opened. Please Refresh"
				% (self.doctype, self.name), raise_exception=1)

	def stop_sales_order(self):
		self.check_modified_date()
		self.update_stock_ledger(-1)
		frappe.db.set(self, 'status', 'Stopped')
		msgprint("""%s: %s has been Stopped. To make transactions against this Sales Order
			you need to Unstop it.""" % (self.doctype, self.name))

	def unstop_sales_order(self):
		self.check_modified_date()
		self.update_stock_ledger(1)
		frappe.db.set(self, 'status', 'Submitted')
		msgprint("%s: %s has been Unstopped" % (self.doctype, self.name))


	def update_stock_ledger(self, update_stock):
		from erpnext.stock.utils import update_bin
		for d in self.get_item_list():
			if frappe.db.get_value("Item", d['item_code'], "is_stock_item") == "Yes":
				args = {
					"item_code": d['item_code'],
					"warehouse": d['reserved_warehouse'],
					"reserved_qty": flt(update_stock) * flt(d['reserved_qty']),
					"posting_date": self.transaction_date,
					"voucher_type": self.doctype,
					"voucher_no": self.name,
					"is_amended": self.amended_from and 'Yes' or 'No'
				}
				update_bin(args)

	def on_update(self):
		pass

	def get_portal_page(self):
		return "order" if self.docstatus==1 else None

def set_missing_values(source, target):
	doc = frappe.get_doc(target)
	doc.run_method("onload_post_render")

@frappe.whitelist()
def make_material_request(source_name, target_doc=None):
	def postprocess(source, doc):
		doc.material_request_type = "Purchase"

	doc = get_mapped_doc("Sales Order", source_name, {
		"Sales Order": {
			"doctype": "Material Request",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Order Item": {
			"doctype": "Material Request Item",
			"field_map": {
				"parent": "sales_order_no",
				"stock_uom": "uom"
			}
		}
	}, target_doc, postprocess)

	return doc

@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None):
	def update_item(source, target, source_parent):
		target.base_amount = (flt(source.qty) - flt(source.delivered_qty)) * flt(source.base_rate)
		target.amount = (flt(source.qty) - flt(source.delivered_qty)) * flt(source.rate)
		target.qty = flt(source.qty) - flt(source.delivered_qty)


	doclist = get_mapped_doc("Sales Order", source_name, {
		"Sales Order": {
			"doctype": "Delivery Note",
			"field_map": {
				"shipping_address": "address_display",
				"shipping_address_name": "party_address",
			},
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Order Item": {
			"doctype": "Delivery Note Item",
			"field_map": {
				"rate": "rate",
				"name": "prevdoc_detail_docname",
				"parent": "against_sales_order",
			},
			"postprocess": update_item,
			"condition": lambda doc: doc.delivered_qty < doc.qty
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"add_if_empty": True
		}
	}, target_doc, set_missing_values)

	return doclist

@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):
	def set_missing_values(source, target):
		doc = frappe.get_doc(target)
		doc.is_pos = 0
		doc.run_method("onload_post_render")

	def update_item(source, target, source_parent):
		target.amount = flt(source.amount) - flt(source.billed_amt)
		target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = source.rate and target.amount / flt(source.rate) or obj.qty

	doclist = get_mapped_doc("Sales Order", source_name, {
		"Sales Order": {
			"doctype": "Sales Invoice",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Order Item": {
			"doctype": "Sales Invoice Item",
			"field_map": {
				"name": "so_detail",
				"parent": "sales_order",
			},
			"postprocess": update_item,
			"condition": lambda doc: doc.base_amount==0 or doc.billed_amt < doc.amount
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"add_if_empty": True
		}
	}, target_doc, set_missing_values)

	return doclist

@frappe.whitelist()
def make_maintenance_schedule(source_name, target_doc=None):
	maint_schedule = frappe.db.sql("""select t1.name
		from `tabMaintenance Schedule` t1, `tabMaintenance Schedule Item` t2
		where t2.parent=t1.name and t2.prevdoc_docname=%s and t1.docstatus=1""", source_name)

	if not maint_schedule:
		doclist = get_mapped_doc("Sales Order", source_name, {
			"Sales Order": {
				"doctype": "Maintenance Schedule",
				"field_map": {
					"name": "sales_order_no"
				},
				"validation": {
					"docstatus": ["=", 1]
				}
			},
			"Sales Order Item": {
				"doctype": "Maintenance Schedule Item",
				"field_map": {
					"parent": "prevdoc_docname"
				},
				"add_if_empty": True
			}
		}, target_doc)

		return doclist

@frappe.whitelist()
def make_maintenance_visit(source_name, target_doc=None):
	visit = frappe.db.sql("""select t1.name
		from `tabMaintenance Visit` t1, `tabMaintenance Visit Purpose` t2
		where t2.parent=t1.name and t2.prevdoc_docname=%s
		and t1.docstatus=1 and t1.completion_status='Fully Completed'""", source_name)

	if not visit:
		doclist = get_mapped_doc("Sales Order", source_name, {
			"Sales Order": {
				"doctype": "Maintenance Visit",
				"field_map": {
					"name": "sales_order_no"
				},
				"validation": {
					"docstatus": ["=", 1]
				}
			},
			"Sales Order Item": {
				"doctype": "Maintenance Visit Purpose",
				"field_map": {
					"parent": "prevdoc_docname",
					"parenttype": "prevdoc_doctype"
				},
				"add_if_empty": True
			}
		}, target_doc)

		return doclist
