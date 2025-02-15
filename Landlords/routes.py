from flask import Blueprint, jsonify, render_template, flash, url_for, redirect, request, session, abort, json
from flask_login import login_user, login_required, fresh_login_required, logout_user, current_user
from models import db, Landlord, Tenant, Unit, Properties, Extras, Verification, Transaction, Members, Complaints, Extra_service, Invoice, Messages
from .form import *
from modules import generate_invoice, send_sms, send_email, send_chat, check_reservation_expiry, assign_tenant_unit, revoke_tenant_access, rent_transaction
import random, os
from datetime import date, datetime

landlords = Blueprint("landlord", __name__)
SECRET_KEY = os.environ['Hms_secret_key']
google_maps =os.environ["Google_maps"]
today = date.today()

@landlords.route("/change-dates", methods=["POST"])
@login_required
@fresh_login_required
def change_date():
  data = json.loads(request.get_data('data'))
  session["this_month"] = data
  return redirect(url_for('landlord.landlord_dashboard'))

@landlords.route("/landlord_registration", methods=["POST", "GET"])
def landlord():
  form = landlord_form()
  try:
    if form.validate_on_submit():
      new_landlord = Landlord(
        first_name=form.first_name.data,
        second_name=form.second_name.data,
        last_name=form.last_name.data,
        email=form.email_address.data,
        phone=form.phone_number.data,
        username=form.username.data,
        date=datetime.now(),
        active="True",
        landlord_id=random.randint(100000, 999999),
        account_type="Landlord",
        passwords=form.password.data,
      )
      db.session.add(new_landlord)
      db.session.commit()
      message = {
        'receiver': new_landlord.email,
        'subject': 'Account Created Successfully',
        'body': f'Congratulations! {new_landlord.first_name} {new_landlord.second_name} you have successfully created your landlord account. \nLogin to your dashboard using your Landlord ID {new_landlord.landlord_id} and your password. \nDo not share your Landlord ID with anyone other than your tenants only when they register.'
      }
      # send_sms(message)
      send_email(**message)
      flash(f"Account created successfully", category="success")
      return redirect(url_for("landlord.Landlord_login"))

    if form.errors != {}:
      for err_msg in form.errors.values():
        flash(f"There was an error creating the account: {err_msg}",category="danger")
  except:
    flash(f"Something went wrong. Check your form and try again", category="danger")

  return render_template("landlord.html", form=form)

@landlords.route("/landlord_login", methods=["POST", "GET"])
def Landlord_login():
  form = landlord_login_form()
  if form.validate_on_submit():
    new_landlord = Landlord.query.filter_by(landlord_id=form.landlord_id.data).first()
    if new_landlord and new_landlord.check_password_correction(attempted_password=form.password.data):
      login_user(new_landlord, remember=True)
      flash(f"Login successfull, welcome {new_landlord.first_name}",category="success")
      next = request.args.get("next")
      return redirect(next or url_for("landlord.landlord_dashboard"))
    elif new_landlord == None:
      flash(f"No user with that Landlord ID", category="danger")
      return redirect(url_for("landlord.Landlord_login"))
    else:
      flash(f"Invalid credentials", category="danger")
      return redirect(url_for("landlord.Landlord_login"))

  return render_template("landlord_login.html", form=form)

def invoice():
  units = Unit.query.filter(Unit.landlord == current_user.id, Unit.tenant != None).all()
  if units:
    for unit in units:
      generate_invoice(unit.id, unit.tenant, unit.rent_amount)

  return render_template("base_landlord.html", units=units)

@landlords.route("/Landlord_dashboard", methods=["POST", "GET"])
@fresh_login_required
@login_required
def landlord_dashboard():
  if current_user.account_type != "Landlord":
    abort(403)
  properties = db.session.query(Properties).filter(current_user.id == Properties.owner).all()
  tenants = db.session.query(Tenant).filter(Tenant.landlord == current_user.id).all()
  todays_time = datetime.now().strftime("%d/%m/%Y")
  if session.get("this_month"):
    this_month = datetime.strptime(session["this_month"], '%Y-%m-%d').date()
  else:
    this_month = today
  expenses = 0
  properties_count = db.session.query(Properties).filter(Properties.owner == current_user.id).count()
  extras = Extras.query.all()
  active_extras = Extra_service.query.filter(Extra_service.landlord == current_user.id).all()
  units = Unit.query.filter(Unit.landlord == current_user.id, Unit.tenant != None).all()
  invoices = Invoice.query.filter_by(status="Cleared").all()
  invoice()

  return render_template("new_dash.html",properties=properties, tenants=tenants,properties_count=properties_count, expenses=expenses, extras=extras, todays_time=todays_time, active_extras=active_extras, this_month=this_month, units=units, invoices=invoices)

@landlords.route("/approve-verification/<int:verification_id>")
@fresh_login_required
@login_required
def approve_verification(verification_id):
  if current_user.account_type != "Landlord":
    abort(403)
  verification = Verification.query.get(verification_id)
  tenant = Tenant.query.filter_by(id=verification.tenant).first()
  unit = Unit.query.filter_by(tenant=tenant.id).first()
  invoice = Invoice.query.filter(Invoice.unit == unit.id, Invoice.status == "Active").first()
  if verification and invoice:
    verification.status = 'approved'
    new_transaction = {
      'tenant': tenant.id,
      'landlord': current_user.id,
      'Property': tenant.properties,
      'Unit': unit.id,
      'invoice': invoice.id,
      'origin': "Mpesa"
    }
    rent_transaction(**new_transaction)
    if not invoice:
      flash(f"The tenant has already paid this month's rent", category="danger")
      verification.status = "denied"
      db.session.commit()
    else:
      invoice.date_closed = datetime.now()
      invoice.month_created = datetime.now()
      invoice.status = "Cleared"
      db.session.commit()
      message = {
        'receiver': [current_user.email, tenant.email],
        'subject': 'RENT PAYMENT',
        'body': f'Confirmed! rental payment of amount {unit.rent_amount} paid successfully on {datetime.now().strftime("%d/%m/%Y")}.'
      }
      # send_sms(message)
      send_email(**message)
      flash(f"Rent payment approved", category="success")
      return redirect(url_for('landlord.landlord_dashboard')) 
  else:
    verification.status = 'failed'
    db.session.commit()
    flash(f"Failed to approve the mpesa transaction.", category=
    "danger")
  return redirect(url_for('landlord.landlord_dashboard'))

@landlords.route("/deny-verification/<int:verification_id>")
@fresh_login_required
@login_required
def deny_verification(verification_id):
  if current_user.account_type != "Landlord":
    abort(403)
  verification = Verification.query.get(verification_id)
  if verification.status == "denied":
    flash(f"Rent payment already denied", category="danger")
  else:
    verification.status = 'denied'
    db.session.commit()
    flash(f"Rent payment denied", category="success")

  return redirect(url_for('landlord.landlord_dashboard'))

@landlords.route("/property_information/<int:property_id>", methods=["POST","GET"])
@fresh_login_required
@login_required
def property_information(property_id):
  if current_user.account_type != "Landlord":
    abort(403)
  try:
    properties = db.session.query(Properties).filter(current_user.id == Properties.owner).all()
    propertiez = Properties.query.filter_by(id=property_id).first()
    if propertiez.owner != current_user.id:
      flash(f"Unknown Property", category="info")
      return redirect(url_for("landlord.landlord_dashboard"))
    users = Members.query.all()
    landlord_user = Landlord.query.all()
    tenant_user = Tenant.query.all()
    today_time = datetime.now().strftime("%d/%m/%Y")
    session["property"] = propertiez
    tenants = db.session.query(Tenant).filter(Tenant.properties == propertiez.id).all()
    units = db.session.query(Unit).filter(Unit.Property == propertiez.id).all()
    tenants_count = db.session.query(Tenant).filter(Tenant.properties == propertiez.id).count()
    unit_count = db.session.query(Unit).filter(Unit.Property == propertiez.id).count()
    invoice()
    check_reservation_expiry(propertiez.id)
  except:
    flash(f"Cannot retrieve property information at the moment. Try again later", category="warning")
    return redirect(url_for("landlord.landlord_dashboard"))

  return render_template("property_dashboard.html", propertiez=propertiez,properties=properties,tenants=tenants,units=units,tenants_count=tenants_count,unit_count=unit_count, today_time=today_time,users=users, landlord_user=landlord_user, tenant_user=tenant_user)

@landlords.route("/tenant_details/<int:tenant_id>", methods=["GET", "POST"])
@fresh_login_required
@login_required
def tenant_details(tenant_id):
  if current_user.account_type != "Landlord":
    abort(403)
  today_time = datetime.now().strftime("%d/%m/%Y")
  try:
    tenant = Tenant.query.get(tenant_id)
    tenant_property = Properties.query.filter_by(id=tenant.properties).first()
    if tenant.landlord != current_user.id:
      flash(f"Unknown Tenant ID", category="info")
      return redirect(url_for("landlord.landlord_dashboard"))
    elif tenant.active == "False":
      flash(f"Cannot view tenant details. Tenant is not active", category="danger")
      return redirect(url_for("landlord.property_information", property_id=tenant_property.id))
    complaints = Complaints.query.filter_by(tenant=tenant.id).all()
    transactions = Transaction.query.filter_by(tenant=tenant.id).all()
    units = Unit.query.all()
    tenant_invoices = Invoice.query.filter_by(tenant=tenant.id).all()
    invoice()
  except:
    flash(f"Something went wrong. Try again", category="danger")
    return redirect(url_for("landlord.landlord_dashboard"))

  return render_template("tenant_details.html",tenant=tenant,complaints=complaints,units=units, today_time=today_time, tenant_property=tenant_property, tenant_invoices=tenant_invoices, transactions=transactions)

@landlords.route("/send-message/<int:tenant_id>", methods=["POST","GET"])
@fresh_login_required
@login_required
def send_message(tenant_id):
  tenant = Tenant.query.get(tenant_id)
  messages = Messages.query.filter_by(landlord=current_user.id, tenant=tenant.id).all()
  if request.method == "POST":
    new_message = {
      'landlord': current_user.id,
      'tenant': tenant.id,
      'info': request.form.get("message"),
      'author': current_user.account_type
    }
    send_chat(**new_message)
    return redirect(url_for('landlord.send_message', tenant_id=tenant.id))

  return render_template("message.html", messages=messages, tenant=tenant)

@landlords.route("/assign-tenant-unit/<int:tenant_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def assign_unit_now(tenant_id):
  if current_user.account_type != "Landlord":
    abort(403)
  unit_id = request.form.get("unit-assign")
  previous_url = request.referrer
  tenant = Tenant.query.get(tenant_id)
  this_property = tenant.properties
  assign_tenant_unit(tenant_id, unit_id, this_property, previous_url, current_user.id)
  return redirect(url_for('landlord.tenant_details', tenant_id=tenant_id))

@landlords.route("/revoke-tenant/<int:tenant_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def remove_tenant_now(tenant_id):
  if current_user.account_type != "Landlord":
    abort(403)
  previous_url = request.referrer
  tenant = Tenant.query.get(tenant_id)
  this_property = tenant.properties
  revoke_tenant_access(tenant_id, current_user.id, previous_url)
  message = {
    'receiver': [current_user.email, tenant.email],
    'subject': 'Account Revoked',
    'body': f'Account successfully revoked'
  }
  send_email(**message)
  return redirect(url_for("landlord.property_information", property_id=this_property))

@landlords.route("/property-registration", methods=["POST", "GET"])
@fresh_login_required
@login_required
def property():
  if current_user.account_type != "Landlord":
    abort(403)
  if session.get("property"):
    this_property = session["property"]
  try:
    new_property = Properties(
      name=request.form.get("property_name"),
      address=request.form.get("property-address"),
      address2 =request.form.get("property-address2"),
      floors=request.form.get("property-floors"),
      rooms=request.form.get("property-units"),
      Type=request.form.get("property-type"),
      property_id=random.randint(100000, 999999),
      date=datetime.now(),
      owner=current_user.id,
      status=request.form.get("availability")
    )
    if new_property.owner != current_user.id:
      flash(f"The landlord ID you entered does not match your landlord ID", category="info")
    for prop in current_user.Property:
      if prop.name == new_property.name:
        flash(f"A property with the name {prop.name} already exists", category="danger")
        return redirect(url_for("landlord.property_information", property_id=this_property.id))
    else:
      db.session.add(new_property)
      db.session.commit()
      flash(f"Property {new_property.name}  was created successfully",category="success")
      return redirect(url_for("landlord.property_information", property_id=new_property.id))
  except:
    flash(f"Something went wrong. Try again later", category="danger")
    return redirect(url_for("landlord.property_information", property_id=this_property.id))

@landlords.route("/delete_property/<int:property_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def delete_property(property_id):
  if current_user.account_type != "Landlord":
    abort(403)
  try:
    property = Properties.query.get(property_id)
    if property.tenants or property.unit:
      flash(f"Cannot remove {property.name}.  Some tenants or units are still linked",category="danger")
      return redirect(url_for("landlord.property_information", property_id=property.id))
    elif property.owner != current_user.id:
      flash(f"No property with the name {property.name}",category="danger",)
      return redirect(url_for("landlord.landlord_dashboard"))
    elif property:
      db.session.delete(property)
      db.session.commit()
      flash(f"Property {property.name} has been decommissioned successfully",category="success",)
      return redirect(url_for("landlord.landlord_dashboard"))
    else:
      flash(f"Property {property.name} could not be deleted. Try again",category="danger")
      return redirect(url_for("landlord.property_information", property_id=property.id))
  except:
    flash(f"An error occurred", category="danger")
    return redirect(url_for("landlord.landlord_dashboard"))

@landlords.route("/Landlord_portal/Property_registration/Unit_registration", methods=["POST", "GET"])
@fresh_login_required
@login_required
def unit():
  if current_user.account_type != "Landlord":
    abort(403)
  this_property = session["property"]
  try:
    new_unit = Unit(
      name=request.form.get("unit-name"),
      floor=request.form.get("unit-floor"),
      Type=request.form.get("unit-type"),
      date=datetime.now(),
      unit_id=random.randint(100000, 999999),
      rent_amount=request.form.get("unit-rent"),
      living_space=request.form.get("living-space"),
      balcony_space=request.form.get("veranda"),
      bedrooms = request.form.get("no-of-bedrooms"),
      bathrooms = request.form.get("no-of-bathrooms"),
      air_conditioning = request.form.get("air-conditioning"),
      amenities = request.form.get("furniture"),
      reserved="False",
      Property=Properties.query.filter_by(property_id=request.form.get("property-id")).first().id,
      landlord=Landlord.query.filter_by(id=current_user.id).first().id
    )
    all_units = Unit.query.filter_by(Property=this_property.id).all()
    for unit in all_units:
      unit_exists = db.session.query(Unit).filter(new_unit.name == unit.name).first()
      if unit_exists:
        flash(f"A unit with name {new_unit.name} already exists in {this_property.name}", category="danger")
        return redirect(url_for("landlord.property_information", property_id=this_property.id))
    all_units_count = Unit.query.filter_by(Property=this_property.id).count()
    if all_units_count == this_property.rooms:
      flash(f"Maximum units allowed of this property has been reached", category="warning")
      return redirect(url_for("landlord.property_information", property_id=this_property.id))
    if this_property.Type == "Office":
      new_unit.bedrooms = 0
      new_unit.bathrooms = 0
      db.session.commit()
    if new_unit.Property != this_property.id:
      flash(f"Invalid Property ID", category="danger")
      return redirect(url_for("landlord.property_information", property_id=this_property.id))
    db.session.add(new_unit)
    db.session.commit()
    flash(f"Unit {new_unit.name} - {new_unit.Type} Added successfully",category="success")
    return redirect(url_for("landlord.property_information", property_id=this_property.id))
  except:
    flash(f"Something went wrong. Try again later", category="danger")
    return redirect(url_for("landlord.property_information", property_id=this_property.id))

@landlords.route("/update-property-availability/<int:property_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def update_property_availability(property_id):
  this_property = session["property"]
  Property = Properties.query.get(property_id)
  availability = request.form.get("availability")
  Property.status = availability
  units = Unit.query.filter_by(Property=Property.id, tenant=None).all()
  if availability == "Sale":
    for unit in units:
      unit.rent_amount = unit.rent_amount * 50
  if availability == "Rent":
    for unit in units:
      unit.rent_amount = unit.rent_amount / 50
  db.session.commit()
  flash(f"{Property.name} availability has been updated successfully. The units rent amount have been adjusted", category="success")

  return redirect(url_for("landlord.property_information", property_id=this_property.id))

@landlords.route("/extra-service/<string:extra_type>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def extra_service(extra_type):
  if current_user.account_type != "Landlord":
    abort(403)
  extras = Extras.query.filter_by(title=extra_type).all()
  properties = Properties.query.filter(Properties.owner == current_user.id).all()
  units = Unit.query.filter(Unit.landlord == current_user.id).all()

  return render_template("extra_services.html", extras=extras, extra_type=extra_type, properties=properties, units=units)

@landlords.route("/extra-services/<int:property_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def unit_select(property_id):
  if current_user.account_type != "Landlord":
    abort(403)
  units = Unit.query.filter_by(Property=property_id).all()
  unitsArray = []
  for unit in units:
    unitObj = {}
    unitObj["id"] = unit.id  
    unitObj["name"] = unit.name  
    unitObj["type"] = unit.Type
    unitsArray.append(unitObj)

  return jsonify({'units': unitsArray})

@landlords.route("/extra-service/<int:extra_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def select_extra_service(extra_id):
  if current_user.account_type != "Landlord":
    abort(403)
  data = json.loads(request.get_data('data'))
  Property = Properties.query.filter_by(id=data.get("property")).first()
  extra = Extras.query.filter_by(id=data.get("extra")).first()
  active_extras = Extra_service.query.filter(Extra_service.landlord == current_user.id, Extra_service.status == "Ongoing", Extra_service.extra == extra_id).all()
  if active_extras:
    extra_occupancy(extra_id)
  else:
    try:
      new_service = Extra_service(
        extra_service_id = random.randint(100000, 999999),
        landlord = current_user.id,
        Property = data.get("property"),
        unit = data.get("unit"),
        extra = data.get("extra"),
        date_opened = datetime.now(),
        cost = extra.cost * 5,
        status = "Ongoing"
      )
      db.session.add(new_service)
      db.session.commit()
      extra_occupancy(extra.id)
    except:
      flash(f"Could not dispatch the extra to your property", category="danger")
      return redirect(url_for("landlord.extra_service", extra_type=extra.title))

  return redirect(url_for("landlord.landlord_dashboard"))

@landlords.route("/extra-occupancy/<int:extra_id>", methods=["POST", "GET"])
@fresh_login_required
@login_required
def extra_occupancy(extra_id):
  if current_user.account_type != "Landlord":
    abort(403)
  extra = Extras.query.get(extra_id)
  active_extras = Extra_service.query.filter_by(landlord = current_user.id, status="Ongoing", extra=extra.id).all()
  occupied_extras = []
  for extras in active_extras:
    occupied_extras.append(extras.extra)
  occupyInfo = {}
  occupyInfo["fname"] = extra.first_name 
  occupyInfo["lname"] = extra.last_name
  if extra.id in occupied_extras:
    return jsonify({'message': occupyInfo})
  else:
    return jsonify({'messages': occupyInfo})

@landlords.route("/logout_landlord")
@login_required
def landlord_logout():
  if current_user.account_type != "Landlord":
    abort(403)
  logout_user()
  flash(f"Logged out successfully!", category="success")
  return redirect(url_for("landlord.Landlord_login"))
