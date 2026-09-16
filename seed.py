"""Fictional demonstration data. Not imported from live One Source records."""
from datetime import date, timedelta
from core import *

def seed_demo(c):
    if c.execute('SELECT 1 FROM parties').fetchone(): return
    user=row(c,"SELECT * FROM users WHERE username='admin'")
    def run(action,**kw): return command(c,user,dict(action=action,**kw))
    def create(entity,**kw): return run('create',entity=entity,**kw)['id']
    def dt(n=0): return (date.today()+timedelta(days=n)).isoformat()
    set_setting(c,'demo',True)
    set_setting(c,'tagline','The operating system for every ceiling project.')
    cust=create('parties',name='Aster Workspaces (DEMO)',type='Customer',email='projects@example.com',phone='',state='29',address='Bengaluru - fictional demo account',credit_days=30)
    cust2=create('parties',name='Meridian Interiors (DEMO)',type='Customer',email='accounts@example.com',state='29',credit_days=45)
    cust3=create('parties',name='Cobalt Technology Park (DEMO)',type='Customer',state='33',credit_days=30)
    supplier=create('parties',name='Acoustic Materials Co. (DEMO)',type='Supplier',state='29',credit_days=30)
    labour=create('parties',name='Precision Site Services (DEMO)',type='Supplier',state='29',credit_days=15)
    wh2=create('warehouses',name='Bengaluru Site Store',city='Bengaluru')
    item_specs=[
        ('MF-6060','Mineral fibre tile 600 x 600','Modular ceiling','Stock','NOS','',520,370,18,300),
        ('OP-1260','Acoustic panel 1200 x 600','Acoustic panels','Stock','NOS','',972,690,18,150),
        ('GR-T24','T24 main runner - 3.6 m','Grid systems','Stock','NOS','',285,195,18,200),
        ('GY-12MM','Gypsum board 12.5 mm','Gypsum ceiling','Stock','NOS','',430,310,18,100),
        ('PET-12','PET acoustic panel 12 mm','Acoustic panels','Stock','NOS','',1850,1240,18,40),
        ('INST-GRID','Modular ceiling installation','Installation','Service','SQM','',195,120,18,0),
        ('INST-GYP','Gypsum ceiling installation','Installation','Service','SQM','',420,260,18,0),
        ('LAB-SUB','Subcontract ceiling services','Subcontract','Service','JOB','',0,18000,18,0),
    ]
    items=[]
    for sku,name,cat,kind,uom,hsn,sell,buy,gst,reorder in item_specs:
        items.append(create('items',sku=sku,name=name,category=cat,kind=kind,uom=uom,hsn=hsn,sell_rate=sell,buy_rate=buy,gst_rate=gst,reorder=reorder))
    p1=create('projects',code='OS-D01',name='Aster | North Campus',client_id=cust,city='Bengaluru',scope='Supply + installation',budget=1250000,area=7200,start_date=dt(-45),target_date=dt(21),status='Active',owner='Project Lead - North',notes='DEMO: modular grid, acoustic panels and gypsum ceilings.')
    p2=create('projects',code='OS-D02',name='Meridian | Innovation Centre',client_id=cust2,city='Bengaluru',scope='Supply + installation',budget=680000,area=3800,start_date=dt(-30),target_date=dt(12),status='Active',owner='Project Lead - South',notes='DEMO: coordination with MEP before ceiling closure.')
    p3=create('projects',code='OS-D03',name='Cobalt | Chennai Office',client_id=cust3,city='Chennai',scope='Supply only',budget=450000,area=2100,start_date=dt(-4),target_date=dt(35),status='Planning',owner='Sales Lead',notes='DEMO: procurement planning. Interstate tax selection requires review.')
    run('manual_journal',date=dt(-60),memo='DEMO opening bank and capital',lines=[dict(account='1000',debit=1800000),dict(account='3000',credit=1800000)])
    for iid,qty,rate in [(items[0],2800,370),(items[1],1300,690),(items[2],800,195),(items[3],75,310),(items[4],24,1240)]:
        run('opening_stock',item_id=iid,warehouse_id=1,qty=qty,rate=rate,date=dt(-55),notes='Fictional opening inventory for demonstration.')
    def document(typ,party,project,lines,day=-40,ref='',tax='intra'):
        return run('create_document',type=typ,party_id=party,project_id=project,date=dt(day),due_date=dt(day+30),reference=ref,tax_mode=tax,place_of_supply='29' if tax=='intra' else '33',lines=[dict(item_id=i,qty=q,rate=r,gst_rate=18) for i,q,r in lines])['id']
    so=document('sales_order',cust,p1,[(items[0],2000,520),(items[2],600,285),(items[5],1500,195)],ref='DEMO-CLIENT-WO-001')
    run('approve_document',id=so)
    sl=doc_lines(c,so)
    run('dispatch',id=so,date=dt(-38),warehouse_id=1,vehicle='DEMO VEHICLE 01',transporter='Demo Logistics',lines=[dict(line_id=sl[0]['id'],qty=1200),dict(line_id=sl[1]['id'],qty=400)])
    inv=run('convert_document',id=so,target='invoice',date=dt(-37),due_date=dt(-7),lines=[dict(line_id=sl[0]['id'],qty=1200),dict(line_id=sl[1]['id'],qty=400),dict(line_id=sl[2]['id'],qty=800)])['id']
    run('post_document',id=inv)
    run('settle',direction='in',document_id=inv,bucket='trade',cash=500000,tds=8000,retention=30000,date=dt(-10),reference='DEMO-BANK-RC001',memo='Partial collection with TDS and retention.')
    so2=document('sales_order',cust2,p2,[(items[1],1000,972),(items[5],700,195)],day=-20,ref='DEMO-CLIENT-WO-002')
    run('approve_document',id=so2); sl2=doc_lines(c,so2)
    run('dispatch',id=so2,date=dt(-18),warehouse_id=1,vehicle='DEMO VEHICLE 02',transporter='Demo Logistics',lines=[dict(line_id=sl2[0]['id'],qty=600)])
    inv2=run('convert_document',id=so2,target='invoice',date=dt(-17),due_date=dt(13),lines=[dict(line_id=sl2[0]['id'],qty=600),dict(line_id=sl2[1]['id'],qty=400)])['id']
    run('post_document',id=inv2)
    run('settle',direction='in',document_id=inv2,bucket='trade',cash=250000,date=dt(-3),reference='DEMO-BANK-RC002')
    ds=rows(c,'SELECT * FROM dispatches ORDER BY id'); run('update',entity='dispatches',id=ds[0]['id'],pod_ref='Signed demo delivery acknowledgement',pod_date=dt(-37))
    po=document('purchase_order',supplier,p1,[(items[0],2000,365),(items[3],500,310)],day=-14,ref='DEMO-REPLENISH-001')
    run('approve_document',id=po); pl=doc_lines(c,po)
    rid=run('receive',id=po,date=dt(-12),warehouse_id=1,reference='DEMO-SUP-DC-01',lines=[dict(line_id=pl[0]['id'],qty=1000),dict(line_id=pl[1]['id'],qty=100)])['id']
    bill=run('bill_receipt',id=rid,date=dt(-12),due_date=dt(18),reference='DEMO-SUP-INV-01')['id']; run('post_document',id=bill)
    run('settle',direction='out',document_id=bill,bucket='trade',cash=150000,date=dt(-5),reference='DEMO-PAY-001')
    svc=document('bill',labour,p2,[(items[7],1,48000)],day=-10,ref='DEMO-SERVICE-01'); run('post_document',id=svc)
    qt=document('quote',cust3,p3,[(items[1],2000,972),(items[2],850,285)],day=-2,ref='DEMO-RFQ-003',tax='inter')
    for company,scope,val,stage,prob,owner,n in [
        ('Aster Phase II (DEMO)','Acoustic baffles + grid ceiling',3400000,'Negotiation',70,'Sales Lead',1),
        ('Cobalt Chennai (DEMO)','Acoustic panel supply',2186250,'Quoted',50,'Sales Lead',2),
        ('Vertex Business Hub (DEMO)','Gypsum + modular ceiling SITC',4750000,'Qualified',35,'Business Development',-1),
        ('Orion Healthcare (DEMO)','Hygienic ceiling supply',1250000,'New',15,'Business Development',3),
        ('Meridian Expansion (DEMO)','PET panels and installation',1850000,'Negotiation',75,'Sales Lead',0)]:
        create('leads',company=company,scope=scope,contact='Demo contact',phone='',value=val,stage=stage,probability=prob,owner=owner,next_date=dt(n),notes='Fictional opportunity for product demonstration.')
    for project,area,trade,status,blocker,n in [(p1,'Level 4 - East wing','MEP / sprinkler','Blocked','MEP testing incomplete',-2),(p1,'Level 3 - Meeting rooms','Grid closure','Cleared','',1),(p2,'Level 2 - Open office','HVAC coordination','Awaiting clearance','Linear grille dimensions',-1),(p2,'Level 1 - Reception','Gypsum finishing','Completed','',-5)]:
        create('clearances',project_id=project,area=area,trade=trade,status=status,blocked_by=blocker,required_date=dt(n),owner='Site Coordinator',notes='DEMO: record clearance before manpower mobilisation.')
    for n,project,team,h,status,out in [(-3,p1,'North installation crew',12,'Working',180),(-2,p1,'North installation crew',12,'Idle',0),(-1,p2,'South installation crew',8,'Working',105),(0,p1,'North installation crew',12,'Working',165)]:
        lid=create('site_logs',project_id=project,date=dt(n),team=team,headcount=h,hours=8,daily_rate=950,status=status,output=out,uom='SQM',notes='DEMO daily manpower entry. Daily cost, not statutory payroll.')
        if n<0: run('post_labour',id=lid)
    for title,typ,value,status,project in [('Ceiling specification upgrade','Rate difference',125000,'Submitted',p1),('MEP damage - tile replacement','Rework',65000,'Raised',p2),('Additional meeting-room ceiling','Variation',210000,'Approved',p1)]:
        create('changes',project_id=project,title=title,type=typ,value=value,status=status,owner='Commercial Team',raised_date=dt(-5),reference='DEMO-CHANGE',notes='No automatic revenue recognition; raise an approved order for billing.')
    for title,owner,due,priority,project in [('Collect overdue Aster invoice','Accounts Team',-1,'High',p1),('Obtain MEP clearance before mobilisation','Site Coordinator',0,'High',p1),('Get revised work order for rate difference','Commercial Team',1,'High',p1),('Collect signed POD for Meridian dispatch','Dispatch Team',0,'Medium',p2),('Confirm balance PO delivery','Purchase Team',2,'Medium',p1),('Follow up on Cobalt quotation','Sales Lead',1,'Medium',p3)]:
        create('tasks',title=title,project_id=project,owner=owner,due_date=dt(due),priority=priority,status='Open',notes='Fictional demo task.')
    run('manual_journal',date=dt(-2),project_id=p1,memo='DEMO project transport expense',lines=[dict(account='5300',debit=18500),dict(account='1000',credit=18500)])

    run('commercial_record',entity='measurements',project_id=p1,invoice_id=inv,date=dt(-37),zone='Level 3 - East wing',description='Modular ceiling installation',uom='SQM',executed=1000,measured=950,certified=800,rate=195,status='Billed',owner='Commercial Team',reference='DEMO-RA-001',notes='Fictional measurement: certified quantity linked to posted invoice.')
    run('commercial_record',entity='measurements',project_id=p2,date=dt(-3),zone='Level 2 - Open office',description='Modular ceiling installation',uom='SQM',executed=300,measured=250,certified=0,rate=195,status='Submitted',owner='Site Coordinator',reference='DEMO-RA-002',notes='Fictional measurement pending client certification.')
    run('commercial_record',entity='credit_instruments',project_id=p1,party_id=cust,reference='DEMO-LC-001',bank='Demonstration Bank',issue_date=dt(-20),due_date=dt(8),face_value=650000,claim_value=500000,accepted_value=400000,status='Accepted',owner='Accounts Team',notes='Fictional LC tracker. Cash receipt and finance charges must be posted separately.')
