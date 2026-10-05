import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import RAW, WORK
import pandas as pd, numpy as np
pd.set_option('display.width',220); pd.set_option('display.max_columns',50); pd.set_option('display.max_colwidth',400)
r=lambda t: pd.read_parquet(WORK/f'{t}.parquet')
tr=r('call_transcripts'); cp=r('complaints'); tx=r('transactions'); cc=r('call_center_interactions')
D=str(RAW)+'/'
cu=pd.read_csv(D+'customers.csv',encoding='utf-8-sig'); pr=pd.read_csv(D+'products.csv',encoding='utf-8-sig')
print('--- transcripts sample'); 
for i in tr.sample(3,random_state=1).index: print(tr.loc[i,['detected_keywords','main_topics']].to_dict()); print(tr.loc[i,'full_text'][:600]); print()
print('unique full_text', tr.full_text.nunique(), 'of', len(tr))
tr['n']=tr.full_text.str.len(); print(tr.n.describe().round(0))
print('--- transcripts interaction link'); print('interaction ids in cc:', tr.interaction_id.isin(cc.interaction_id).mean().round(3))
m=tr.merge(cc[['interaction_id','reason_category']],on='interaction_id'); print((m.main_topics==m.reason_category).mean())
print('--- orphans complaints->customers/products'); print(cp.customer_id.isin(cu.customer_id).mean(), cp.affected_product_id.dropna().isin(pr.product_id).mean())
print('cc cust', cc.customer_id.isin(cu.customer_id).mean(),'tx prod', tx.product_id.isin(pr.product_id).mean(),'tx cust', tx.customer_id.isin(cu.customer_id).mean())
print('--- dup customers/products', cu.customer_id.duplicated().sum(), pr.product_id.duplicated().sum(), len(cu), len(pr))
print('--- tx country/city variants'); print(tx.transaction_country.value_counts().to_dict())
print('--- missing days per table')
for t,c in [('complaints','process_date'),('call_center_interactions','process_date'),('transactions','process_date')]:
    d=pd.to_datetime(r(t)[c]); print(t,d.min().date(),d.max().date(),d.nunique())
print('--- claims vs unrecognized charge by status'); u=cp[cp.subcategory=='Cargo no reconocido']; print(u.case_type.value_counts().to_dict(), u.status.value_counts().to_dict())
print(u.priority.value_counts().to_dict(), u.claimed_amount.astype(float).describe().round(1).to_dict())
print('has product',u.affected_product_id.notna().mean().round(3), 'compensation>0', u.compensation_granted.notna().mean().round(3))
print('--- Cargo no reconocido -> tx match on product within 30d before')
u=u.dropna(subset=['affected_product_id']).copy(); u['cd']=pd.to_datetime(u.creation_date); tx['td']=pd.to_datetime(tx.transaction_date)
t2=tx[tx.product_id.isin(u.affected_product_id)][['product_id','td','amount','transaction_status','is_fraud']]
mm=u.merge(t2,left_on='affected_product_id',right_on='product_id'); mm=mm[(mm.td<=mm.cd)&(mm.td>=mm.cd-pd.Timedelta(days=30))]
print('claims with >=1 tx in 30d:', mm.complaint_id.nunique(), 'of', len(u), '; frac fraud among matched tx', (mm.is_fraud=='True').mean().round(4))
mm['amt']=mm.amount.astype(float); print('claimed==tx amount:', (np.isclose(mm.amt,mm.claimed_amount.astype(float),atol=0.01)).any())
print('--- credit'); print(pr.product_type.value_counts().to_dict()); print(pr.product_status.value_counts().to_dict())
cr=pr[pr.product_type.isin(['Credit Card','Personal Loan','Mortgage'])]; print(cr.days_past_due.astype(float).describe().round(1).to_dict()); print('dpd>0', (cr.days_past_due.astype(float)>0).mean().round(3), 'dpd>90',(cr.days_past_due.astype(float)>90).mean().round(3))
cu['cs']=pd.to_numeric(cu.credit_score); print(cu.cs.describe().round(0).to_dict(),'null',cu.cs.isna().mean().round(3)); print(cu.groupby('segment').cs.mean().round(0).to_dict())
m=cr.merge(cu[['customer_id','cs','estimated_monthly_income']],on='customer_id'); m['dpd']=m.days_past_due.astype(float)
print('corr(credit_score, dpd)', m[['cs','dpd']].corr().iloc[0,1].round(3), '; corr income vs limit', np.corrcoef(m.estimated_monthly_income.astype(float).fillna(0), m.credit_limit.astype(float).fillna(0))[0,1].round(3))
print(cu.columns.tolist())
