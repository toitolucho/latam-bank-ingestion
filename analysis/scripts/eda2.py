import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import RAW, WORK
import pandas as pd
pd.set_option('display.width',220); pd.set_option('display.max_columns',50); pd.set_option('display.max_rows',80)
r=lambda t: pd.read_parquet(WORK/f'{t}.parquet')
cc=r('call_center_interactions'); cp=r('complaints'); tr=r('call_transcripts'); tx=r('transactions')
print('--- CC reason_category'); print(cc.reason_category.value_counts(dropna=False,normalize=True).round(3))
print('--- CC contact_reason top'); print(cc.contact_reason.value_counts().head(30))
print('--- CC by channel'); print(cc.channel.value_counts(normalize=True).round(3))
for c in ['was_resolved','was_escalated','requires_followup']: print(c, cc[c].value_counts(normalize=True).round(3).to_dict())
g=cc.groupby('reason_category').agg(n=('interaction_id','size'),fcr=('was_resolved',lambda s:(s=='True').mean()),esc=('was_escalated',lambda s:(s=='True').mean()))
print(g.round(3))
print('--- complaints case_type'); print(cp.case_type.value_counts())
print(cp.groupby(['category','subcategory']).size().sort_values(ascending=False).head(40))
print('--- status'); print(cp.status.value_counts())
print('--- sla_breached', cp.sla_breached.value_counts(normalize=True).round(3).to_dict())
cp['rd']=pd.to_numeric(cp.resolution_days)
print(cp.groupby('category').rd.describe().round(1))
print(cp.groupby('priority').size())
print('--- Cargo no reconocido sample descriptions'); 
print(cp.description.value_counts().head(12))
print('--- transcripts intents'); print(tr.detected_intents.value_counts().head(25)); print(tr.main_topics.value_counts().head(15)); print(tr.detected_language.value_counts())
print('--- tx'); 
for c in ['transaction_type','transaction_status','channel','is_fraud','response_code','transaction_country','currency']: print(c, tx[c].value_counts(dropna=False,normalize=True).round(4).head(12).to_dict())
tx['fs']=pd.to_numeric(tx.fraud_score); print(tx.groupby('is_fraud').fs.describe().round(1))
