import pandas as pd, glob, sys
pd.set_option('display.width',200); pd.set_option('display.max_columns',50); pd.set_option('display.max_rows',100)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import RAW, WORK
D=str(RAW)+'/'
def load(t):
    fs=glob.glob(D+t+'/**/*.csv',recursive=True)
    return pd.concat((pd.read_csv(f,dtype=str,encoding='utf-8-sig') for f in fs),ignore_index=True)
for t in ['complaints','call_center_interactions','call_transcripts','satisfaction_surveys','transactions']:
    df=load(t); df.to_parquet(WORK/f'{t}.parquet'); 
    idc=df.columns[0]
    print(f'== {t}: rows={len(df)} dup_id={df[idc].duplicated().sum()} cols={len(df.columns)}')
    print(' null%:', (df.isna().mean()*100).round(1)[lambda s:s>0].to_dict())
