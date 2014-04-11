// Copyright (c) 2013, Web Notes Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.cscript.tname = "Purchase Receipt Item";
cur_frm.cscript.fname = "purchase_receipt_details";
cur_frm.cscript.other_fname = "other_charges";

{% include 'buying/doctype/purchase_common/purchase_common.js' %};
{% include 'accounts/doctype/purchase_taxes_and_charges_master/purchase_taxes_and_charges_master.js' %}
{% include 'utilities/doctype/sms_control/sms_control.js' %}
{% include 'accounts/doctype/sales_invoice/pos.js' %}

frappe.provide("erpnext.stock");
erpnext.stock.PurchaseReceiptController = erpnext.buying.BuyingController.extend({
	refresh: function() {
		this._super();

		if(this.frm.doc.docstatus == 1) {
			if(!this.frm.doc.__billing_complete) {
				cur_frm.add_custom_button(frappe._('Make Purchase Invoice'),
					this.make_purchase_invoice);
			}
			cur_frm.add_custom_button('Send SMS', cur_frm.cscript.send_sms);

			this.show_stock_ledger();
			this.show_general_ledger();
		} else {
			cur_frm.add_custom_button(frappe._(frappe._('From Purchase Order')),
				function() {
					frappe.model.map_current_doc({
						method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
						source_doctype: "Purchase Order",
						get_query_filters: {
							party: cur_frm.doc.party || undefined,
							docstatus: 1,
							status: ["!=", "Stopped"],
							per_received: ["<", 99.99],
							company: cur_frm.doc.company
						}
					})
				});
		}

		if(frappe.boot.sysdefaults.country == 'India') {
			unhide_field(['challan_no', 'challan_date']);
		}
	},

	received_qty: function(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["qty", "received_qty"]);

		item.qty = (item.qty < item.received_qty) ? item.qty : item.received_qty;
		this.qty(doc, cdt, cdn);
	},

	qty: function(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["qty", "received_qty"]);

		if(!(item.received_qty || item.rejected_qty) && item.qty) {
			item.received_qty = item.qty;
		}

		if(item.qty > item.received_qty) {
			msgprint(frappe._("Error") + ": " + frappe._(frappe.meta.get_label(item.doctype, "qty", item.name))
				+ " > " + frappe._(frappe.meta.get_label(item.doctype, "received_qty", item.name)));
			item.qty = item.rejected_qty = 0.0;
		} else {
			item.rejected_qty = flt(item.received_qty - item.qty, precision("rejected_qty", item));
		}

		this._super();
	},

	rejected_qty: function(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["received_qty", "rejected_qty"]);

		if(item.rejected_qty > item.received_qty) {
			msgprint(frappe._("Error") + ": " +
				frappe._(frappe.meta.get_label(item.doctype, "rejected_qty", item.name))
				+ " > " + frappe._(frappe.meta.get_label(item.doctype, "received_qty", item.name)));
			item.qty = item.rejected_qty = 0.0;
		} else {
			item.qty = flt(item.received_qty - item.rejected_qty, precision("qty", item));
		}

		this.qty(doc, cdt, cdn);
	},

	make_purchase_invoice: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
			source_name: cur_frm.doc.name
		})
	},

	tc_name: function() {
		this.get_terms();
	},

});

// for backward compatibility: combine new and previous states
$.extend(cur_frm.cscript, new erpnext.stock.PurchaseReceiptController({frm: cur_frm}));

cur_frm.fields_dict['party_address'].get_query = function(doc, cdt, cdn) {
	return {
		filters: { 'party': doc.party}
	}
}

cur_frm.fields_dict['contact_person'].get_query = function(doc, cdt, cdn) {
	return {
		filters: { 'party': doc.party }
	}
}

cur_frm.fields_dict['purchase_receipt_details'].grid.get_field('project_name').get_query = function(doc, cdt, cdn) {
	return {
		filters: [
			['Project', 'status', 'not in', 'Completed, Cancelled']
		]
	}
}

cur_frm.fields_dict['purchase_receipt_details'].grid.get_field('batch_no').get_query= function(doc, cdt, cdn) {
	var d = locals[cdt][cdn];
	if(d.item_code) {
		return {
			filters: {'item': d.item_code}
		}
	}
	else
		msgprint(frappe._("Please enter Item Code."));
}

cur_frm.cscript.select_print_heading = function(doc, cdt, cdn) {
	if(doc.select_print_heading)
		cur_frm.pformat.print_heading = doc.select_print_heading;
	else
		cur_frm.pformat.print_heading = "Purchase Receipt";
}

cur_frm.fields_dict['select_print_heading'].get_query = function(doc, cdt, cdn) {
	return {
		filters: [
			['Print Heading', 'docstatus', '!=', '2']
		]
	}
}

cur_frm.fields_dict.purchase_receipt_details.grid.get_field("qa_no").get_query = function(doc) {
	return {
		filters: {
			'docstatus': 1
		}
	}
}

cur_frm.cscript.on_submit = function(doc, cdt, cdn) {
	if(cint(frappe.boot.notification_settings.purchase_receipt))
		cur_frm.email_doc(frappe.boot.notification_settings.purchase_receipt_message);
}
