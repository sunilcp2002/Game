# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from ast import literal_eval
from odoo.tools import float_compare, float_round, float_is_zero, pycompat


class StockQuantInherit(models.Model):
	_inherit = 'stock.quant'

	unit_price = fields.Float('Cost Price', readonly=False)
	inv_cost = fields.Boolean(related="company_id.inv_cost")

	@api.model_create_multi
	def create(self, vals):
		""" Override to handle the "inventory mode" and create a quant as
		superuser the conditions are met.
		"""
		if self._is_inventory_mode() and any(f in vals for f in ['inventory_quantity', 'inventory_quantity_auto_apply']):
			allowed_fields = self._get_inventory_fields_create()
			if any(field for field in vals.keys() if field not in allowed_fields):
				raise UserError(_("Quant's creation is restricted, you can't do this operation."))

			inventory_quantity = vals.pop('inventory_quantity', False) or vals.pop(
				'inventory_quantity_auto_apply', False) or 0
			# Create an empty quant or write on a similar one.
			product = self.env['product.product'].browse(vals['product_id'])
			location = self.env['stock.location'].browse(vals['location_id'])
			lot_id = self.env['stock.lot'].browse(vals.get('lot_id'))
			package_id = self.env['stock.quant.package'].browse(vals.get('package_id'))
			owner_id = self.env['res.partner'].browse(vals.get('owner_id'))
			quant = self._gather(product, location, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=True)
			unit_price = self.env['stock.quant'].browse(vals.get(tuple('unit_price')))

			if quant:
				quant = quant[0].sudo()
			else:
				quant = self.sudo().create(vals)
			# Set the `inventory_quantity` field to create the necessary move.
			quant.inventory_quantity = inventory_quantity
			quant.user_id = vals.get('user_id', self.env.user.id)
			quant.inventory_date = fields.Date.today()
			if vals.get('unit_price'):
				quant.unit_price = vals.pop('unit_price')
			return quant
		res = super(StockQuantInherit, self).create(vals)
		if self._is_inventory_mode():
			res._check_company()
		return res


	def update_standard_price(self):
	
		for quant in self:
			if quant.product_id.cost_method == 'average' and quant.unit_price > 0.00:
				total_value_incoming_shipment = quant.product_id.standard_price * quant.quantity
				total_value_invoice_line = quant.unit_price * quant.quantity
				if (quant.quantity + quant.quantity) != 0:
					new_average_price = (total_value_incoming_shipment + total_value_invoice_line) / (quant.quantity + quant.quantity)
					for i in quant.product_id.company_id.currency_id:
						new_average_price = i.round(new_average_price)
					quant.product_id.standard_price = new_average_price

	@api.model
	def _get_inventory_fields_create(self):
		""" Returns a list of fields user can edit when he want to create a quant in `inventory_mode`.
		"""
		res = super(StockQuantInherit,self)._get_inventory_fields_create()
		res += ['unit_price']
		return res

	@api.model
	def _get_inventory_fields_write(self):
		""" Returns a list of fields user can edit when he want to edit a quant in `inventory_mode`.
		"""
		res = super(StockQuantInherit,self)._get_inventory_fields_write()
		res += ['unit_price']
		return res

	@api.model
	def default_get(self,fields):
		res = super(StockQuantInherit, self).default_get(fields)
		if 'unit_price' in fields and res.get('product_id'):
			res['unit_price'] = self.env['product.product'].browse(res['product_id']).standard_price
		return res

	def _get_inventory_move_values(self, qty, location_id, location_dest_id, package_id=False, package_dest_id=False):
		self.ensure_one()
		res = super(StockQuantInherit,self)._get_inventory_move_values(qty, location_id, location_dest_id, package_id, package_dest_id)
		if fields.Float.is_zero(qty, 0, precision_rounding=self.product_uom_id.rounding):
			name = _('Product Quantity Confirmed')
		else:
			name = _('Product Quantity Updated')
		res.update({
		  'price_unit':self.unit_price
		})

		return res

	@api.onchange('product_id')
	def _onchange_location_or_product_id(self):
		if self.product_id:
			self.unit_price = self.product_id.standard_price
		return super(StockQuantInherit, self)._onchange_location_or_product_id()
