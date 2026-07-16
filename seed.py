"""
Seeds LoadFlow with a demo Broker org, Carrier org, Shipper, roles, staff,
a compliance record, and one sample load — so judges can log in and see a
populated app immediately instead of an empty database.

Run with:  python seed.py
"""
from datetime import datetime, timedelta
from app.database import SessionLocal, Base, engine
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()


def get_or_create_org(name, type_):
    org = db.query(models.Org).filter(models.Org.name == name, models.Org.type == type_).first()
    if org:
        return org
    org = models.Org(name=name, type=type_)
    db.add(org)
    db.flush()
    return org


def get_or_create_user(email, **kwargs):
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
        return user
    user = models.User(email=email, **kwargs)
    db.add(user)
    db.flush()
    return user


print("Seeding LoadFlow demo data...")

# --- Broker org ---
broker_org = get_or_create_org("Summit Freight Brokerage", "broker")
broker_admin_role = db.query(models.Role).filter(models.Role.org_id == broker_org.id, models.Role.name == "Admin").first()
if not broker_admin_role:
    broker_admin_role = models.Role(org_id=broker_org.id, name="Admin", permissions=models.PERMISSION_CATALOG)
    db.add(broker_admin_role)
    db.flush()

dispatcher_role = db.query(models.Role).filter(models.Role.org_id == broker_org.id, models.Role.name == "Dispatcher").first()
if not dispatcher_role:
    dispatcher_role = models.Role(org_id=broker_org.id, name="Dispatcher",
                                   permissions=["load.create", "load.assign_carrier", "rate.confirm",
                                                "load.update_status"])
    db.add(dispatcher_role)
    db.flush()

ops_lead_role = db.query(models.Role).filter(models.Role.org_id == broker_org.id, models.Role.name == "Ops Lead").first()
if not ops_lead_role:
    ops_lead_role = models.Role(org_id=broker_org.id, name="Ops Lead",
                                 permissions=["load.create", "load.assign_carrier", "rate.confirm",
                                              "load.update_status", "load.override_compliance_flag", "staff.manage"])
    db.add(ops_lead_role)
    db.flush()

broker_admin = get_or_create_user(
    "admin@summitfreight.com", hashed_password=hash_password("password123"),
    account_type="broker", org_id=broker_org.id, role_id=broker_admin_role.id,
    is_admin=True, full_name="Alice Summit")

dispatcher_user = get_or_create_user(
    "dispatcher@summitfreight.com", hashed_password=hash_password("password123"),
    account_type="broker", org_id=broker_org.id, role_id=dispatcher_role.id,
    is_admin=False, full_name="Dana Dispatcher")

# --- Carrier org ---
carrier_org = get_or_create_org("Ironhide Trucking Co", "carrier")
carrier_admin_role = db.query(models.Role).filter(models.Role.org_id == carrier_org.id, models.Role.name == "Admin").first()
if not carrier_admin_role:
    carrier_admin_role = models.Role(org_id=carrier_org.id, name="Admin", permissions=models.PERMISSION_CATALOG)
    db.add(carrier_admin_role)
    db.flush()

driver_role = db.query(models.Role).filter(models.Role.org_id == carrier_org.id, models.Role.name == "Driver").first()
if not driver_role:
    driver_role = models.Role(org_id=carrier_org.id, name="Driver",
                               permissions=["load.update_status", "pod.upload"])
    db.add(driver_role)
    db.flush()

carrier_dispatch_role = db.query(models.Role).filter(models.Role.org_id == carrier_org.id,
                                                       models.Role.name == "Carrier Dispatch").first()
if not carrier_dispatch_role:
    carrier_dispatch_role = models.Role(org_id=carrier_org.id, name="Carrier Dispatch",
                                         permissions=["load.accept_decline", "load.update_status"])
    db.add(carrier_dispatch_role)
    db.flush()

carrier_admin = get_or_create_user(
    "admin@ironhidetrucking.com", hashed_password=hash_password("password123"),
    account_type="carrier", org_id=carrier_org.id, role_id=carrier_admin_role.id,
    is_admin=True, full_name="Ivan Ironhide")

driver_user = get_or_create_user(
    "driver@ironhidetrucking.com", hashed_password=hash_password("password123"),
    account_type="carrier", org_id=carrier_org.id, role_id=driver_role.id,
    is_admin=False, full_name="Dave Driver")

# --- Compliance record (compliant) ---
compliance = db.query(models.ComplianceRecord).filter(models.ComplianceRecord.carrier_org_id == carrier_org.id).first()
if not compliance:
    compliance = models.ComplianceRecord(
        carrier_org_id=carrier_org.id,
        insurance_expiry=datetime.utcnow() + timedelta(days=180),
        authority_status="active",
        approved_equipment=["Dry Van", "Reefer"],
        approved_commodities=["General", "Frozen"],
    )
    db.add(compliance)

# --- A second, non-compliant carrier for demoing the auto-flag ---
risky_org = get_or_create_org("Fly-By-Night Logistics", "carrier")
risky_admin_role = db.query(models.Role).filter(models.Role.org_id == risky_org.id, models.Role.name == "Admin").first()
if not risky_admin_role:
    risky_admin_role = models.Role(org_id=risky_org.id, name="Admin", permissions=models.PERMISSION_CATALOG)
    db.add(risky_admin_role)
    db.flush()
risky_admin = get_or_create_user(
    "admin@flybynight.com", hashed_password=hash_password("password123"),
    account_type="carrier", org_id=risky_org.id, role_id=risky_admin_role.id,
    is_admin=True, full_name="Rick Risky")
risky_compliance = db.query(models.ComplianceRecord).filter(models.ComplianceRecord.carrier_org_id == risky_org.id).first()
if not risky_compliance:
    risky_compliance = models.ComplianceRecord(
        carrier_org_id=risky_org.id,
        insurance_expiry=datetime.utcnow() - timedelta(days=10),  # EXPIRED on purpose
        authority_status="inactive",
        approved_equipment=["Dry Van"],
        approved_commodities=["General"],
    )
    db.add(risky_compliance)

# --- Shipper ---
shipper = get_or_create_user(
    "shipper@acmegoods.com", hashed_password=hash_password("password123"),
    account_type="shipper", org_id=None, role_id=None, is_admin=False,
    full_name="Sam Shipper", company_name="Acme Goods Inc")

db.flush()

# --- Sample load ---
existing_load = db.query(models.Load).filter(models.Load.origin == "Chicago, IL").first()
if not existing_load:
    load = models.Load(
        broker_org_id=broker_org.id,
        shipper_id=shipper.id,
        origin="Chicago, IL",
        destination="Dallas, TX",
        equipment_type="Dry Van",
        commodity_type="General",
        status="Posted",
    )
    db.add(load)
    db.flush()
    db.add(models.LoadStatusHistory(load_id=load.id, from_status=None, to_status="Posted",
                                     changed_by_user_id=broker_admin.id, note="Seeded demo load"))

db.commit()
db.close()

print("""
Seed complete. Demo logins (password: password123):
  Broker Admin       admin@summitfreight.com
  Broker Dispatcher  dispatcher@summitfreight.com
  Carrier Admin      admin@ironhidetrucking.com    (compliant carrier: Ironhide Trucking Co)
  Carrier Driver     driver@ironhidetrucking.com
  Carrier Admin      admin@flybynight.com          (NON-compliant carrier — expired insurance/authority)
  Shipper            shipper@acmegoods.com

Try: log in as the broker admin, assign 'Fly-By-Night Logistics' to the
seeded Chicago->Dallas load, and watch the compliance auto-flag block
progression until you either fix their record or override it as an Ops Lead.
""")
