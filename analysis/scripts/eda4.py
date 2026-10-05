import pandas as pd, glob
pd.set_option('display.width',220); pd.set_option('display.max_columns',50); pd.set_option('display.max_rows',80)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import RAW, WORK
D=str(RAW)+'/'
def load(t,cols=None):
    fs=glob.glob(D+t+'/**/*.csv',recursive=True)
    return pd.concat((pd.read_csv(f,dtype=str,encoding='utf-8-sig',usecols=cols) for f in fs),ignore_index=True)
cs=load('campaign_sends'); cs.to_parquet(WORK/'campaign_sends.parquet')
print('campaign_sends',len(cs),'dup',cs.send_id.duplicated().sum()); print((cs.isna().mean()*100).round(1)[lambda s:s>0].to_dict())
mc=pd.read_csv(D+'marketing_campaigns.csv',encoding='utf-8-sig')
print(mc.promoted_product.value_counts().to_dict()); print(mc.campaign_objective.value_counts().to_dict())
m=cs.merge(mc[['campaign_id','promoted_product','campaign_objective']],on='campaign_id',how='left')
print('orphan campaigns',m.promoted_product.isna().mean().round(3))
for c in ['was_delivered','was_opened','was_clicked','had_conversion']: m[c]=m[c]=='True'
print(m.groupby('promoted_product').agg(n=('send_id','size'),open=('was_opened','mean'),click=('was_clicked','mean'),conv=('had_conversion','mean')).round(3))
print(m.groupby('campaign_objective').agg(n=('send_id','size'),conv=('had_conversion','mean')).round(3))
print(m.send_channel.value_counts(normalize=True).round(3).to_dict())
de=load('digital_events'); de.to_parquet(WORK/'digital_events.parquet')
print('digital_events',len(de),'dup',de.event_id.duplicated().sum()); print((de.isna().mean()*100).round(1)[lambda s:s>0].to_dict())
for c in ['event_type','event_category','channel','platform','action','page_title']: print(c, de[c].value_counts(dropna=False).head(15).to_dict())
print(de.ip_country.value_counts().head(8).to_dict())
print('sessions',de.session_id.nunique(),'cust',de.customer_id.nunique())
