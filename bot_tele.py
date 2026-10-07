# TÁO XOÀI TOOL - TELEGRAM BOT ONLY
# CLEAN V57 · 67 board strategies + HASH-36 CALIBRATED
# Run: python bot_tele.py

import os, json, math, time, asyncio, sqlite3, re, html, hashlib
from pathlib import Path
from typing import Any
import httpx

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = os.getenv('DB_PATH', str(BASE_DIR / 'taoxoai_bot.db'))

POLL_SECONDS = max(0.35, float(os.getenv('POLL_SECONDS', '0.50')))

MAX_HISTORY = max(2000, min(50000, int(os.getenv('MAX_HISTORY', '10000'))))

BOT_TOKEN = os.getenv('BOT_TOKEN','').strip()

BOT_POLL_TIMEOUT = max(5, int(os.getenv('BOT_POLL_TIMEOUT','15')))

ADMIN_IDS = {int(x) for x in os.getenv('ADMIN_IDS','').replace(';',',').split(',') if x.strip().lstrip('-').isdigit()}

BOT_REQUIRE_ACCESS = os.getenv('BOT_REQUIRE_ACCESS','1').strip().lower() not in ('0','false','no','off')

BOARDS = {
    'sunwin:hu': {
        'game':'sunwin','table':'hu','kind':'tx_pair',
        'current':'https://amongst-plots-called-dining.trycloudflare.com/api/tx',
        'current_fallbacks':['https://kwinstore.com/sunwin/tx/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7'],
        'history':'https://kwinstore.com/sunwin/tx/history/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7',
    },
    'sunwin:sicbo': {
        'game':'sunwin','table':'sicbo','kind':'sicbo_pair',
        'current':'https://kwinstore.com/sunwin/sicbo/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7',
        'history':'https://kwinstore.com/sunwin/sicbo/history/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7',
    },
    'lc79:hu': {
        'game':'lc79','table':'hu','kind':'tx_pair',
        'current':'https://reported-prot-prefers-cattle.trycloudflare.com/api/tx',
        'current_fallbacks':['https://kwinstore.com/lc79/tx/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7'],
        'history':'https://kwinstore.com/lc79/tx/history/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7',
    },
    'lc79:md5': {
        'game':'lc79','table':'md5','kind':'tx_pair',
        'current':'https://reported-prot-prefers-cattle.trycloudflare.com/api/txmd5',
        'current_fallbacks':['https://kwinstore.com/lc79/md5/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7'],
        'history':'https://kwinstore.com/lc79/md5/history/9b7a587deb56a4caf8de8ffdb0c13e8d22e793ae598b66c7',
    },
    'lc79:xocdia': {
        'game':'lc79','table':'xocdia','kind':'xocdia',
        'current':'https://reported-prot-prefers-cattle.trycloudflare.com/api/xocdia',
    },
}

_db_lock = asyncio.Lock()

_worker_task = None

_bot_task = None

_ml_cache = {}

_hash_fast_cache = {}

_hash_fast_cache_order = []

_state_model_cache = {}

def pick(o: Any, keys):
    if not isinstance(o, dict): return None
    for k in keys:
        if k in o and o[k] is not None: return o[k]
    return None

def sid(o, fallback=None):
    return pick(o,['phien','phiên','phien_id','phienId','id','session_id','sessionId','session','gameId','game_id','stt','code','index','issue','round','roundId','round_id','sid']) or fallback

def canonical_session(v, fallback=None):
    """Normalize numeric sessions such as '#2755690' -> '2755690'."""
    if v is None:
        v=fallback
    if v is None:
        return None
    z=str(v).strip()
    m=re.search(r'(\d+)(?!.*\d)',z)
    return m.group(1) if m else z

def dice_values(o):
    arr = pick(o,['dices','dice','xuc_xac','xúc_xắc','xucXac','xucxac','dice_values','diceValues','xs','xucsac','xucxac_list'])
    if isinstance(arr,list):
        vals=[]
        for v in arr[:3]:
            if isinstance(v,dict): v=pick(v,['value','point','number','face','dice'])
            try: vals.append(int(v))
            except: pass
        if len(vals)>=3: return vals[:3]
    for ks in [('dice1','dice2','dice3'),('d1','d2','d3'),('xx1','xx2','xx3'),('xucxac1','xucxac2','xucxac3'),('xuc_xac_1','xuc_xac_2','xuc_xac_3'),('xucXac1','xucXac2','xucXac3')]:
        try:
            vals=[int(o[k]) for k in ks]
            return vals
        except: pass
    return []

def total_value(o,dice):
    v=pick(o,['point','points','Tong','tong','tổng','sum','total','score','totalPoint','total_point','tong_diem','tongDiem'])
    try: return int(v)
    except: return sum(dice) if len(dice)>=3 else None

def tx_result(o,dice=None,total=None):
    dice=dice or []
    if total is None: total=total_value(o,dice)
    v=pick(o,['ket_qua','kết_quả','ketqua','result','ketQua','resultTruyenThong','type','tai_xiu','taiXiu','taixiu','side','prediction','outcome','status_result','win','game_result','gameResult','result_text','resultText'])
    if v is not None:
        z=str(v).strip().upper()
        if 'TAI' in z or 'TÀI' in z or z in ('T','BIG','OVER','1','TRUE'): return 'TÀI'
        if 'XIU' in z or 'XỈU' in z or z in ('X','SMALL','UNDER','0','FALSE'): return 'XỈU'
    if total is not None: return 'TÀI' if total>10 else 'XỈU'
    return None

def find_rows(data, depth=0):
    if depth>4: return []
    if isinstance(data,list):
        if any(isinstance(x,dict) for x in data): return data
        return []
    if not isinstance(data,dict): return []
    for k in ['data','current','result','results','history','histories','list','items','sessions','rounds','records','rows','games','payload','response']:
        if k in data:
            hit=find_rows(data[k],depth+1)
            if hit: return hit
    if sid(data) is not None: return [data]
    for v in data.values():
        hit=find_rows(v,depth+1)
        if hit: return hit
    return []

def parse_tx(data):
    out=[]
    for i,o in enumerate(find_rows(data)):
        if not isinstance(o,dict): continue
        d=dice_values(o); t=total_value(o,d); r=tx_result(o,d,t)
        if not r: continue
        meta={
            'total_tai':pick(o,['total_tai','tong_tai','tai_total','totalTai']),
            'total_xiu':pick(o,['total_xiu','tong_xiu','xiu_total','totalXiu']),
            'jackpot':pick(o,['jackpot','hu','pot']),
            'raw_rs':pick(o,['raw_rS','raw_rs','raw']),
            'cbb':pick(o,['CBB','cbb']),
            'gbb':pick(o,['gBB','gbb']),
            'i':pick(o,['i'])
        }
        meta={k:v for k,v in meta.items() if v is not None}
        raw_sid=sid(o,i+1)
        out.append({'id':canonical_session(raw_sid,i+1),'result':r,'dice':d,'sum':t,
                    'md5':pick(o,['md5','hash','md5_hash','md5Hash','hash_md5','md5Code','md5_code','md5_result','md5_enc','md5_dec']),
                    'meta':dict(meta or {},raw_session=str(raw_sid) if raw_sid is not None else None)})
    def key(x):
        try: return (0,int(x['id']))
        except: return (1,x['id'])
    out.sort(key=key)
    return out

def parse_sicbo(data):
    """Parser riêng SUNWIN Sicbo; chuẩn hóa #phiên và kiểm tra xúc xắc 1..6."""
    out=[]
    for i,o in enumerate(find_rows(data)):
        if not isinstance(o,dict):
            continue
        d=dice_values(o)
        if len(d)<3:
            continue
        try:
            d=[int(x) for x in d[:3]]
        except:
            continue
        if any(x<1 or x>6 for x in d):
            continue
        t=total_value(o,d)
        if not isinstance(t,(int,float)) or int(t)<3 or int(t)>18:
            t=sum(d)
        else:
            t=int(t)
        r=tx_result(o,d,t)
        if r not in ('TÀI','XỈU'):
            continue
        raw_sid=sid(o,i+1)
        sess=canonical_session(raw_sid,i+1)
        if not sess:
            continue
        out.append({
            'id':sess,
            'result':r,
            'dice':d,
            'sum':t,
            'md5':pick(o,['md5_enc','md5','hash','md5_hash','md5Hash','md5_result','md5_dec','raw_rS','raw_rs']),
            'meta':{
                'source_game':pick(o,['game','name']) or 'sunwin',
                'update_at':pick(o,['update_at','updated_at','last_update','last_update_at','tick_update_at']),
                'md5_dec':pick(o,['md5_dec']),
                'raw_rs':pick(o,['raw_rS','raw_rs']),
                'jackpot':pick(o,['jackpot']),
                'raw_session':str(raw_sid) if raw_sid is not None else None
            }
        })
    out.sort(key=lambda x:(_session_num(x['id']) is None,_session_num(x['id']) or 0))
    return out

def sicbo_hash_features(h):
    """Adapted deterministic feature analyzer from sicbo(1).txt.
    The score is a heuristic signal, not a real probability.
    """
    if not h:return None
    h=str(h).strip().lower()
    m=re.search(r'([0-9a-f]{32,64})',h)
    if not m:return None
    h=m.group(1)
    try:
        p=[int(h[i:i+2],16) for i in range(0,min(len(h),64),2) if i+2<=len(h)]
        if not p:return None
        dS=sum(int(c,16) for c in h[:32]);hS=sum(p)
        bO=bin(int(h[:32],16))[2:].count('1')
        try:b1=int(h[:32],16).bit_count()/(len(h[:32])*4)
        except:b1=0.0
        h8=sum(1 for c in h[:32] if int(c,16)>=8)/max(1,len(h[:32]))
        xV=0
        for v in p[:16]:xV^=v
        lu=[2,1]
        for _ in range(2,15):lu.append(lu[-1]+lu[-2])
        lw=sum(p[i]*lu[i] for i in range(min(len(p),15)))
        mean=sum(p)/len(p)
        std=math.sqrt(sum((x-mean)**2 for x in p)/len(p))
        comp=len(set(h[:32]))
        fo=sum(abs(p[i]-p[i-1]) for i in range(1,min(len(p),16)))
        sha=''.join(hex(((ord(h[i%len(h)])*(i+1)+7)%16))[2:] for i in range(56))
        sP=[int(sha[i:i+2],16) for i in range(0,len(sha)-1,2)]
        sS=sum(sP) if sP else 0
        hl=len(h)//2
        sym=sum(1 for i in range(min(hl,16)) if i<len(h) and hl+i<len(h) and h[i]==h[hl+i])
        first=p[:10]
        geo=math.pow(math.prod(first),1/len(first)) if len(first)>=10 and all(v>0 for v in first) else 0.0
        cX=xV^(int(sha[:2],16) if sha[:2] else 0)
        def fib_mod(x,mod):
            a,b=0,1
            for _ in range(2,x+1):a,b=b,a+b
            return b%mod
        fib=fib_mod(dS,100) if dS>0 else 0
        bX=0
        for i in range(0,len(sha)-1,2):bX^=int(sha[i:i+2],16)
        wE=(p[0]*3+p[-1]*2)%100 if p else 50
        mV=[hS%x for x in (43,47,53,59,61,67)] if hS else [0]*6
        maxR=max((h[:32].count(c) for c in set(h[:32])),default=0)
        odd=sum(1 for c in h[:32] if int(c,16)%2==1)
        sI=len(p)//4;eI=(3*len(p))//4
        mid=sum(p[sI:eI]) if sI<eI else 0
        fibH=sum(1 for c in h[:32] if c in '12358')
        shaSym=sum(1 for i in range(16) if i<len(sha) and 39-i<len(sha) and sha[i]==sha[39-i])
        freq={}
        for c in h[:32]:freq[c]=freq.get(c,0)+1
        ent=0.0
        for v in freq.values():
            pc=v/max(1,len(h[:32]))
            if pc>0:ent-=pc*math.log2(pc)
        tX=xV^bX^cX;last=int(h[-1],16);wf=1.0 if len(h)>=32 else .8
        score=(dS*.05+hS*.05+bO*.05+b1*.1+h8*.1+lw*.05+std*.05+comp*.05+fo*.05+
               sS*.05+sym*.05+geo*.05+cX*.05+fib*.05+bX*.05+wE*.05+sum(mV)*.05+
               maxR*.05+odd*.05+mid*.05+fibH*.05+shaSym*.05+ent*.05+tX*.05+last*.05)*wf%100
        return {'raw_score':round(score,4),'raw_prediction':'TÀI' if score>=50 else 'XỈU',
                'tai_signal':round(score,2),'xiu_signal':round(100-score,2),
                'entropy':round(ent,4),'bit_density':round(b1,4),'byte_std':round(std,3),'hex_unique':comp}
    except Exception:
        return None

def sicbo_hash_signal(rows):
    """Calibrate hash direction causally on this board's own history."""
    hist=[r for r in rows[-260:] if r.get('result') in ('TÀI','XỈU')]
    if not hist:return {'ready':False,'usable':False,'sample':0}
    tests=[]
    for i in range(1,len(hist)):
        f=sicbo_hash_features(hist[i-1].get('md5'))
        if f:tests.append((f['raw_prediction'],hist[i]['result']))
    n=len(tests);raw_w=sum(1 for p,a in tests if p==a);inv_w=sum(1 for p,a in tests if _opp(p)==a)
    orientation='normal' if raw_w>=inv_w else 'reverse'
    best_w=max(raw_w,inv_w)
    quality=(best_w+8*.5)/max(1,n+8)
    raw_acc=raw_w/max(1,n)
    latest=sicbo_hash_features(hist[-1].get('md5'))
    if not latest:
        return {'ready':False,'usable':False,'sample':n,'orientation':orientation,
                'quality':round(quality,4),'raw_accuracy':round(raw_acc,4)}
    pred=latest['raw_prediction'] if orientation=='normal' else _opp(latest['raw_prediction'])
    usable=(n>=18 and quality>=.525)
    return {'ready':True,'usable':usable,'sample':n,'orientation':orientation,
            'prediction':pred,'quality':round(quality,4),'raw_accuracy':round(raw_acc,4),
            'raw_prediction':latest['raw_prediction'],'raw_score':latest['raw_score'],
            'tai_signal':latest['tai_signal'],'xiu_signal':latest['xiu_signal'],
            'note':'calibrated historical hash signal'}

def sicbo_dice_side(rows):
    df=dice_position_forecast(rows)
    if not df.get('ready'):
        return {'ready':False,'prediction':None,'quality':0.0,'forecast':df}
    expected=float(df.get('expected_total') or 10.5)
    pred='TÀI' if expected>=10.5 else 'XỈU'
    q=float(df.get('quality') or 0.0)
    meta_q=_clamp(.48+max(0.0,q-.18)*.20,.48,.61)
    return {'ready':True,'prediction':pred,'quality':round(meta_q,4),'forecast':df}

def parse_xocdia(data):
    rows=[]
    for i,o in enumerate(find_rows(data)):
        if not isinstance(o,dict): continue
        raw=pick(o,['ket_qua_truyen_thong','ket_qua','result','ketQua'])
        z=str(raw or '').strip().upper()
        if 'CHẴN' in z or 'CHAN' in z or 'EVEN' in z: result='TÀI'   # internal binary: TÀI == CHẴN
        elif 'LẺ' in z or z=='LE' or 'ODD' in z: result='XỈU'       # internal binary: XỈU == LẺ
        else: continue
        colors=pick(o,['xuc_xac_goc','xuc_xac','coins','colors']) or []
        if not isinstance(colors,list): colors=[]
        norm=[str(x).lower() for x in colors]
        red=sum(1 for x in norm if 'do'==x or 'đỏ' in x or x=='red')
        white=sum(1 for x in norm if 'trang'==x or 'trắng' in x or x=='white')
        raw_sid=sid(o,i+1)
        rows.append({
            'id':canonical_session(raw_sid,i+1),'result':result,'dice':[],'sum':red,
            'md5':pick(o,['md5','md5_raw','hash']),
            'meta':{'colors':norm[:4],'red_count':red,'white_count':white,
                    'detail':pick(o,['ket_qua_chi_tiet','ket_qua_chi_tiet_goc']),
                    'jackpot_result':pick(o,['jackpot_result_goc','jackpot_result'])}
        })
    def key(x):
        try:return (0,int(re.sub(r'\D','',x['id']) or 0))
        except:return (1,x['id'])
    rows.sort(key=key)
    return rows

def dice_position_forecast(rows):
    """Ensemble vị Sicbo: decay-frequency + Markov1/2 + lag-cycle + sum-state.
    `probability` là tỷ trọng model nội bộ, không phải xác suất thật của viên xúc xắc.
    """
    valid=[r for r in rows[-850:] if isinstance(r.get('dice'),list) and len(r.get('dice'))>=3]
    valid=[r for r in valid if all(isinstance(x,(int,float)) and 1<=int(x)<=6 for x in r.get('dice')[:3])]
    if len(valid)<18:
        return {'ready':False,'sample':len(valid),'faces':[],'estimated_total':None,'sum_zone':'ĐANG HỌC'}

    def fit_pos(hist,j):
        last=int(hist[-1]['dice'][j])
        prev2=tuple(int(r['dice'][j]) for r in hist[-2:])
        scores={k:2.2 for k in range(1,7)}

        # 1) recency-decayed face frequency
        for idx,r in enumerate(hist):
            v=int(r['dice'][j]); age=len(hist)-1-idx
            scores[v]+=0.78*(0.5**(age/52))

        # 2) Markov-1 transition from current face
        ev1=0.0
        for idx in range(1,len(hist)):
            if int(hist[idx-1]['dice'][j])!=last: continue
            nxt=int(hist[idx]['dice'][j]); age=len(hist)-1-idx
            w=0.5**(age/44); scores[nxt]+=1.65*w; ev1+=w

        # 3) Markov-2 on this position
        ev2=0.0
        for idx in range(2,len(hist)):
            ctx=(int(hist[idx-2]['dice'][j]),int(hist[idx-1]['dice'][j]))
            if ctx!=prev2: continue
            nxt=int(hist[idx]['dice'][j]); age=len(hist)-1-idx
            w=0.5**(age/48); scores[nxt]+=1.28*w; ev2+=w

        # 4) strongest positive/inverse lag state
        arr=[int(r['dice'][j]) for r in hist[-180:]]
        best_lag=None; best_edge=0.0; best_face=None
        for lag in (2,3,4,5,6,7,8,10,12):
            if len(arr)<lag+28: continue
            same=sum(1 for idx in range(lag,len(arr)) if arr[idx]==arr[idx-lag])
            rate=same/max(1,len(arr)-lag)
            edge=rate-(1/6)
            if edge>best_edge:
                best_edge=edge; best_lag=lag; best_face=arr[-lag]
        if best_lag and best_edge>.035:
            scores[best_face]+=min(1.6, .45+best_edge*6.0)

        # 5) previous total band -> next face at this position
        cur_sum=hist[-1].get('sum')
        if isinstance(cur_sum,(int,float)):
            band='L' if cur_sum<=8 else 'H' if cur_sum>=13 else 'M'
            for idx in range(1,len(hist)):
                ps=hist[idx-1].get('sum')
                if not isinstance(ps,(int,float)): continue
                pb='L' if ps<=8 else 'H' if ps>=13 else 'M'
                if pb!=band: continue
                nxt=int(hist[idx]['dice'][j]); age=len(hist)-1-idx
                scores[nxt]+=.58*(0.5**(age/46))

        total_score=sum(scores.values()) or 1.0
        ordered=sorted(scores.items(),key=lambda kv:kv[1],reverse=True)
        top,second=ordered[0],ordered[1]
        edge=(top[1]-second[1])/max(.001,top[1]+second[1])
        mean=sum(face*sc for face,sc in scores.items())/total_score
        return {
            'position':j+1,
            'face':top[0],
            'expected':round(mean,3),
            'strength':round(edge,3),
            'model_share':round(top[1]/total_score,3),
            'markov1_support':round(ev1,2),
            'markov2_support':round(ev2,2),
            'lag':best_lag or 0,
            'top3':[{'face':f,'share':round(sc/total_score,3)} for f,sc in ordered[:3]]
        }

    faces=[fit_pos(valid,j) for j in range(3)]
    expected_total=sum(x['expected'] for x in faces)
    est_top=sum(x['face'] for x in faces)
    zone='3–8' if expected_total<8.5 else '9–10' if expected_total<10.5 else '11–12' if expected_total<12.5 else '13–18'

    # lightweight walk-forward top-1 validation on recent known rounds
    checks=0; hits=[0,0,0]
    start=max(18,len(valid)-90)
    step=3  # keep CPU light while polling
    for idx in range(start,len(valid),step):
        hist=valid[:idx]
        if len(hist)<18: continue
        for j in range(3):
            pred=fit_pos(hist,j)['face']
            hits[j]+=int(pred==int(valid[idx]['dice'][j]))
        checks+=1
    validation=[round(h/max(1,checks),3) for h in hits]

    # reliability shrinks when top-1 validation is no better than the 1/6 baseline
    rel=sum(max(0.0,v-(1/6)) for v in validation)/3
    overall_strength=sum(x['strength'] for x in faces)/3
    quality=_clamp(.15 + rel*2.6 + overall_strength*1.8,.15,.78)

    return {
        'ready':True,'sample':len(valid),'faces':faces,
        'estimated_total_top':est_top,'expected_total':round(expected_total,2),
        'sum_zone':zone,'validation':validation,'checks':checks,
        'quality':round(quality,3)
    }

def xocdia_detail_forecast(rows, binary_prediction):
    want_even=(binary_prediction=='TÀI')
    allowed=[k for k in range(5) if (k%2==0)==want_even]
    scores={k:1.4 for k in allowed}
    valid=[]
    for r in rows[-700:]:
        meta=r.get('meta') or {};red=meta.get('red_count')
        if isinstance(red,int) and 0<=red<=4:valid.append(red)
    for idx,red in enumerate(valid):
        if red not in scores:continue
        age=len(valid)-1-idx;scores[red]+=0.5**(age/44)
    # transition conditioned on the last observed red-count
    if valid:
        last=valid[-1]
        for i in range(1,len(valid)):
            if valid[i-1]==last and valid[i] in scores:
                age=len(valid)-1-i;scores[valid[i]]+=1.25*(0.5**(age/40))
    if not scores:return None
    total=sum(scores.values());best=max(scores,key=scores.get)
    return {'red_count':best,'white_count':4-best,'label':f'{best} Đỏ · {4-best} Trắng',
            'sample':len(valid),'probability':round(scores[best]/max(.001,total),3)}

def _clamp(v,a,b):
    return max(a,min(b,v))

def _entropy(seq):
    if not seq: return 1.0
    p=sum(1 for x in seq if x=='TÀI')/len(seq)
    if p<=0 or p>=1: return 0.0
    return -p*math.log2(p)-(1-p)*math.log2(1-p)

def _session_num(v):
    m=re.search(r'(\d+)(?!.*\d)',str(v)) if v is not None else None
    try: return int(m.group(1)) if m else None
    except: return None

def _stable_rows(rows):
    u={str(r.get('id')):r for r in rows if r.get('id') is not None}
    nums=sorted([r for r in u.values() if _session_num(r.get('id')) is not None],key=lambda r:_session_num(r['id']))
    if len(nums)>=4:
        groups=[]; g=[nums[0]]
        for r in nums[1:]:
            if _session_num(r['id'])-_session_num(g[-1]['id'])<=12:g.append(r)
            else:groups.append(g);g=[r]
        groups.append(g)
        best=max(groups,key=lambda x:(len(x),_session_num(x[-1]['id'])))
        if len(best)>=3: nums=best
    return nums

def _next_session(rows):
    s=_stable_rows(rows)
    return str(_session_num(s[-1]['id'])+1) if s else None

def _sigmoid(z):
    z=_clamp(float(z),-18.0,18.0)
    return 1.0/(1.0+math.exp(-z))

def _ml_feature(valid, upto):
    """Features computed only from rows before `upto`, so training never peeks at the target."""
    if upto < 12: return None
    hist=valid[:upto]
    seq=[1 if r.get('result')=='TÀI' else -1 for r in hist]
    f=[1.0]
    # last 5 binary outcomes
    for k in range(1,6):
        f.append(float(seq[-k]) if len(seq)>=k else 0.0)
    # multi-window balances
    for w in (6,12,24,48):
        q=seq[-w:]
        f.append(sum(q)/max(1,len(q)))
    # signed run length
    run=1
    for j in range(len(seq)-2,-1,-1):
        if seq[j]==seq[-1] and run<8: run+=1
        else: break
    f.append(seq[-1]*run/8.0)
    # flip rate
    q=seq[-16:]
    fr=sum(1 for j in range(1,len(q)) if q[j]!=q[j-1])/max(1,len(q)-1)
    f.append((fr-.5)*2.0)
    # transition conditioned on last state, Laplace-smoothed
    p=x=1.5
    for j in range(1,len(seq)):
        if seq[j-1]!=seq[-1]: continue
        if seq[j]>0:p+=1
        else:x+=1
    f.append((p-x)/(p+x))
    # order-2 context
    p=x=1.5
    if len(seq)>=3:
        ctx=tuple(seq[-2:])
        for j in range(2,len(seq)):
            if tuple(seq[j-2:j])!=ctx: continue
            if seq[j]>0:p+=1
            else:x+=1
    f.append((p-x)/(p+x))
    # entropy / regime
    raw=['TÀI' if v>0 else 'XỈU' for v in seq[-36:]]
    f.append((.5-_entropy(raw))*2.0)
    # dice/sum state
    last=hist[-1]
    sm=last.get('sum')
    f.append(_clamp(((float(sm)-10.5)/7.5) if isinstance(sm,(int,float)) else 0.0,-1,1))
    sums=[r.get('sum') for r in hist[-10:] if isinstance(r.get('sum'),(int,float))]
    f.append(_clamp(((sum(sums)/len(sums)-10.5)/5.0) if sums else 0.0,-1,1))
    if len(sums)>=2: f.append(_clamp((sums[-1]-sums[-2])/8.0,-1,1))
    else: f.append(0.0)
    d=last.get('dice') or []
    if len(d)>=3:
        f.append((sum(1 for v in d[:3] if int(v)>=4)-1.5)/1.5)
        f.append((sum(1 for v in d[:3] if int(v)%2==0)-1.5)/1.5)
        pair=len(set(int(v) for v in d[:3]))
        f.append(1.0 if pair==1 else .35 if pair==2 else -.35)
    else:
        f.extend([0.0,0.0,0.0])
    # optional crowd-flow feature; low influence and only when source exposes both totals
    meta=last.get('meta') or {}
    try:
        tt=float(meta.get('total_tai')); tx=float(meta.get('total_xiu'))
        f.append(_clamp((tt-tx)/max(1.0,tt+tx),-1,1))
    except:
        f.append(0.0)
    return f

def _online_ml_signal(rows, board=None):
    valid=[r for r in rows[-560:] if r.get('result') in ('TÀI','XỈU')]
    if len(valid)<70:
        return {'ready':False,'sample':max(0,len(valid)-12),'score':0.0,'p_tai':.5,'val_accuracy':.5,'brier':.25}
    last_id=str(valid[-1].get('id'))
    cache_key=(board or '',last_id,len(valid))
    if board and cache_key in _ml_cache:
        return _ml_cache[cache_key]
    samples=[]
    for i in range(12,len(valid)):
        x=_ml_feature(valid,i)
        if x is None: continue
        y=1.0 if valid[i].get('result')=='TÀI' else 0.0
        samples.append((x,y))
    if len(samples)<45:
        res={'ready':False,'sample':len(samples),'score':0.0,'p_tai':.5,'val_accuracy':.5,'brier':.25}
        if board:_ml_cache[cache_key]=res
        return res
    cut=max(30,min(len(samples)-12,int(len(samples)*.76)))
    train=samples[:cut]; val=samples[cut:]
    dim=len(train[0][0]); w=[0.0]*dim
    # SGD with L2 and recency emphasis
    for ep in range(5):
        lr=.050/(1.0+ep*.38)
        L=max(1,len(train))
        for idx,(x,y) in enumerate(train):
            p=_sigmoid(sum(a*b for a,b in zip(w,x)))
            rw=.35+.65*((idx+1)/L)
            err=(y-p)*rw
            for j in range(dim):
                reg=.0025*w[j] if j else 0.0
                w[j]+=lr*(err*x[j]-reg)
    correct=0; brier=0.0
    for x,y in val:
        p=_sigmoid(sum(a*b for a,b in zip(w,x)))
        correct += int((p>=.5)==(y>=.5))
        brier += (p-y)**2
    acc=correct/max(1,len(val)); brier/=max(1,len(val))
    # train the final model on all known samples after validation is measured
    for ep in range(2):
        lr=.025/(1+ep*.4); L=max(1,len(samples))
        for idx,(x,y) in enumerate(samples):
            p=_sigmoid(sum(a*b for a,b in zip(w,x)))
            rw=.45+.55*((idx+1)/L); err=(y-p)*rw
            for j in range(dim):
                reg=.002*w[j] if j else 0.0
                w[j]+=lr*(err*x[j]-reg)
    cur=_ml_feature(valid,len(valid))
    p=_sigmoid(sum(a*b for a,b in zip(w,cur)))
    reliability=_clamp(.08+max(0,acc-.50)*2.6+max(0,.25-brier)*1.7,.08,.72)
    # if validation is below chance, strongly shrink rather than invert/overfit.
    if acc<.49 and brier>=.25: reliability*=.45
    strength=(p-.5)*2.0*reliability
    res={'ready':True,'sample':len(samples),'validation':len(val),'p_tai':round(p,4),
         'val_accuracy':round(acc,4),'brier':round(brier,4),'reliability':round(reliability,4),
         'score':round(_clamp(strength,-.58,.58),4)}
    if board:
        # keep only the newest cache for this board
        for k in list(_ml_cache):
            if k[0]==board and k!=cache_key:_ml_cache.pop(k,None)
        _ml_cache[cache_key]=res
    return res

def model_snapshot(rows, game=None, board=None):
    seq=[r['result'] for r in rows if r.get('result') in ('TÀI','XỈU')]
    if len(seq)<6:
        return {'sample':len(seq),'score':0.0,'prediction':None,'confidence':50,'percent':50,
                'pattern':'ĐANG HỌC','alt':'Chưa đủ mẫu','entropy':round(_entropy(seq),4),
                'cycle':{'k':0,'r':0.0},'agreement':0.5,'engine':'BOARD-META 67 + HASH-36 TURBO ENSEMBLE V56',
                'skills':0,'totalSkills':60,'ml':{'ready':False},'updated_at':time.time()}
    vote=lambda x: 1 if x=='TÀI' else -1
    n=len(seq); comps=[]
    def add(name,score,weight):
        if isinstance(score,(int,float)) and math.isfinite(score):
            comps.append((name,_clamp(float(score),-.85,.85),float(weight)))

    # Decayed Markov / VOM contexts 1..5
    for order,wt in [(1,1.00),(2,1.15),(3,1.24),(4,1.18),(5,1.05)]:
        if n<order+5: continue
        ctx=tuple(seq[-order:]); p=x=1.6; ev=0.0
        for i in range(order,n):
            if tuple(seq[i-order:i])!=ctx: continue
            age=(n-1)-i; w=0.5**(age/34)
            if seq[i]=='TÀI': p+=w
            else: x+=w
            ev+=w
        if ev>=1.2: add(f'ctx{order}',(p-x)/(p+x),wt)

    # Multi-window balance + EWMA trend
    vals=[]
    for win in (6,10,18,30,48,80):
        q=seq[-win:]
        if len(q)>=min(6,win):
            bal=sum(vote(z) for z in q)/len(q); vals.append(bal)
            add(f'window{win}',bal,(.48+.30*min(1,win/48)))
    if vals:
        pos=sum(v>0 for v in vals); neg=sum(v<0 for v in vals)
        if max(pos,neg)/len(vals)>=.6:
            add('multiwin',sum(v/(1+i*.32) for i,v in enumerate(vals))/sum(1/(1+i*.32) for i in range(len(vals)))*.46,.76)
    ew=0.0; denew=0.0
    for age,z in enumerate(reversed(seq[-80:])):
        w=.5**(age/14); ew+=vote(z)*w; denew+=w
    if denew:add('ewma',ew/denew,.72)
    if n>=30:
        a=sum(vote(z) for z in seq[-10:])/10
        b=sum(vote(z) for z in seq[-30:-10])/20
        add('balance_slope',(a-b)*.55,.62)
        if abs(a-b)>=.35:add('changepoint',a*.24,.56)

    # Run pressure + flip/repeat state
    run=1
    for i in range(n-2,-1,-1):
        if seq[i]==seq[-1]: run+=1
        else: break
    if run>=5: add('runpressure',-vote(seq[-1])*(.13+.025*min(run-5,4)),.68)
    elif run==4: add('runpressure',-vote(seq[-1])*.10,.62)
    elif run==3: add('runpressure',-vote(seq[-1])*.04,.50)
    current_flip=seq[-1]!=seq[-2]
    same=flip=1.8; ev=0.0
    for i in range(2,n):
        if (seq[i-1]!=seq[i-2])!=current_flip: continue
        age=(n-1)-i; w=0.5**(age/34)
        if seq[i]==seq[i-1]: same+=w
        else: flip+=w
        ev+=w
    if ev>=2:add('fliprepeat',vote(seq[-1])*(same-flip)/(same+flip),.66)
    if n>=10:
        recent=seq[-14:]; flips=sum(1 for i in range(1,len(recent)) if recent[i]!=recent[i-1])
        rate=flips/max(1,len(recent)-1)
        if rate>.64:add('flippressure',-vote(seq[-1])*(rate-.5)*1.35,.72)
        elif rate<.36:add('repeatpressure',vote(seq[-1])*(.5-rate)*1.25,.68)

    # Recent transition + run-length conditional
    if n>=12:
        cur=seq[-1]; p=x=1.5; ev=0.0
        for i in range(1,n):
            if seq[i-1]!=cur: continue
            w=0.5**(((n-1)-i)/24)
            if seq[i]=='TÀI': p+=w
            else:x+=w
            ev+=w
        if ev>=2:add('transition',(p-x)/(p+x),.82)
    if n>=18:
        p=x=1.5; ev=0.0
        for i in range(2,n):
            rr=1; j=i-2
            while j>=0 and seq[j]==seq[i-1] and rr<8:
                rr+=1;j-=1
            if rr!=min(run,8):continue
            w=0.5**(((n-1)-i)/30)
            if seq[i]=='TÀI':p+=w
            else:x+=w
            ev+=w
        if ev>=1.5:add('runcond',(p-x)/(p+x),.76)

    # Motifs 3..6
    for L,wt in ((3,.70),(4,.78),(5,.84),(6,.78)):
        if n<L+8:continue
        motif=tuple(seq[-L:]);p=x=1.4;ev=0.0
        for i in range(L,n):
            if tuple(seq[i-L:i])!=motif:continue
            w=0.5**(((n-1)-i)/28)
            if seq[i]=='TÀI':p+=w
            else:x+=w
            ev+=w
        if ev>=1.2:add(f'motif{L}',(p-x)/(p+x),wt)

    # Markov order 2/3 with a separate recency window
    for order,wt,half in ((2,.88,34),(3,.91,40)):
        if n<order+18:continue
        ctx=tuple(seq[-order:]);p=x=1.6;ev=0.0
        for i in range(order,n):
            if tuple(seq[i-order:i])!=ctx:continue
            w=0.5**(((n-1)-i)/half);ev+=w
            if seq[i]=='TÀI':p+=w
            else:x+=w
        if ev>=2:add(f'markov{order}',(p-x)/(p+x),wt)

    # Multi-lag positive/inverse autocorrelation candidates
    arr=[vote(x) for x in seq[-120:]]; best=0.0; lag=0
    if len(arr)>=14:
        mean=sum(arr)/len(arr);den=sum((x-mean)**2 for x in arr)
        if den:
            for k in range(1,min(16,len(arr)//3)+1):
                num=sum((arr[i]-mean)*(arr[i+k]-mean) for i in range(len(arr)-k));r=num/den
                if abs(r)>abs(best):best=r;lag=k
                if abs(r)>=.16:
                    base=vote(seq[-k]);add(f'lag{k}',base*(1 if r>0 else -1)*min(.46,abs(r)*.75),.60)
    if lag:
        lagv=vote(seq[-lag]);add('autocorr',(lagv if best>=0 else -lagv)*min(.44,abs(best)*.72),.76)

    # Dice/sum contextual experts
    valid=[r for r in rows if r.get('result') in ('TÀI','XỈU')]
    if valid:
        cur_sum=valid[-1].get('sum')
        if isinstance(cur_sum,(int,float)):
            p=x=1.7;ev=0
            for i,r in enumerate(valid[:-1]):
                if r.get('sum')!=cur_sum:continue
                w=0.5**(((len(valid)-2)-i)/40)
                if valid[i+1]['result']=='TÀI':p+=w
                else:x+=w
                ev+=w
            if ev>=1.8:add('exactsum',(p-x)/(p+x),.72)
            bucket='LOW' if cur_sum<=8 else 'HIGH' if cur_sum>=13 else 'MID'
            p=x=1.6;ev=0
            for i,r in enumerate(valid[:-1]):
                sm=r.get('sum')
                if not isinstance(sm,(int,float)):continue
                b='LOW' if sm<=8 else 'HIGH' if sm>=13 else 'MID'
                if b!=bucket:continue
                w=0.5**(((len(valid)-2)-i)/36)
                if valid[i+1]['result']=='TÀI':p+=w
                else:x+=w
                ev+=w
            if ev>=1.8:add('sumband',(p-x)/(p+x),.68)
            if len(valid)>=3 and isinstance(valid[-2].get('sum'),(int,float)):
                cur_delta=1 if cur_sum>valid[-2]['sum'] else -1 if cur_sum<valid[-2]['sum'] else 0
                p=x=1.6;ev=0
                for i in range(2,len(valid)):
                    a=valid[i-2].get('sum');b=valid[i-1].get('sum')
                    if not isinstance(a,(int,float)) or not isinstance(b,(int,float)):continue
                    d=1 if b>a else -1 if b<a else 0
                    if d!=cur_delta:continue
                    w=.5**(((len(valid)-1)-i)/36)
                    if valid[i]['result']=='TÀI':p+=w
                    else:x+=w
                    ev+=w
                if ev>=1.8:add('sumdelta',(p-x)/(p+x),.64)

        cur_d=valid[-1].get('dice') or []
        if len(cur_d)>=3:
            def state_parity(d):return sum(int(v)%2==0 for v in d[:3])
            def state_high(d):return sum(int(v)>=4 for v in d[:3])
            def state_pair(d):return len(set(int(v) for v in d[:3]))
            for name,fn,wt in [('parity',state_parity,.58),('highcount',state_high,.62),('pairstate',state_pair,.57)]:
                cur=fn(cur_d);p=x=1.6;ev=0
                for i,r in enumerate(valid[:-1]):
                    d=r.get('dice') or []
                    if len(d)<3 or fn(d)!=cur:continue
                    w=.5**(((len(valid)-2)-i)/36)
                    if valid[i+1]['result']=='TÀI':p+=w
                    else:x+=w
                    ev+=w
                if ev>=1.8:add(name,(p-x)/(p+x),wt)
            # Per-position face-conditioned next-result experts
            for pos in range(3):
                face=int(cur_d[pos]);p=x=1.5;ev=0
                for i,r in enumerate(valid[:-1]):
                    d=r.get('dice') or []
                    if len(d)<3:continue
                    try:match=int(d[pos])==face
                    except:match=False
                    if not match:continue
                    w=.5**(((len(valid)-2)-i)/38)
                    if valid[i+1]['result']=='TÀI':p+=w
                    else:x+=w
                    ev+=w
                if ev>=2.0:add(f'pos{pos+1}face',(p-x)/(p+x),.54)

        # Sicbo-only position/total expectation expert.
        if board=='sunwin:sicbo' and len(valid)>=24:
            try:
                df=dice_position_forecast(valid)
                if df.get('ready'):
                    exp=float(df.get('expected_total',10.5))
                    q=float(df.get('quality',.2))
                    # Small expert only; exact dice are inherently noisy.
                    add('sicbo_possum',_clamp((exp-10.5)/5.5,-.55,.55),.36+.28*q)
            except:
                pass

        # Weak crowd-flow expert if source exposes totals; never treated as ground truth.
        meta=valid[-1].get('meta') or {}
        try:
            tt=float(meta.get('total_tai'));tx=float(meta.get('total_xiu'))
            crowd=(tt-tx)/max(1.0,tt+tx)
            if abs(crowd)>=.03:add('crowdflow',crowd*.35,.28)
        except:pass

    # Online logistic learner trained/validated only on this board's historical rows.
    ml=_online_ml_signal(rows,board)
    if ml.get('ready') and abs(ml.get('score',0))>=.012:
        # validation/reliability is already folded into score; keep it as one expert, not a dictator.
        add('online_ml',ml['score'],1.12)

    active=[c for c in comps if abs(c[1])>=.028]
    if not active:active=[('fallback',vote(seq[-1])*.02,.25)]
    num=sum(sc*wt for _,sc,wt in active);den=sum(abs(wt) for _,_,wt in active) or 1
    raw=num/den
    posw=sum(abs(wt) for _,sc,wt in active if sc>0);negw=sum(abs(wt) for _,sc,wt in active if sc<0)
    agreement=max(posw,negw)/max(.001,posw+negw)
    H=_entropy(seq[-80:])
    sample_factor=_clamp(n/42,.56,1.0)
    entropy_factor=_clamp(1.22-H*.43,.72,1.0)
    agree_factor=.62 if agreement<.55 else .82 if agreement<.67 else 1.0
    score=_clamp(raw*sample_factor*entropy_factor*agree_factor,-.82,.82)
    # explicit conflict damping (fixes the old undefined `signals` runtime bug)
    score*=1.0-min(.42,max(0.0,1.0-agreement)*.72)
    if abs(score)<.012:score=vote(seq[-1])*.012
    pred='TÀI' if score>=0 else 'XỈU'
    evidence=_clamp(abs(score)*1.92+max(0,agreement-.5)*.46,0,1)
    cap=64 if game=='baccarat' else 69
    conf=round(_clamp(50+evidence*(cap-50),51,cap))
    if run>=3:pattern=f"BỆT {seq[-1]} x{run}"
    elif current_flip:pattern='ĐẢO 1-1 / FLIP'
    else:pattern='CẦU HỖN HỢP'
    top=sorted(active,key=lambda c:abs(c[1]*c[2]),reverse=True)[:8]
    top_signals=[{'name':name,'score':round(sc,3),'weight':round(wt,3)} for name,sc,wt in top]
    ml_txt=(f" · ML val {round(ml.get('val_accuracy',.5)*100)}%" if ml.get('ready') else '')
    alt=f"{len(active)} tín hiệu · đồng thuận {round(agreement*100)}% · entropy {H:.3f}{ml_txt}"
    return {'sample':n,'score':round(score,4),'prediction':pred,'confidence':conf,'percent':conf,
            'run':run,'pattern':pattern,'alt':alt,'entropy':round(H,4),
            'cycle':{'k':lag,'r':round(best,4)},'agreement':round(agreement,4),
            'engine':'BOARD-META 67 + HASH-36 TURBO ENSEMBLE V56','skills':len(active),'totalSkills':60,
            'ml':ml,'top_signals':top_signals,'updated_at':time.time()}

fusion_model_snapshot = model_snapshot

STRATEGY_NAMES = (
    'FOLLOW_LAST','REVERSE_LAST','ALTERNATING_PATTERN','RUN_BREAK','RUN_FOLLOW',
    'BIAS_MEAN_REVERSION','BIAS_MOMENTUM','MARKOV_TRANSITION','ANTI_RAW',
    'HIGH_ORDER_MARKOV','MARKOV_ORDER2','RUN_HAZARD','MULTI_WINDOW',
    'DECAYED_TRANSITION','REGIME_ADAPTIVE','MOTIF_WEIGHTED',
    'FLIP_STATE_MARKOV','RUN_LENGTH_MARKOV','PERIODIC_MATCH','DUAL_HORIZON',
    'ANALOG_KNN','RUN_SURVIVAL','CONTEXT_ENTROPY',
    'BAYES_CONTEXT','HORIZON_CONSENSUS','REGIME_SWITCH','LAG_ENSEMBLE',
    'REFERENCE_PATTERN_PRIOR','JS_TREND_BLEND','JS_BREAK_CALIBRATOR','JS_ULTRA_STACK',
    'VOM_CONTEXT_6','LONG_MEMORY_BAYES','RUN_PROFILE_LONG','MULTISCALE_TRANSITION',
    'CHANGEPOINT_ADAPTIVE','WILSON_CONTEXT','KNN_RECENCY','RUN_MATRIX',
    'ENTROPY_GATE','CROSS_HORIZON_BAYES',
    'DIRICHLET_VOM','SEQUENTIAL_CHANGE','MOTIF_SURVIVAL',
    'REGIME_POSTERIOR','MULTIRESOLUTION_EDGE','BAYES_RUN_MIXTURE',
    'CTW_APPROX','HIERARCHICAL_BAYES','TRANSITION_DRIFT','RUN_CONTEXT_JOINT','SPECTRAL_LAG','ROBUST_STACK',
    'SUFFIX_CONTEXT','FUSION_CORE'
)

BOARD_META_PROFILES = {
    'hitclub:hu':   {'mode':'champion','top_k':1,'wf_depth':160,'reverse_min':28,'reverse_gap':.16},
    'hitclub:md5':  {'mode':'champion','top_k':1,'wf_depth':160,'reverse_min':28,'reverse_gap':.16},
    'sunwin:hu':    {'mode':'consensus','top_k':4,'wf_depth':220,'reverse_min':34,'reverse_gap':.18,
                     'prefer':('CTW_APPROX','HIERARCHICAL_BAYES','ROBUST_STACK','MARKOV_ORDER2','CROSS_HORIZON_BAYES','SUFFIX_CONTEXT')},
    'sunwin:sicbo': {'mode':'consensus','top_k':5,'wf_depth':240,'reverse_min':40,'reverse_gap':.22,
                     'prefer':('REGIME_ADAPTIVE','DECAYED_TRANSITION','RUN_LENGTH_MARKOV','FLIP_STATE_MARKOV',
                               'MOTIF_WEIGHTED','PERIODIC_MATCH','MARKOV_ORDER2','RUN_HAZARD','SUFFIX_CONTEXT','FUSION_CORE',
                               'REFERENCE_PATTERN_PRIOR','JS_BREAK_CALIBRATOR','JS_ULTRA_STACK','CHANGEPOINT_ADAPTIVE','WILSON_CONTEXT','KNN_RECENCY','CROSS_HORIZON_BAYES')},
    'lc79:hu':      {'mode':'consensus','top_k':4,'wf_depth':220,'reverse_min':34,'reverse_gap':.18,
                     'prefer':('CTW_APPROX','ROBUST_STACK','RUN_CONTEXT_JOINT','MARKOV_ORDER2','CROSS_HORIZON_BAYES','SUFFIX_CONTEXT')},
    'lc79:md5':     {'mode':'consensus','top_k':4,'wf_depth':240,'reverse_min':34,'reverse_gap':.18,
                     'prefer':('HIERARCHICAL_BAYES','CTW_APPROX','ROBUST_STACK','SUFFIX_CONTEXT','HIGH_ORDER_MARKOV','MARKOV_ORDER2')},
    'lc79:xocdia':  {'mode':'consensus','top_k':3,'wf_depth':200,'reverse_min':36,'reverse_gap':.20,
                     'prefer':('ROBUST_STACK','RUN_CONTEXT_JOINT','CTW_APPROX','MARKOV_ORDER2','RUN_HAZARD','SUFFIX_CONTEXT')},
    'gb68:hu':      {'mode':'consensus','top_k':3,'wf_depth':180,'reverse_min':32,'reverse_gap':.19},
    'gb68:md5':     {'mode':'consensus','top_k':4,'wf_depth':220,'reverse_min':34,'reverse_gap':.18,
                     'prefer':('SUFFIX_CONTEXT','MARKOV_ORDER2','HIGH_ORDER_MARKOV','FUSION_CORE')},
    'betvip:hu':    {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'betvip:md5':   {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'b52:hu':       {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'b52:md5':      {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'max789:hu':    {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'max789:md5':   {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'son789:hu':    {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
    'son789:md5':   {'mode':'consensus','top_k':3,'wf_depth':160,'reverse_min':32,'reverse_gap':.20},
}

_WF_CACHE={}

def _profile_for(board):
    if board in BOARD_META_PROFILES:return BOARD_META_PROFILES[board]
    if str(board).startswith('baccarat:'):
        return {'mode':'consensus','top_k':5,'wf_depth':260,'reverse_min':42,'reverse_gap':.22,
                'prefer':('BAYES_CONTEXT','REGIME_SWITCH','ANALOG_KNN','CONTEXT_ENTROPY','RUN_SURVIVAL',
                          'HORIZON_CONSENSUS','LAG_ENSEMBLE','REGIME_ADAPTIVE','DECAYED_TRANSITION','MOTIF_WEIGHTED','MARKOV_ORDER2','CHANGEPOINT_ADAPTIVE','WILSON_CONTEXT','KNN_RECENCY','ENTROPY_GATE','CROSS_HORIZON_BAYES','FUSION_CORE')}
    return {'mode':'consensus','top_k':3,'wf_depth':170,'reverse_min':34,'reverse_gap':.20}

def _opp(side):
    return 'XỈU' if side=='TÀI' else 'TÀI'

def _seq(rows):
    return [r.get('result') for r in rows if r.get('result') in ('TÀI','XỈU')]

def _run_len(seq):
    if not seq: return 0
    n=1
    for i in range(len(seq)-2,-1,-1):
        if seq[i]==seq[-1]: n+=1
        else: break
    return n

def _markov_prediction(seq, order=1):
    if not seq: return 'TÀI'
    order=max(1,min(4,int(order)))
    if len(seq)<=order+2: return _opp(seq[-1])
    ctx=tuple(seq[-order:]); t=x=1.0
    for i in range(order,len(seq)):
        if tuple(seq[i-order:i])!=ctx: continue
        if seq[i]=='TÀI': t+=1
        else: x+=1
    return 'TÀI' if t>=x else 'XỈU'

def _suffix_prediction(seq):
    if not seq: return 'TÀI'
    for L in (6,5,4,3,2):
        if len(seq)<=L: continue
        motif=tuple(seq[-L:]); t=x=0
        for i in range(L,len(seq)):
            if tuple(seq[i-L:i])!=motif: continue
            if seq[i]=='TÀI': t+=1
            else: x+=1
        if t+x>=2: return 'TÀI' if t>=x else 'XỈU'
    return _markov_prediction(seq,1)

def _recent_final_stats(board,limit=50):
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute(
            '''SELECT prediction,actual,ok,model_json
               FROM shared_predictions
               WHERE board=? AND actual IS NOT NULL AND ok IS NOT NULL
               ORDER BY settled_at DESC LIMIT ?''',(board,int(limit))
        ).fetchall()
    out=[]
    for pred,actual,ok,mj in rows:
        try: model=json.loads(mj) if mj else {}
        except: model={}
        out.append({'prediction':pred,'actual':actual,'ok':bool(ok),'model':model})
    return out

def _anti_phase(board):
    hist=_recent_final_stats(board,20)
    anti_tai=anti_xiu=wrong=0
    for h in hist:
        if h['ok']: continue
        wrong+=1
        raw=(h.get('model') or {}).get('raw_prediction') or h.get('prediction')
        if raw=='TÀI': anti_xiu+=1
        elif raw=='XỈU': anti_tai+=1
    return {'wrong_rate':wrong/max(1,len(hist)),'anti_tai':anti_tai,'anti_xiu':anti_xiu,'sample':len(hist)}

def _run_hazard_prediction(seq):
    if not seq: return 'TÀI'
    side=seq[-1]; cur=_run_len(seq)
    follow=brk=1.0
    for i in range(1,len(seq)):
        if seq[i-1]!=side: continue
        rl=1; j=i-2
        while j>=0 and seq[j]==side and rl<8:
            rl+=1; j-=1
        if abs(rl-cur)>1: continue
        if seq[i]==side: follow+=1
        else: brk+=1
    return side if follow>=brk else _opp(side)

def _multi_window_prediction(seq):
    if not seq: return 'TÀI'
    vote=0.0
    for w,weight in ((8,1.0),(16,1.15),(32,1.3),(64,1.1)):
        q=seq[-w:]
        if not q: continue
        p=q.count('TÀI')/len(q)
        if p>=.68: vote-=weight
        elif p>=.54: vote+=weight
        elif p<=.32: vote+=weight
        elif p<=.46: vote-=weight
    if abs(vote)<.1: return _markov_prediction(seq,2)
    return 'TÀI' if vote>0 else 'XỈU'

def _decayed_transition_prediction(seq,order=2,decay=.955):
    if not seq:return 'TÀI'
    order=max(1,min(4,int(order)))
    if len(seq)<=order+3:return _markov_prediction(seq,order)
    ctx=tuple(seq[-order:]);t=x=.7
    for i in range(order,len(seq)):
        if tuple(seq[i-order:i])!=ctx:continue
        age=(len(seq)-1)-i;w=decay**age
        if seq[i]=='TÀI':t+=w
        else:x+=w
    return 'TÀI' if t>=x else 'XỈU'

def _motif_weighted_prediction(seq):
    if not seq:return 'TÀI'
    vt=vx=0.0
    for L in (2,3,4,5,6):
        if len(seq)<=L+1:continue
        motif=tuple(seq[-L:])
        for i in range(L,len(seq)):
            if tuple(seq[i-L:i])!=motif:continue
            age=(len(seq)-1)-i;w=(1.0+.20*L)*(.965**age)
            if seq[i]=='TÀI':vt+=w
            else:vx+=w
    if vt+vx<1.2:return _markov_prediction(seq,2)
    return 'TÀI' if vt>=vx else 'XỈU'

def _regime_adaptive_prediction(seq):
    if not seq:return 'TÀI'
    q=seq[-24:];last=q[-1];run=_run_len(q)
    flips=sum(1 for i in range(1,len(q)) if q[i]!=q[i-1])/max(1,len(q)-1);p=q.count('TÀI')/len(q)
    if flips>=.70:return _opp(last)
    if run>=3:return _run_hazard_prediction(seq)
    if p>=.70:return 'XỈU'
    if p<=.30:return 'TÀI'
    if p>=.57:return 'TÀI'
    if p<=.43:return 'XỈU'
    return _decayed_transition_prediction(seq,2)

def _flip_state_markov_prediction(seq):
    if not seq:return 'TÀI'
    if len(seq)<8:return _markov_prediction(seq,1)
    state='F' if seq[-1]!=seq[-2] else 'R'
    tai=xiu=1.2
    for i in range(2,len(seq)):
        st='F' if seq[i-1]!=seq[i-2] else 'R'
        if st!=state:continue
        w=.965**((len(seq)-1)-i)
        if seq[i]=='TÀI':tai+=w
        else:xiu+=w
    return 'TÀI' if tai>=xiu else 'XỈU'

def _run_length_markov_prediction(seq):
    if not seq:return 'TÀI'
    if len(seq)<10:return _run_hazard_prediction(seq)
    side=seq[-1];target=min(_run_len(seq),6)
    follow=brk=1.25
    for i in range(2,len(seq)):
        prev=seq[i-1]
        if prev!=side:continue
        rl=1;j=i-2
        while j>=0 and seq[j]==prev and rl<6:
            rl+=1;j-=1
        if abs(rl-target)>1:continue
        w=.97**((len(seq)-1)-i)
        if seq[i]==side:follow+=w
        else:brk+=w
    return side if follow>=brk else _opp(side)

def _periodic_match_prediction(seq):
    if not seq:return 'TÀI'
    n=len(seq)
    if n<18:return _markov_prediction(seq,2)
    best_lag=None;best=-1.0
    q=seq[-min(70,n):]
    for lag in range(2,min(13,len(q)//3+1)):
        hit=tot=0
        for i in range(lag,len(q)):
            tot+=1
            if q[i]==q[i-lag]:hit+=1
        if tot<10:continue
        rate=(hit+2.5)/(tot+5)
        score=rate-(.008 if lag<=3 else 0)
        if score>best:best=score;best_lag=lag
    return seq[-best_lag] if best_lag else _markov_prediction(seq,2)

def _dual_horizon_prediction(seq):
    if not seq:return 'TÀI'
    q8=seq[-8:];q28=seq[-28:]
    p8=q8.count('TÀI')/max(1,len(q8));p28=q28.count('TÀI')/max(1,len(q28))
    short=p8-.5;long=p28-.5
    if short*long>0 and abs(short)>=.08:return 'TÀI' if short>0 else 'XỈU'
    if abs(short-long)>=.28:return 'XỈU' if short>0 else 'TÀI'
    return _decayed_transition_prediction(seq,2)

def _analog_knn_prediction(seq):
    if not seq:return 'TÀI'
    n=len(seq)
    if n<24:return _markov_prediction(seq,2)
    vt=vx=0.0
    for L in (4,5,6,7,8):
        if n<=L+2:continue
        cur=seq[-L:]
        for i in range(L,n-1):
            past=seq[i-L:i]
            sim=sum(1 for a,b in zip(cur,past) if a==b)/L
            if sim<.75:continue
            age=(n-1)-i
            w=(sim**3)*(0.97**age)*(1+.06*L)
            nxt=seq[i]
            if nxt=='TÀI':vt+=w
            else:vx+=w
    if vt+vx<1.0:return _suffix_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _run_survival_prediction(seq):
    if not seq:return 'TÀI'
    side=seq[-1];cur=min(_run_len(seq),8)
    runs=[];rside=seq[0];length=1
    for x in seq[1:]:
        if x==rside:length+=1
        else:
            runs.append((rside,length));rside=x;length=1
    same=[l for sd,l in runs if sd==side and l>=cur]
    if len(same)<3:return _run_length_markov_prediction(seq)
    survive=sum(1 for l in same if l>=cur+1)
    p=(survive+2)/(len(same)+4)
    return side if p>=.52 else _opp(side)

def _context_entropy_prediction(seq):
    if not seq:return 'TÀI'
    best=None
    for order in (1,2,3,4):
        if len(seq)<order+12:continue
        ctx=tuple(seq[-order:]);t=x=1.5;sample=0
        for i in range(order,len(seq)):
            if tuple(seq[i-order:i])!=ctx:continue
            w=.97**((len(seq)-1)-i)
            if seq[i]=='TÀI':t+=w
            else:x+=w
            sample+=1
        if sample<3:continue
        p=t/(t+x)
        ent=0.0
        for z in (p,1-p):
            if z>0:ent-=z*math.log2(z)
        strength=abs(p-.5)*(1-ent*.35)*min(1,sample/10)
        cand=(strength,'TÀI' if p>=.5 else 'XỈU')
        if best is None or cand[0]>best[0]:best=cand
    return best[1] if best else _decayed_transition_prediction(seq,2)

def _bayes_context_prediction(seq):
    if not seq:return 'TÀI'
    vt=vx=0.0
    for order,ow in ((1,.7),(2,1.0),(3,1.25),(4,1.45),(5,1.6)):
        if len(seq)<order+6:continue
        ctx=tuple(seq[-order:]);t=x=2.0;sample=0
        for i in range(order,len(seq)):
            if tuple(seq[i-order:i])!=ctx:continue
            age=(len(seq)-1)-i;w=.972**age
            if seq[i]=='TÀI':t+=w
            else:x+=w
            sample+=1
        if sample<2:continue
        p=t/(t+x);strength=abs(p-.5)*min(1.0,sample/10)*ow
        if p>=.5:vt+=strength
        else:vx+=strength
    if vt+vx<.04:return _decayed_transition_prediction(seq,2)
    return 'TÀI' if vt>=vx else 'XỈU'

def _horizon_consensus_prediction(seq):
    if not seq:return 'TÀI'
    vote=0.0
    for w,wt in ((6,1.35),(10,1.25),(20,1.10),(40,.90),(80,.70)):
        q=seq[-w:]
        if len(q)<4:continue
        p=q.count('TÀI')/len(q);edge=p-.5
        if abs(edge)<.04:continue
        vote+=wt*edge*2
    if abs(vote)<.12:return _markov_prediction(seq,2)
    return 'TÀI' if vote>0 else 'XỈU'

def _regime_switch_prediction(seq):
    if not seq:return 'TÀI'
    q=seq[-32:];last=q[-1];run=_run_len(q)
    flips=sum(1 for i in range(1,len(q)) if q[i]!=q[i-1])/max(1,len(q)-1)
    p=q.count('TÀI')/len(q)
    if flips>=.68:return _opp(last)
    if flips<=.32 and run>=2:return _run_survival_prediction(seq)
    if abs(p-.5)>=.18:return _multi_window_prediction(seq)
    a=_bayes_context_prediction(seq);b=_decayed_transition_prediction(seq,3);c=_motif_weighted_prediction(seq)
    return a if a==b or a==c else b if b==c else _markov_prediction(seq,2)

def _lag_ensemble_prediction(seq):
    if not seq:return 'TÀI'
    n=len(seq)
    if n<24:return _periodic_match_prediction(seq)
    vt=vx=0.0
    for lag in range(2,min(16,n//3+1)):
        hit=tot=0
        start=max(lag,n-90)
        for i in range(start,n):
            tot+=1;hit+=1 if seq[i]==seq[i-lag] else 0
        if tot<10:continue
        rate=(hit+3)/(tot+6);edge=rate-.5
        if abs(edge)<.035:continue
        pred=seq[-lag] if edge>0 else _opp(seq[-lag])
        w=abs(edge)*(1.0/(1+.035*lag))
        if pred=='TÀI':vt+=w
        else:vx+=w
    if vt+vx<.035:return _periodic_match_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _vom_context6_prediction(seq):
    if not seq:return 'TÀI'
    vt=vx=0.0;n=len(seq)
    for order,ow in ((2,.8),(3,1.0),(4,1.18),(5,1.35),(6,1.50),(7,1.60),(8,1.68)):
        if n<order+12:continue
        ctx=tuple(seq[-order:]);t=x=1.8;support=0.0
        for i in range(order,n):
            if tuple(seq[i-order:i])!=ctx:continue
            age=(n-1)-i;w=.5**(age/260.0)
            support+=w
            if seq[i]=='TÀI':t+=w
            else:x+=w
        if support<2.0:continue
        p=t/(t+x);edge=(p-.5)*2.0
        weight=ow*min(1.0,support/18.0)*min(1.0,abs(edge)*3.0+.15)
        if p>=.5:vt+=weight*max(.05,abs(edge))
        else:vx+=weight*max(.05,abs(edge))
    if vt+vx<.05:return _bayes_context_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _long_memory_bayes_prediction(seq):
    if not seq:return 'TÀI'
    q=seq[-min(len(seq),MAX_HISTORY):];n=len(q);vt=vx=0.0
    for order,ow in ((1,.55),(2,.75),(3,1.0),(4,1.2),(5,1.35),(6,1.48)):
        if n<order+20:continue
        ctx=tuple(q[-order:]);t=x=3.0;support=0.0
        for i in range(order,n):
            if tuple(q[i-order:i])!=ctx:continue
            age=(n-1)-i;w=.5**(age/520.0)
            support+=w
            if q[i]=='TÀI':t+=w
            else:x+=w
        if support<3:continue
        p=t/(t+x);edge=(p-.5)*2
        rel=(1-math.exp(-support/25.0))*ow
        if p>=.5:vt+=rel*abs(edge)
        else:vx+=rel*abs(edge)
    if vt+vx<.035:return _decayed_transition_prediction(seq,3)
    return 'TÀI' if vt>=vx else 'XỈU'

def _run_profile_long_prediction(seq):
    if not seq:return 'TÀI'
    q=seq[-min(len(seq),MAX_HISTORY):];side=q[-1];cur=min(_run_len(q),12)
    same=brk=1.5;support=0
    for i in range(2,len(q)):
        prev=q[i-1];rl=1;j=i-2
        while j>=0 and q[j]==prev and rl<12:
            rl+=1;j-=1
        if prev!=side or abs(rl-cur)>1:continue
        age=(len(q)-1)-i;w=.5**(age/650.0);support+=1
        if q[i]==prev:same+=w
        else:brk+=w
    if support<6:return _run_survival_prediction(seq)
    return side if same>=brk else _opp(side)

def _multiscale_transition_prediction(seq):
    if not seq:return 'TÀI'
    votes=[]
    for w,wt in ((32,1.40),(64,1.30),(128,1.18),(256,1.04),(512,.90),(1000,.78),(2000,.66),(5000,.52),(10000,.40)):
        q=seq[-w:]
        if len(q)<min(24,w):continue
        a=_decayed_transition_prediction(q,2,.972 if w<=128 else .988)
        b=_markov_prediction(q,3)
        pred=a if a==b else _bayes_context_prediction(q)
        votes.append((pred,wt))
    if not votes:return _markov_prediction(seq,2)
    vt=sum(w for p,w in votes if p=='TÀI');vx=sum(w for p,w in votes if p=='XỈU')
    return 'TÀI' if vt>=vx else 'XỈU'

def _regime_label(seq):
    if not seq:return 'EMPTY'
    q=list(seq[-48:])
    if len(q)<8:return 'SHORT'
    flips=sum(1 for i in range(1,len(q)) if q[i]!=q[i-1])/max(1,len(q)-1)
    p=q.count('TÀI')/len(q);run=_run_len(q)
    if run>=4:return 'RUN'
    if flips>=.68:return 'ALT'
    if flips<=.30:return 'STICKY'
    if p>=.66:return 'BIAS_T'
    if p<=.34:return 'BIAS_X'
    if flips>=.56:return 'VOLATILE'
    return 'BALANCED'

def _majority3(a,b,c):
    if a==b or a==c:return a
    if b==c:return b
    return b

def _changepoint_adaptive_prediction(seq):
    if not seq:return 'TÀI'
    if len(seq)<36:return _regime_switch_prediction(seq)
    r=seq[-16:]; old=seq[-48:-16] if len(seq)>=48 else seq[:-16]
    pr=r.count('TÀI')/len(r);po=old.count('TÀI')/max(1,len(old))
    fr=sum(1 for i in range(1,len(r)) if r[i]!=r[i-1])/max(1,len(r)-1)
    fo=sum(1 for i in range(1,len(old)) if old[i]!=old[i-1])/max(1,len(old)-1)
    shift=abs(pr-po)+.65*abs(fr-fo)
    if shift>=.28:
        q=seq[-48:]
        return _majority3(_decayed_transition_prediction(q,2,.94),
                          _bayes_context_prediction(q),
                          _regime_switch_prediction(q))
    return _majority3(_long_memory_bayes_prediction(seq),
                      _multiscale_transition_prediction(seq),
                      _bayes_context_prediction(seq))

def _wilson_lower(wins,total,z=1.2816):
    if total<=0:return .0
    p=wins/total;z2=z*z
    den=1+z2/total
    centre=p+z2/(2*total)
    spread=z*math.sqrt(max(0.0,p*(1-p)/total+z2/(4*total*total)))
    return (centre-spread)/den

def _wilson_context_prediction(seq):
    if not seq:return 'TÀI'
    n=len(seq);best=None
    for order in range(2,10):
        if n<order+12:continue
        ctx=tuple(seq[-order:]);t=x=0
        for i in range(order,n):
            if tuple(seq[i-order:i])!=ctx:continue
            if seq[i]=='TÀI':t+=1
            else:x+=1
        total=t+x
        if total<4:continue
        maj=max(t,x);side='TÀI' if t>=x else 'XỈU'
        lower=_wilson_lower(maj,total)
        edge=(maj/total)-.5
        score=(lower-.5)*min(1.0,total/28.0)*(1+.06*order)+edge*.12
        cand=(score,total,order,side)
        if best is None or cand[:3]>best[:3]:best=cand
    if not best or best[0]<=.002:return _bayes_context_prediction(seq)
    return best[3]

def _knn_recency_prediction(seq):
    if not seq:return 'TÀI'
    n=len(seq)
    if n<32:return _analog_knn_prediction(seq)
    candidates=[]
    for L in (5,6,8,10,12):
        if n<=L+3:continue
        cur=seq[-L:]
        for i in range(L,n-1):
            past=seq[i-L:i]
            sim=sum(1 for a,b in zip(cur,past) if a==b)/L
            if sim<.70:continue
            age=(n-1)-i
            w=(sim**4)*(0.5**(age/360.0))*(1+.035*L)
            candidates.append((w,seq[i]))
    if not candidates:return _analog_knn_prediction(seq)
    candidates.sort(reverse=True,key=lambda z:z[0]);candidates=candidates[:48]
    vt=sum(w for w,p in candidates if p=='TÀI');vx=sum(w for w,p in candidates if p=='XỈU')
    if vt+vx<.9:return _analog_knn_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _run_matrix_prediction(seq):
    if not seq:return 'TÀI'
    side=seq[-1];cur=min(_run_len(seq),6);same=brk=2.0;support=0.0
    n=len(seq)
    for i in range(2,n):
        prev=seq[i-1];rl=1;j=i-2
        while j>=0 and seq[j]==prev and rl<6:
            rl+=1;j-=1
        if prev!=side or min(rl,6)!=cur:continue
        age=(n-1)-i;w=.5**(age/420.0);support+=w
        if seq[i]==prev:same+=w
        else:brk+=w
    if support<3.0:return _run_profile_long_prediction(seq)
    return side if same>=brk else _opp(side)

def _structure_score(seq):
    """Estimate persistent non-IID structure; used only to calibrate confidence.
    A low score does not change the side prediction, it only prevents a random
    hot streak among many strategies from being displayed as a strong signal.
    """
    q=list(seq[-min(len(seq),800):])
    n=len(q)
    if n<80:return .22
    p=q.count('TÀI')/n
    bias=abs(p-.5)*2
    # First-order transition dependence.
    tt=tx=xt=xx=1.0
    for a,b in zip(q[:-1],q[1:]):
        if a=='TÀI' and b=='TÀI':tt+=1
        elif a=='TÀI':tx+=1
        elif b=='TÀI':xt+=1
        else:xx+=1
    pt_t=tt/(tt+tx);pt_x=xt/(xt+xx)
    trans=abs(pt_t-pt_x)
    # Maximum lag correlation, shrunk for multiple lags.
    vals=[1 if x=='TÀI' else -1 for x in q]
    lag_best=0.0
    for lag in range(1,13):
        a=vals[lag:];b=vals[:-lag]
        if len(a)<50:continue
        ma=sum(a)/len(a);mb=sum(b)/len(b)
        va=sum((x-ma)**2 for x in a);vb=sum((x-mb)**2 for x in b)
        if va<=0 or vb<=0:continue
        corr=abs(sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb))
        lag_best=max(lag_best,corr)
    lag_signal=max(0.0,lag_best-0.055)*2.6
    # Order-2 conditional concentration. The 0.08 dead-zone absorbs normal sampling noise.
    ctx_edges=[]
    for ctx in (('TÀI','TÀI'),('TÀI','XỈU'),('XỈU','TÀI'),('XỈU','XỈU')):
        t=x=2.0;support=0
        for i in range(2,n):
            if tuple(q[i-2:i])!=ctx:continue
            support+=1
            if q[i]=='TÀI':t+=1
            else:x+=1
        if support>=20:ctx_edges.append(abs(t/(t+x)-.5)*2)
    ctx=max(ctx_edges,default=0.0)
    ctx_signal=max(0.0,ctx-.08)*1.45
    # Stability: true structure should appear in both halves, not only one hot patch.
    def half_features(h):
        if len(h)<40:return (0.0,0.0)
        ph=h.count('TÀI')/len(h);fl=sum(1 for i in range(1,len(h)) if h[i]!=h[i-1])/max(1,len(h)-1)
        return abs(ph-.5)*2,abs(fl-.5)*2
    h1=half_features(q[:n//2]);h2=half_features(q[n//2:])
    stable=1-min(1.0,abs(h1[0]-h2[0])+abs(h1[1]-h2[1]))
    raw=.24*bias+.28*trans+.25*lag_signal+.23*ctx_signal
    return _clamp(raw*(.72+.28*stable),0,1)

def _entropy_gate_prediction(seq):
    if not seq:return 'TÀI'
    q32=seq[-32:];q128=seq[-128:]
    h32=_entropy(q32);h128=_entropy(q128)
    flips=sum(1 for i in range(1,len(q32)) if q32[i]!=q32[i-1])/max(1,len(q32)-1)
    p32=q32.count('TÀI')/max(1,len(q32));p128=q128.count('TÀI')/max(1,len(q128))
    if h32<.78 and _run_len(q32)>=3:return _run_matrix_prediction(seq)
    if flips>=.70:return _opp(q32[-1])
    if abs(p32-.5)>=.16 and abs(p128-.5)>=.08 and (p32-.5)*(p128-.5)>0:
        return 'TÀI' if p32>.5 else 'XỈU'
    if h32-h128>=.10:return _changepoint_adaptive_prediction(seq)
    return _wilson_context_prediction(seq)

def _cross_horizon_bayes_prediction(seq):
    if not seq:return 'TÀI'
    vt=vx=0.0
    for w,wt in ((24,1.35),(48,1.22),(96,1.08),(192,.92),(384,.78),(768,.64),(1500,.50),(3000,.38)):
        q=seq[-w:]
        if len(q)<min(20,w):continue
        a=_bayes_context_prediction(q);b=_decayed_transition_prediction(q,3,.965 if w<=96 else .986)
        pred=a if a==b else _wilson_context_prediction(q)
        # stable horizons receive more influence; heavily imbalanced horizons are shrunk
        p=q.count('TÀI')/len(q);stability=1-min(.35,abs(p-.5)*.7)
        ww=wt*stability
        if pred=='TÀI':vt+=ww
        else:vx+=ww
    if vt+vx<.5:return _bayes_context_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

REFERENCE_PATTERN_COUNTS = {'TT': (678, 606),
 'TX': (597, 642),
 'XT': (610, 628),
 'XX': (637, 613),
 'TTT': (348, 328),
 'TTX': (282, 324),
 'TXT': (298, 299),
 'TXX': (322, 316),
 'XTT': (330, 277),
 'XTX': (313, 316),
 'XXT': (309, 328),
 'XXX': (313, 297),
 'TTTT': (179, 169),
 'TTTX': (154, 174),
 'TTXT': (145, 137),
 'TTXX': (170, 153),
 'TXTT': (165, 132),
 'TXTX': (156, 144),
 'TXXT': (149, 173),
 'TXXX': (156, 157),
 'XTTT': (169, 159),
 'XTTX': (127, 150),
 'XTXT': (151, 162),
 'XTXX': (151, 162),
 'XXTT': (163, 145),
 'XXTX': (157, 171),
 'XXXT': (159, 154),
 'XXXX': (157, 140),
 'TTTTT': (91, 88),
 'TTTTX': (78, 91),
 'TTTXT': (79, 75),
 'TTTXX': (86, 87),
 'TTXTT': (88, 56),
 'TTXTX': (70, 68),
 'TTXXT': (71, 99),
 'TTXXX': (67, 83),
 'TXTTT': (82, 81),
 'TXTTX': (60, 72),
 'TXTXT': (79, 77),
 'TXTXX': (66, 78),
 'TXXTT': (92, 57),
 'TXXTX': (84, 89),
 'TXXXT': (84, 72),
 'TXXXX': (78, 79),
 'XTTTT': (88, 81),
 'XTTTX': (76, 83),
 'XTTXT': (66, 61),
 'XTTXX': (84, 66),
 'XTXTT': (76, 75),
 'XTXTX': (86, 76),
 'XTXXT': (77, 74),
 'XTXXX': (88, 74),
 'XXTTT': (87, 76),
 'XXTTX': (67, 78),
 'XXTXT': (72, 85),
 'XXTXX': (84, 84),
 'XXXTT': (70, 88),
 'XXXTX': (72, 82),
 'XXXXT': (75, 82),
 'XXXXX': (79, 61),
 'TTTTTT': (46, 45),
 'TTTTTX': (41, 47),
 'TTTTXT': (36, 42),
 'TTTTXX': (39, 52),
 'TTTXTT': (42, 36),
 'TTTXTX': (38, 37),
 'TTTXXT': (37, 49),
 'TTTXXX': (42, 44),
 'TTXTTT': (41, 45),
 'TTXTTX': (27, 29),
 'TTXTXT': (36, 34),
 'TTXTXX': (32, 36),
 'TTXXTT': (48, 23),
 'TTXXTX': (51, 48),
 'TTXXXT': (35, 32),
 'TTXXXX': (36, 47),
 'TXTTTT': (43, 39),
 'TXTTTX': (36, 45),
 'TXTTXT': (30, 30),
 'TXTTXX': (39, 33),
 'TXTXTT': (33, 46),
 'TXTXTX': (36, 41),
 'TXTXXT': (32, 34),
 'TXTXXX': (38, 40),
 'TXXTTT': (51, 41),
 'TXXTTX': (22, 35),
 'TXXTXT': (38, 46),
 'TXXTXX': (37, 50),
 'TXXXTT': (36, 47),
 'TXXXTX': (35, 37),
 'TXXXXT': (34, 44),
 'TXXXXX': (45, 34),
 'XTTTTT': (45, 43),
 'XTTTTX': (37, 44),
 'XTTTXT': (43, 33),
 'XTTTXX': (47, 35),
 'XTTXTT': (46, 20),
 'XTTXTX': (32, 30),
 'XTTXXT': (34, 50),
 'XTTXXX': (25, 39),
 'XTXTTT': (41, 35),
 'XTXTTX': (32, 43),
 'XTXTXT': (43, 43),
 'XTXTXX': (34, 42),
 'XTXXTT': (43, 34),
 'XTXXTX': (33, 41),
 'XTXXXT': (48, 40),
 'XTXXXX': (42, 32),
 'XXTTTT': (45, 42),
 'XXTTTX': (40, 36),
 'XXTTXT': (36, 31),
 'XXTTXX': (45, 33),
 'XXTXTT': (43, 29),
 'XXTXTX': (50, 35),
 'XXTXXT': (44, 40),
 'XXTXXX': (50, 34),
 'XXXTTT': (35, 35),
 'XXXTTX': (45, 43),
 'XXXTXT': (34, 38),
 'XXXTXX': (47, 34),
 'XXXXTT': (34, 41),
 'XXXXTX': (37, 45),
 'XXXXXT': (41, 38),
 'XXXXXX': (34, 27),
 'TTTTTTT': (26, 20),
 'TTTTTTX': (21, 24),
 'TTTTTXT': (20, 21),
 'TTTTTXX': (20, 27),
 'TTTTXTT': (16, 20),
 'TTTTXTX': (23, 19),
 'TTTTXXT': (19, 20),
 'TTTTXXX': (24, 28),
 'TTTXTTT': (18, 23),
 'TTTXTTX': (19, 17),
 'TTTXTXT': (23, 15),
 'TTTXTXX': (16, 21),
 'TTTXXTT': (23, 14),
 'TTTXXTX': (24, 25),
 'TTTXXXT': (23, 19),
 'TTTXXXX': (19, 25),
 'TTXTTTT': (20, 21),
 'TTXTTTX': (24, 21),
 'TTXTTXT': (12, 15),
 'TTXTTXX': (15, 14),
 'TTXTXTT': (12, 24),
 'TTXTXTX': (16, 18),
 'TTXTXXT': (16, 16),
 'TTXTXXX': (11, 25),
 'TTXXTTT': (28, 20),
 'TTXXTTX': (12, 11),
 'TTXXTXT': (23, 28),
 'TTXXTXX': (19, 28),
 'TTXXXTT': (12, 22),
 'TTXXXTX': (16, 16),
 'TTXXXXT': (15, 21),
 'TTXXXXX': (26, 21),
 'TXTTTTT': (22, 21),
 'TXTTTTX': (19, 20),
 'TXTTTXT': (22, 14),
 'TXTTTXX': (24, 21),
 'TXTTXTT': (23, 7),
 'TXTTXTX': (18, 12),
 'TXTTXXT': (16, 23),
 'TXTTXXX': (13, 19),
 'TXTXTTT': (17, 16),
 'TXTXTTX': (24, 22),
 'TXTXTXT': (18, 18),
 'TXTXTXX': (18, 23),
 'TXTXXTT': (16, 16),
 'TXTXXTX': (15, 19),
 'TXTXXXT': (22, 16),
 'TXTXXXX': (25, 15),
 'TXXTTTT': (23, 28),
 'TXXTTTX': (22, 19),
 'TXXTTXT': (10, 12),
 'TXXTTXX': (21, 14),
 'TXXTXTT': (21, 17),
 'TXXTXTX': (26, 20),
 'TXXTXXT': (18, 19),
 'TXXTXXX': (29, 21),
 'TXXXTTT': (17, 19),
 'TXXXTTX': (24, 23),
 'TXXXTXT': (13, 22),
 'TXXXTXX': (19, 17),
 'TXXXXTT': (16, 18),
 'TXXXXTX': (21, 23),
 'TXXXXXT': (19, 26),
 'TXXXXXX': (18, 16),
 'XTTTTTT': (20, 25),
 'XTTTTTX': (20, 23),
 'XTTTTXT': (16, 21),
 'XTTTTXX': (19, 25),
 'XTTTXTT': (26, 16),
 'XTTTXTX': (15, 18),
 'XTTTXXT': (18, 29),
 'XTTTXXX': (18, 16),
 'XTTXTTT': (23, 22),
 'XTTXTTX': (8, 12),
 'XTTXTXT': (13, 19),
 'XTTXTXX': (16, 14),
 'XTTXXTT': (25, 9),
 'XTTXXTX': (27, 23),
 'XTTXXXT': (12, 13),
 'XTTXXXX': (17, 22),
 'XTXTTTT': (23, 18),
 'XTXTTTX': (12, 23),
 'XTXTTXT': (17, 15),
 'XTXTTXX': (24, 19),
 'XTXTXTT': (21, 22),
 'XTXTXTX': (20, 23),
 'XTXTXXT': (16, 18),
 'XTXTXXX': (27, 15),
 'XTXXTTT': (23, 20),
 'XTXXTTX': (10, 24),
 'XTXXTXT': (15, 18),
 'XTXXTXX': (18, 22),
 'XTXXXTT': (23, 25),
 'XTXXXTX': (19, 21),
 'XTXXXXT': (19, 23),
 'XTXXXXX': (19, 13),
 'XXTTTTT': (23, 22),
 'XXTTTTX': (18, 24),
 'XXTTTXT': (21, 19),
 'XXTTTXX': (22, 13),
 'XXTTXTT': (23, 13),
 'XXTTXTX': (14, 18),
 'XXTTXXT': (18, 27),
 'XXTTXXX': (12, 20),
 'XXTXTTT': (24, 19),
 'XXTXTTX': (8, 21),
 'XXTXTXT': (25, 25),
 'XXTXTXX': (16, 19),
 'XXTXXTT': (26, 18),
 'XXTXXTX': (18, 22),
 'XXTXXXT': (26, 24),
 'XXTXXXX': (17, 17),
 'XXXTTTT': (22, 13),
 'XXXTTTX': (18, 17),
 'XXXTTXT': (26, 19),
 'XXXTTXX': (24, 19),
 'XXXTXTT': (22, 12),
 'XXXTXTX': (24, 14),
 'XXXTXXT': (26, 21),
 'XXXTXXX': (21, 13),
 'XXXXTTT': (18, 16),
 'XXXXTTX': (21, 20),
 'XXXXTXT': (21, 16),
 'XXXXTXX': (28, 17),
 'XXXXXTT': (18, 23),
 'XXXXXTX': (16, 22),
 'XXXXXXT': (22, 12),
 'XXXXXXX': (16, 11),
 'TTTTTTTT': (14, 12),
 'TTTTTTTX': (8, 12),
 'TTTTTTXT': (10, 11),
 'TTTTTTXX': (10, 14),
 'TTTTTXTT': (8, 12),
 'TTTTTXTX': (11, 10),
 'TTTTTXXT': (11, 9),
 'TTTTTXXX': (12, 15),
 'TTTTXTTT': (8, 7),
 'TTTTXTTX': (9, 11),
 'TTTTXTXT': (15, 8),
 'TTTTXTXX': (12, 7),
 'TTTTXXTT': (13, 6),
 'TTTTXXTX': (8, 12),
 'TTTTXXXT': (11, 13),
 'TTTTXXXX': (13, 15),
 'TTTXTTTT': (8, 10),
 'TTTXTTTX': (11, 12),
 'TTTXTTXT': (9, 10),
 'TTTXTTXX': (8, 9),
 'TTTXTXTT': (6, 17),
 'TTTXTXTX': (8, 7),
 'TTTXTXXT': (7, 9),
 'TTTXTXXX': (7, 14),
 'TTTXXTTT': (14, 9),
 'TTTXXTTX': (7, 7),
 'TTTXXTXT': (15, 9),
 'TTTXXTXX': (10, 14),
 'TTTXXXTT': (10, 12),
 'TTTXXXTX': (7, 12),
 'TTTXXXXT': (10, 9),
 'TTTXXXXX': (12, 13),
 'TTXTTTTT': (9, 11),
 'TTXTTTTX': (10, 11),
 'TTXTTTXT': (17, 7),
 'TTXTTTXX': (11, 10),
 'TTXTTXTT': (8, 4),
 'TTXTTXTX': (10, 5),
 'TTXTTXXT': (7, 8),
 'TTXTTXXX': (8, 6),
 'TTXTXTTT': (6, 6),
 'TTXTXTTX': (13, 11),
 'TTXTXTXT': (7, 9),
 'TTXTXTXX': (8, 10),
 'TTXTXXTT': (8, 8),
 'TTXTXXTX': (9, 7),
 'TTXTXXXT': (5, 6),
 'TTXTXXXX': (17, 8),
 'TTXXTTTT': (14, 14),
 'TTXXTTTX': (8, 12),
 'TTXXTTXT': (3, 9),
 'TTXXTTXX': (8, 3),
 'TTXXTXTT': (14, 9),
 'TTXXTXTX': (15, 13),
 'TTXXTXXT': (7, 12),
 'TTXXTXXX': (17, 11),
 'TTXXXTTT': (4, 8),
 'TTXXXTTX': (13, 9),
 'TTXXXTXT': (8, 8),
 'TTXXXTXX': (7, 8),
 'TTXXXXTT': (5, 10),
 'TTXXXXTX': (9, 12),
 'TTXXXXXT': (12, 14),
 'TTXXXXXX': (11, 10),
 'TXTTTTTT': (9, 13),
 'TXTTTTTX': (9, 12),
 'TXTTTTXT': (6, 13),
 'TXTTTTXX': (8, 12),
 'TXTTTXTT': (11, 10),
 'TXTTTXTX': (6, 8),
 'TXTTTXXT': (10, 14),
 'TXTTTXXX': (8, 12),
 'TXTTXTTT': (12, 10),
 'TXTTXTTX': (3, 4),
 'TXTTXTXT': (7, 11),
 'TXTTXTXX': (6, 6),
 'TXTTXXTT': (12, 4),
 'TXTTXXTX': (13, 10),
 'TXTTXXXT': (5, 8),
 'TXTTXXXX': (10, 9),
 'TXTXTTTT': (9, 8),
 'TXTXTTTX': (8, 8),
 'TXTXTTXT': (12, 12),
 'TXTXTTXX': (12, 10),
 'TXTXTXTT': (7, 11),
 'TXTXTXTX': (8, 10),
 'TXTXTXXT': (4, 14),
 'TXTXTXXX': (13, 10),
 'TXTXXTTT': (7, 9),
 'TXTXXTTX': (5, 11),
 'TXTXXTXT': (8, 7),
 'TXTXXTXX': (10, 9),
 'TXTXXXTT': (8, 14),
 'TXTXXXTX': (11, 5),
 'TXTXXXXT': (12, 13),
 'TXTXXXXX': (7, 8),
 'TXXTTTTT': (12, 11),
 'TXXTTTTX': (12, 16),
 'TXXTTTXT': (11, 11),
 'TXXTTTXX': (12, 7),
 'TXXTTXTT': (4, 6),
 'TXXTTXTX': (8, 5),
 'TXXTTXXT': (7, 14),
 'TXXTTXXX': (6, 8),
 'TXXTXTTT': (16, 5),
 'TXXTXTTX': (6, 11),
 'TXXTXTXT': (11, 15),
 'TXXTXTXX': (10, 10),
 'TXXTXXTT': (12, 6),
 'TXXTXXTX': (9, 10),
 'TXXTXXXT': (13, 16),
 'TXXTXXXX': (9, 12),
 'TXXXTTTT': (9, 8),
 'TXXXTTTX': (8, 11),
 'TXXXTTXT': (15, 9),
 'TXXXTTXX': (14, 9),
 'TXXXTXTT': (6, 7),
 'TXXXTXTX': (12, 10),
 'TXXXTXXT': (8, 11),
 'TXXXTXXX': (10, 7),
 'TXXXXTTT': (8, 8),
 'TXXXXTTX': (8, 10),
 'TXXXXTXT': (13, 8),
 'TXXXXTXX': (18, 5),
 'TXXXXXTT': (8, 11),
 'TXXXXXTX': (10, 16),
 'TXXXXXXT': (14, 4),
 'TXXXXXXX': (12, 4),
 'XTTTTTTT': (12, 8),
 'XTTTTTTX': (13, 12),
 'XTTTTTXT': (10, 10),
 'XTTTTTXX': (10, 13),
 'XTTTTXTT': (8, 8),
 'XTTTTXTX': (12, 9),
 'XTTTTXXT': (8, 11),
 'XTTTTXXX': (12, 13),
 'XTTTXTTT': (10, 16),
 'XTTTXTTX': (10, 6),
 'XTTTXTXT': (8, 7),
 'XTTTXTXX': (4, 14),
 'XTTTXXTT': (10, 8),
 'XTTTXXTX': (16, 13),
 'XTTTXXXT': (12, 6),
 'XTTTXXXX': (6, 10),
 'XTTXTTTT': (12, 11),
 'XTTXTTTX': (13, 9),
 'XTTXTTXT': (3, 5),
 'XTTXTTXX': (7, 5),
 'XTTXTXTT': (6, 7),
 'XTTXTXTX': (8, 11),
 'XTTXTXXT': (9, 7),
 'XTTXTXXX': (4, 10),
 'XTTXXTTT': (14, 11),
 'XTTXXTTX': (5, 4),
 'XTTXXTXT': (8, 19),
 'XTTXXTXX': (9, 14),
 'XTTXXXTT': (2, 10),
 'XTTXXXTX': (9, 4),
 'XTTXXXXT': (5, 12),
 'XTTXXXXX': (14, 8),
 'XTXTTTTT': (13, 10),
 'XTXTTTTX': (9, 9),
 'XTXTTTXT': (5, 7),
 'XTXTTTXX': (13, 10),
 'XTXTTXTT': (14, 3),
 'XTXTTXTX': (8, 7),
 'XTXTTXXT': (9, 15),
 'XTXTTXXX': (5, 13),
 'XTXTXTTT': (11, 10),
 'XTXTXTTX': (11, 11),
 'XTXTXTXT': (11, 9),
 'XTXTXTXX': (10, 13),
 'XTXTXXTT': (8, 8),
 'XTXTXXTX': (6, 12),
 'XTXTXXXT': (17, 10),
 'XTXTXXXX': (8, 7),
 'XTXXTTTT': (9, 14),
 'XTXXTTTX': (13, 7),
 'XTXXTTXT': (7, 3),
 'XTXXTTXX': (13, 11),
 'XTXXTXTT': (7, 8),
 'XTXXTXTX': (11, 7),
 'XTXXTXXT': (11, 7),
 'XTXXTXXX': (12, 10),
 'XTXXXTTT': (13, 10),
 'XTXXXTTX': (11, 14),
 'XTXXXTXT': (5, 14),
 'XTXXXTXX': (12, 9),
 'XTXXXXTT': (11, 8),
 'XTXXXXTX': (12, 11),
 'XTXXXXXT': (7, 12),
 'XTXXXXXX': (7, 6),
 'XXTTTTTT': (11, 12),
 'XXTTTTTX': (11, 11),
 'XXTTTTXT': (10, 8),
 'XXTTTTXX': (11, 13),
 'XXTTTXTT': (15, 6),
 'XXTTTXTX': (9, 10),
 'XXTTTXXT': (7, 15),
 'XXTTTXXX': (9, 4),
 'XXTTXTTT': (11, 12),
 'XXTTXTTX': (5, 8),
 'XXTTXTXT': (6, 8),
 'XXTTXTXX': (10, 8),
 'XXTTXXTT': (13, 5),
 'XXTTXXTX': (14, 13),
 'XXTTXXXT': (7, 5),
 'XXTTXXXX': (7, 13),
 'XXTXTTTT': (14, 10),
 'XXTXTTTX': (4, 15),
 'XXTXTTXT': (5, 3),
 'XXTXTTXX': (12, 9),
 'XXTXTXTT': (14, 11),
 'XXTXTXTX': (12, 13),
 'XXTXTXXT': (12, 4),
 'XXTXTXXX': (14, 5),
 'XXTXXTTT': (15, 11),
 'XXTXXTTX': (5, 13),
 'XXTXXTXT': (7, 11),
 'XXTXXTXX': (8, 13),
 'XXTXXXTT': (15, 11),
 'XXTXXXTX': (8, 16),
 'XXTXXXXT': (7, 10),
 'XXTXXXXX': (12, 5),
 'XXXTTTTT': (11, 11),
 'XXXTTTTX': (6, 7),
 'XXXTTTXT': (10, 8),
 'XXXTTTXX': (10, 6),
 'XXXTTXTT': (19, 7),
 'XXXTTXTX': (6, 13),
 'XXXTTXXT': (11, 13),
 'XXXTTXXX': (6, 12),
 'XXXTXTTT': (8, 14),
 'XXXTXTTX': (2, 10),
 'XXXTXTXT': (14, 10),
 'XXXTXTXX': (6, 8),
 'XXXTXXTT': (14, 12),
 'XXXTXXTX': (9, 12),
 'XXXTXXXT': (13, 8),
 'XXXTXXXX': (8, 5),
 'XXXXTTTT': (13, 5),
 'XXXXTTTX': (10, 6),
 'XXXXTTXT': (11, 10),
 'XXXXTTXX': (10, 10),
 'XXXXTXTT': (16, 5),
 'XXXXTXTX': (12, 4),
 'XXXXTXXT': (18, 10),
 'XXXXTXXX': (11, 6),
 'XXXXXTTT': (10, 8),
 'XXXXXTTX': (13, 10),
 'XXXXXTXT': (8, 8),
 'XXXXXTXX': (10, 12),
 'XXXXXXTT': (10, 12),
 'XXXXXXTX': (6, 6),
 'XXXXXXXT': (8, 8),
 'XXXXXXXX': (4, 7)}

def _reference_allowed(board):
    # Source is Tài/Xỉu-oriented. Do not transfer it to Baccarat or Xóc Đĩa semantics.
    return bool(board) and not str(board).startswith('baccarat:') and str(board) != 'lc79:xocdia'

def _reference_pattern_signal(seq):
    if not seq:
        return {'ready':False,'prediction':'TÀI','score':0.0,'support':0,'length':0,'p_tai':.5}
    tx=''.join('T' if x=='TÀI' else 'X' for x in seq[-8:])
    num=den=0.0; best_support=0; best_len=0; best_p=.5; used=[]
    for L in range(min(8,len(tx)),1,-1):
        key=tx[-L:]; pair=REFERENCE_PATTERN_COUNTS.get(key)
        if not pair: continue
        t,x=pair; support=t+x
        min_support=4 if L>=7 else 5 if L>=5 else 7
        if support<min_support: continue
        # Beta smoothing: conflict-heavy patterns remain near 50/50.
        p=(t+3.0)/(support+6.0); edge=(p-.5)*2.0
        reliability=(1-math.exp(-support/14.0))*((L/8.0)**1.35)
        # Small edges should not dominate just because support is large.
        w=reliability*(.38+.62*min(1.0,abs(edge)*2.4))
        num+=edge*w; den+=w
        used.append((L,key,support,p,edge,w))
        if L>best_len or (L==best_len and support>best_support):
            best_len=L;best_support=support;best_p=p
    if den<=0:
        pred=_markov_prediction(seq,2)
        return {'ready':False,'prediction':pred,'score':0.0,'support':0,'length':0,'p_tai':.5}
    score=_clamp(num/den,-.72,.72)
    pred='TÀI' if score>=0 else 'XỈU'
    return {'ready':True,'prediction':pred,'score':round(score,4),'support':best_support,'length':best_len,
            'p_tai':round((score+1)/2,4),'best_p_tai':round(best_p,4),'contexts':len(used)}

def _reference_pattern_prediction(seq):
    return _reference_pattern_signal(seq).get('prediction') or _markov_prediction(seq,2)

def _js_randomness_score(seq):
    # Port of the useful part of JS model8: change ratio + balance + entropy.
    q=list(seq[-15:])
    if len(q)<10:return .5
    changes=sum(1 for i in range(1,len(q)) if q[i]!=q[i-1])
    change_ratio=changes/max(1,len(q)-1)
    t=q.count('TÀI');x=len(q)-t;distribution=abs(t-x)/len(q)
    p=t/len(q); ent=0.0
    for z in (p,1-p):
        if z>0:ent-=z*math.log2(z)
    return _clamp(change_ratio*.4+(1-distribution)*.3+ent*.3,0,1)

def _js_break_signal(seq):
    # Combines streak break rate, same-length run survival and recent break behaviour.
    if not seq:return {'prediction':'TÀI','p_break':.5,'support':0,'run':0}
    side=seq[-1];cur=max(1,min(_run_len(seq),8))
    opportunities=breaks=0
    for i in range(4,len(seq)):
        prev=seq[i-1];rl=1;j=i-2
        while j>=0 and seq[j]==prev and rl<8:
            rl+=1;j-=1
        if rl<3 or abs(rl-cur)>1:continue
        opportunities+=1
        if seq[i]!=prev:breaks+=1
    # Recent evidence gets a smaller adaptive component.
    ro=rb=0
    for i in range(max(4,len(seq)-18),len(seq)):
        prev=seq[i-1];rl=1;j=i-2
        while j>=0 and seq[j]==prev and rl<8:
            rl+=1;j-=1
        if rl<3:continue
        ro+=1;rb+=1 if seq[i]!=prev else 0
    p_global=(breaks+3)/(opportunities+6)
    p_recent=(rb+2)/(ro+4) if ro else .5
    # Longer current runs raise break pressure only mildly; history remains dominant.
    length_prior=_clamp(.42+.035*max(0,cur-2),.42,.68)
    p=_clamp(.55*p_global+.25*p_recent+.20*length_prior,.18,.82)
    pred=_opp(side) if p>=.54 else side
    return {'prediction':pred,'p_break':round(p,4),'support':opportunities,'run':cur}

def _js_break_calibrator_prediction(seq):
    return _js_break_signal(seq)['prediction']

def _js_trend_blend_prediction(seq):
    # JS model2/3/4/15 distilled into a causal, non-recursive predictor.
    if not seq:return 'TÀI'
    short=seq[-5:];long=seq[-20:];q12=seq[-12:]
    def edge(q):return (q.count('TÀI')-q.count('XỈU'))/max(1,len(q))
    es=edge(short);el=edge(long);e12=edge(q12)
    trend=('TÀI' if (es+el)>=0 else 'XỈU')
    trend_strength=.62*abs(es)+.38*abs(el)
    # Mean reversion only activates on a clearly imbalanced W12.
    meanrev=_opp('TÀI' if e12>0 else 'XỈU') if abs(e12)>=.34 else None
    br=_js_break_signal(seq)
    vt=vx=0.0
    def add(pred,w):
        nonlocal vt,vx
        if pred=='TÀI':vt+=w
        elif pred=='XỈU':vx+=w
    add(trend,.85+trend_strength)
    if meanrev:add(meanrev,.55+abs(e12)*.55)
    add(br['prediction'],.62+abs(br['p_break']-.5)*1.1)
    # Short momentum vote.
    s3=seq[-3:];add('TÀI' if s3.count('TÀI')>=2 else 'XỈU',.62)
    return 'TÀI' if vt>=vx else 'XỈU'

def _js_ultra_stack_prediction(seq, use_reference=True):
    # Performance selection is handled by BOARD_META; this is the local JS-inspired stack.
    if not seq:return 'TÀI'
    rnd=_js_randomness_score(seq)
    signals=[
        (_js_trend_blend_prediction(seq),1.00),
        (_js_break_calibrator_prediction(seq),.95),
        (_bayes_context_prediction(seq),1.10),
        (_context_entropy_prediction(seq),.92),
        (_regime_switch_prediction(seq),1.00),
    ]
    if use_reference:
        rs=_reference_pattern_signal(seq)
        if rs.get('ready'):
            rw=(.55+min(.55,abs(float(rs.get('score',0)))*.9))*(.65 if rnd>.72 else 1.0)
            signals.append((rs['prediction'],rw))
    # On bad/random runs, shrink pattern/trend concentration by giving adaptive context more say.
    if rnd>.72:
        signals += [(_multi_window_prediction(seq),.72),(_markov_prediction(seq,2),.78)]
    vt=vx=0.0
    for pred,w in signals:
        if pred=='TÀI':vt+=w
        else:vx+=w
    return 'TÀI' if vt>=vx else 'XỈU'

def _dirichlet_vom_prediction(seq):
    """Variable-order Markov 1..10 with Dirichlet smoothing + recency evidence."""
    if not seq:return 'TÀI'
    n=len(seq); vt=vx=0.0
    max_order=min(10,max(1,n//5))
    for order in range(1,max_order+1):
        if n<=order+3:continue
        ctx=tuple(seq[-order:]);t=x=1.8;ev=0.0
        half=max(28.0,72.0-order*3.0)
        for i in range(order,n):
            if tuple(seq[i-order:i])!=ctx:continue
            age=(n-1)-i;w=.5**(age/half)
            if seq[i]=='TÀI':t+=w
            else:x+=w
            ev+=w
        if ev<1.1:continue
        edge=(t-x)/(t+x)
        evidence=(1-math.exp(-ev/4.0))*min(1.35,.72+.075*order)
        if edge>=0:vt+=abs(edge)*evidence
        else:vx+=abs(edge)*evidence
    if vt+vx<.025:return _markov_prediction(seq,2)
    return 'TÀI' if vt>=vx else 'XỈU'

def _sequential_change_prediction(seq):
    """Detect distribution/transition drift and shorten memory after a change."""
    if not seq:return 'TÀI'
    n=len(seq)
    if n<36:return _decayed_transition_prediction(seq,2)
    def feats(q):
        if len(q)<3:return (0.5,0.5,0.5)
        pt=q.count('TÀI')/len(q)
        same=sum(1 for i in range(1,len(q)) if q[i]==q[i-1])/max(1,len(q)-1)
        return pt,same,1-same
    recent=seq[-24:]; older=seq[-104:-24] if n>=104 else seq[:-24]
    fr=feats(recent);fo=feats(older)
    drift=sum(abs(a-b) for a,b in zip(fr,fo))/3.0
    if drift>=.17:return _regime_switch_prediction(seq[-80:])
    if drift>=.10:
        a=_changepoint_adaptive_prediction(seq);b=_dirichlet_vom_prediction(seq[-220:])
        return a if a==b else _decayed_transition_prediction(seq,2)
    return _dirichlet_vom_prediction(seq)

def _motif_survival_prediction(seq):
    """Suffix matching 3..12 with Beta smoothing, age decay and support weighting."""
    if not seq:return 'TÀI'
    n=len(seq);vt=vx=0.0
    for L in range(3,min(12,n-4)+1):
        motif=tuple(seq[-L:]);t=x=1.4;ev=0.0
        for i in range(L,n):
            if tuple(seq[i-L:i])!=motif:continue
            age=(n-1)-i;w=.5**(age/max(36.0,92.0-L*3.0))
            if seq[i]=='TÀI':t+=w
            else:x+=w
            ev+=w
        if ev<1.0:continue
        edge=(t-x)/(t+x)
        strength=(1-math.exp(-ev/3.6))*(.66+.055*L)
        if edge>=0:vt+=abs(edge)*strength
        else:vx+=abs(edge)*strength
    if vt+vx<.02:return _suffix_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _regime_posterior_prediction(seq):
    """Soft mixture over run / alternating / biased / mixed regimes."""
    if not seq:return 'TÀI'
    q=seq[-64:];run=_run_len(q)
    flips=sum(1 for i in range(1,len(q)) if q[i]!=q[i-1])/max(1,len(q)-1)
    bias=abs(q.count('TÀI')-q.count('XỈU'))/max(1,len(q));h=_entropy(q)
    prun=math.exp(2.0*min(1,run/5)+1.4*max(0,.48-flips))
    palt=math.exp(3.0*max(0,flips-.52))
    pbias=math.exp(4.0*max(0,bias-.12))
    pmix=math.exp(1.8*max(0,h-.84));z=prun+palt+pbias+pmix
    votes=[(_run_hazard_prediction(seq),prun/z),(_opp(seq[-1]),palt/z),
           (_multi_window_prediction(seq),pbias/z),(_bayes_context_prediction(seq),pmix/z)]
    vt=sum(w for p,w in votes if p=='TÀI');vx=sum(w for p,w in votes if p=='XỈU')
    return 'TÀI' if vt>=vx else 'XỈU'

def _multiresolution_edge_prediction(seq):
    """Shrinked edge over 8..1024 horizons."""
    if not seq:return 'TÀI'
    n=len(seq);vt=vx=0.0
    for k,wsize in enumerate((8,16,32,64,128,256,512,1024)):
        if n<min(8,wsize):continue
        q=seq[-min(n,wsize):];m=len(q);raw=(q.count('TÀI')-q.count('XỈU'))/m
        shr=raw*(m/(m+18.0));wt=(1.18/(1+.18*k))*(.72+.28*min(1,m/128))
        if shr>=0:vt+=abs(shr)*wt
        else:vx+=abs(shr)*wt
    if vt+vx<.02:return _multi_window_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _bayes_run_mixture_prediction(seq):
    """Hierarchical continuation/break model by side and run length, blended with context."""
    if not seq:return 'TÀI'
    side=seq[-1];cur=min(_run_len(seq),12);cont=brk=2.0
    for i in range(1,len(seq)):
        prev=seq[i-1];rl=1;j=i-2
        while j>=0 and seq[j]==prev and rl<12:
            rl+=1;j-=1
        if prev!=side:continue
        d=abs(rl-cur)
        if d>2:continue
        w=(1.0,.62,.34)[d];age=(len(seq)-1)-i;w*=.5**(age/180.0)
        if seq[i]==side:cont+=w
        else:brk+=w
    pcont=cont/(cont+brk);run_pred=side if pcont>=.5 else _opp(side);ctx=_dirichlet_vom_prediction(seq)
    if abs(pcont-.5)>=.12:return run_pred
    return run_pred if run_pred==ctx else _regime_posterior_prediction(seq)

def _confidence_bucket_calibration(board, proposed):
    """Historical guardrail for displayed signal strength; not a win-probability estimate."""
    try:
        with sqlite3.connect(DB_PATH) as db:
            rows=db.execute('SELECT ok,model_json FROM shared_predictions WHERE board=? AND actual IS NOT NULL AND ok IS NOT NULL ORDER BY settled_at DESC LIMIT 320',(board,)).fetchall()
    except Exception:
        return {'sample':0,'bayes':.5,'cap':72.0,'bonus':0.0}
    target=float(proposed)
    def bucket(width):
        vals=[]
        for ok,mj in rows:
            try:m=json.loads(mj) if mj else {}
            except Exception:m={}
            c=m.get('model_confidence',m.get('confidence'))
            if isinstance(c,(int,float)) and abs(float(c)-target)<=width:vals.append(bool(ok))
        return vals
    vals=bucket(6.0)
    if len(vals)<16:vals=bucket(10.0)
    n=len(vals);wins=sum(vals);bayes=(wins+8*.5)/(n+8) if n else .5;cap=72.0;bonus=0.0
    if n>=18:
        if bayes<.45:cap=54.0
        elif bayes<.49:cap=57.0
        elif bayes<.52:cap=61.0
        elif bayes<.55:cap=66.0
        elif bayes>.59 and n>=30:bonus=1.0
    return {'sample':n,'bayes':round(bayes,4),'cap':cap,'bonus':bonus}

def _ctx_prob_weighted(seq, order, max_scan=6000):
    """Recency-weighted Beta-smoothed P(TÀI | context)."""
    n=len(seq)
    if n<=order:return .5,0.0
    ctx=tuple(seq[-order:]); t=x=0.0; support=0.0
    start=max(order,n-max_scan)
    tau=max(120.0,min(1800.0,max_scan/2.2))
    for i in range(start,n):
        if tuple(seq[i-order:i])!=ctx:continue
        age=n-i
        w=math.exp(-age/tau)
        support+=w
        if seq[i]=='TÀI':t+=w
        else:x+=w
    p=(t+2.0)/(t+x+4.0)
    return p,support

def _ctw_approx_prediction(seq):
    if len(seq)<8:return _markov_prediction(seq,1)
    logit=0.0;den=0.0
    for k in range(1,min(12,len(seq)-1)+1):
        p,sup=_ctx_prob_weighted(seq,k)
        if sup<.8:continue
        strength=abs(p-.5)*2
        w=(1.0+k*.16)*(sup/(sup+5.0))*(.25+.75*strength)
        logit+=(p-.5)*w;den+=w
    if den<=0:return _bayes_context_prediction(seq)
    return 'TÀI' if logit>=0 else 'XỈU'

def _hierarchical_bayes_prediction(seq):
    if len(seq)<10:return _markov_prediction(seq,1)
    base=(seq[-512:].count('TÀI')+6)/(len(seq[-512:])+12)
    p=base
    # Higher orders update the posterior only when they have evidence.
    for k in range(1,min(10,len(seq)-1)+1):
        pk,sup=_ctx_prob_weighted(seq,k,5000)
        shrink=sup/(sup+7.0+1.8*k)
        p=(1-shrink)*p+shrink*pk
    return 'TÀI' if p>=.5 else 'XỈU'

def _transition_drift_prediction(seq):
    if len(seq)<12:return _markov_prediction(seq,1)
    last=seq[-1]
    def p_for(window):
        q=seq[-window:];a=b=0.0
        for i in range(1,len(q)):
            if q[i-1]!=last:continue
            # mild recency emphasis
            w=.55+.45*(i/max(1,len(q)-1))
            if q[i]=='TÀI':a+=w
            else:b+=w
        return (a+2)/(a+b+4),a+b
    vals=[]
    for w in (24,64,160,512,1600):
        if len(seq)>=min(12,w//2):vals.append(p_for(w))
    if not vals:return _markov_prediction(seq,1)
    longp=vals[-1][0];score=0.0;den=0.0
    for idx,(p,sup) in enumerate(vals):
        rec=(len(vals)-idx)/len(vals)
        drift=abs(p-longp)
        wt=(sup/(sup+8))*(1.15 if idx==0 and drift>.12 else 1.0)*(.75+.5*rec)
        score+=(p-.5)*wt;den+=wt
    return 'TÀI' if score>=0 else 'XỈU'

def _run_context_joint_prediction(seq):
    if len(seq)<12:return _run_hazard_prediction(seq)
    last=seq[-1];run=min(_run_len(seq),8)
    t=x=0.0;n=len(seq)
    for i in range(4,n):
        # run length ending at i-1
        r=1
        j=i-2
        while j>=0 and seq[j]==seq[i-1] and r<8:
            r+=1;j-=1
        if seq[i-1]!=last or min(r,8)!=run:continue
        # joint state: same side/run + last two flip states where possible
        curflip=(seq[-1]!=seq[-2]); histflip=(seq[i-1]!=seq[i-2])
        if curflip!=histflip:continue
        w=math.exp(-(n-i)/900.0)
        if seq[i]=='TÀI':t+=w
        else:x+=w
    if t+x<2.0:return _bayes_run_mixture_prediction(seq)
    p=(t+2)/(t+x+4)
    return 'TÀI' if p>=.5 else 'XỈU'

def _spectral_lag_prediction(seq):
    q=seq[-768:]
    if len(q)<24:return _periodic_match_prediction(seq)
    vt=vx=0.0
    for lag in range(2,min(40,len(q)//3)+1):
        matches=sum(1 for i in range(lag,len(q)) if q[i]==q[i-lag])
        total=len(q)-lag
        if total<18:continue
        rate=(matches+4*.5)/(total+4)
        edge=abs(rate-.5)
        if edge<.025:continue
        pred=q[-lag] if rate>=.5 else _opp(q[-lag])
        wt=edge*math.sqrt(total)/(1+.035*lag)
        if pred=='TÀI':vt+=wt
        else:vx+=wt
    if vt+vx<=0:return _lag_ensemble_prediction(seq)
    return 'TÀI' if vt>=vx else 'XỈU'

def _robust_stack_prediction(seq):
    experts=[
        _ctw_approx_prediction(seq),_hierarchical_bayes_prediction(seq),
        _transition_drift_prediction(seq),_run_context_joint_prediction(seq),
        _spectral_lag_prediction(seq),_dirichlet_vom_prediction(seq),
        _cross_horizon_bayes_prediction(seq),_regime_posterior_prediction(seq),
        _entropy_gate_prediction(seq),_bayes_run_mixture_prediction(seq)
    ]
    t=experts.count('TÀI');x=len(experts)-t
    if t==x:return _ctw_approx_prediction(seq)
    return 'TÀI' if t>x else 'XỈU'

def _pure_strategy_predictions(seq, board=None):
    """Causal predictors dùng riêng để walk-forward, không đọc future/DB feedback."""
    if not seq:return {}
    last=seq[-1];run=_run_len(seq);q6=seq[-6:]
    flips=sum(1 for i in range(1,len(q6)) if q6[i]!=q6[i-1]);alt=flips/max(1,len(q6)-1)
    p20=seq[-20:].count('TÀI')/max(1,len(seq[-20:]));p12=seq[-12:].count('TÀI')/max(1,len(seq[-12:]))
    return {
      'FOLLOW_LAST':last,'REVERSE_LAST':_opp(last),
      'ALTERNATING_PATTERN':_opp(last) if alt>=.60 else _markov_prediction(seq,1),
      'RUN_BREAK':_opp(last) if run>=3 else _markov_prediction(seq,1),
      'RUN_FOLLOW':last if 2<=run<=3 else (_opp(last) if run>=5 else _markov_prediction(seq,1)),
      'BIAS_MEAN_REVERSION':'XỈU' if p20>=.60 else 'TÀI' if p20<=.40 else _opp(last),
      'BIAS_MOMENTUM':'TÀI' if p12>=.58 else 'XỈU' if p12<=.42 else last,
      'MARKOV_TRANSITION':_markov_prediction(seq,1),
      'HIGH_ORDER_MARKOV':_markov_prediction(seq,3),
      'MARKOV_ORDER2':_markov_prediction(seq,2),
      'RUN_HAZARD':_run_hazard_prediction(seq),
      'MULTI_WINDOW':_multi_window_prediction(seq),
      'DECAYED_TRANSITION':_decayed_transition_prediction(seq,2),
      'REGIME_ADAPTIVE':_regime_adaptive_prediction(seq),
      'MOTIF_WEIGHTED':_motif_weighted_prediction(seq),
      'FLIP_STATE_MARKOV':_flip_state_markov_prediction(seq),
      'RUN_LENGTH_MARKOV':_run_length_markov_prediction(seq),
      'PERIODIC_MATCH':_periodic_match_prediction(seq),
      'DUAL_HORIZON':_dual_horizon_prediction(seq),
      'ANALOG_KNN':_analog_knn_prediction(seq),
      'RUN_SURVIVAL':_run_survival_prediction(seq),
      'CONTEXT_ENTROPY':_context_entropy_prediction(seq),
      'BAYES_CONTEXT':_bayes_context_prediction(seq),
      'HORIZON_CONSENSUS':_horizon_consensus_prediction(seq),
      'REGIME_SWITCH':_regime_switch_prediction(seq),
      'LAG_ENSEMBLE':_lag_ensemble_prediction(seq),
      'REFERENCE_PATTERN_PRIOR':_reference_pattern_prediction(seq) if _reference_allowed(board) else _bayes_context_prediction(seq),
      'JS_TREND_BLEND':_js_trend_blend_prediction(seq),
      'JS_BREAK_CALIBRATOR':_js_break_calibrator_prediction(seq),
      'JS_ULTRA_STACK':_js_ultra_stack_prediction(seq,_reference_allowed(board)),
      'VOM_CONTEXT_6':_vom_context6_prediction(seq),
      'LONG_MEMORY_BAYES':_long_memory_bayes_prediction(seq),
      'RUN_PROFILE_LONG':_run_profile_long_prediction(seq),
      'MULTISCALE_TRANSITION':_multiscale_transition_prediction(seq),
      'CHANGEPOINT_ADAPTIVE':_changepoint_adaptive_prediction(seq),
      'WILSON_CONTEXT':_wilson_context_prediction(seq),
      'KNN_RECENCY':_knn_recency_prediction(seq),
      'RUN_MATRIX':_run_matrix_prediction(seq),
      'ENTROPY_GATE':_entropy_gate_prediction(seq),
      'CROSS_HORIZON_BAYES':_cross_horizon_bayes_prediction(seq),
      'DIRICHLET_VOM':_dirichlet_vom_prediction(seq),
      'SEQUENTIAL_CHANGE':_sequential_change_prediction(seq),
      'MOTIF_SURVIVAL':_motif_survival_prediction(seq),
      'REGIME_POSTERIOR':_regime_posterior_prediction(seq),
      'MULTIRESOLUTION_EDGE':_multiresolution_edge_prediction(seq),
      'BAYES_RUN_MIXTURE':_bayes_run_mixture_prediction(seq),
      'CTW_APPROX':_ctw_approx_prediction(seq),
      'HIERARCHICAL_BAYES':_hierarchical_bayes_prediction(seq),
      'TRANSITION_DRIFT':_transition_drift_prediction(seq),
      'RUN_CONTEXT_JOINT':_run_context_joint_prediction(seq),
      'SPECTRAL_LAG':_spectral_lag_prediction(seq),
      'ROBUST_STACK':_robust_stack_prediction(seq),
      'SUFFIX_CONTEXT':_suffix_prediction(seq)
    }

def _bayes_rate(wins,total,prior_n=14,prior_p=.5):
    return (wins+prior_n*prior_p)/max(1,total+prior_n)

def walk_forward_strategy_stats(board,rows):
    profile=_profile_for(board); seq_all=_seq(rows); last_id=str(rows[-1].get('id')) if rows else ''
    recent_depth=max(int(profile.get('wf_depth',170)),260)
    sparse_span=min(1100,max(recent_depth+120,int(math.sqrt(max(1,len(seq_all)))*34)))
    key=(board,last_id,len(seq_all),recent_depth,sparse_span,'v49')
    if key in _WF_CACHE:return _WF_CACHE[key]
    seq=seq_all[-min(len(seq_all),sparse_span+80):]
    names=[n for n in STRATEGY_NAMES if n not in ('ANTI_RAW','FUSION_CORE')]
    rec={n:[] for n in names};recent_start=max(24,len(seq)-recent_depth);old_start=max(24,len(seq)-sparse_span)
    indices=sorted(set(list(range(old_start,recent_start,6))+list(range(recent_start,len(seq)))))
    for i in indices:
        hist=seq[:i];actual=seq[i];reg=_regime_label(hist);preds=_pure_strategy_predictions(hist,board);is_recent=i>=recent_start
        for n in names:
            pr=preds.get(n)
            if pr in ('TÀI','XỈU'):rec[n].append((pr==actual,reg,is_recent))
    current_reg=_regime_label(seq);out={}
    for n,vals in rec.items():
        def st(items):
            q=[bool(x[0] if isinstance(x,tuple) else x) for x in items];total=len(q);wins=sum(q);raw=wins/total if total else .5
            num=den=0.0
            for age,ok in enumerate(reversed(q)):
                w=.5**(age/14.0);den+=w;num+=w*(1.0 if ok else 0.0)
            ewma=num/den if den else .5
            return {'total':total,'win':wins,'loss':total-wins,'win_rate':_bayes_rate(wins,total),'raw_win_rate':raw,'ewma':ewma,'lower':_wilson_lower(wins,total) if total else .0}
        recent_vals=[x for x in vals if len(x)<3 or x[2]]
        s20=st(recent_vals[-20:]);s50=st(recent_vals[-50:]);s100=st(recent_vals[-100:]);s200=st(vals[-200:]);s400=st(vals[-400:])
        rv=[x for x in vals if isinstance(x,tuple) and x[1]==current_reg][-80:];rs=st(rv)
        rates=[x['win_rate'] for x in (s20,s50,s100,s200) if x['total']>=10];stability=1-(max(rates)-min(rates) if len(rates)>=2 else .12)
        score=.34*s20['win_rate']+.23*s50['win_rate']+.14*s100['win_rate']+.10*s200['win_rate']+.07*s400['win_rate']+.12*s20['ewma']
        if rs['total']>=8:score+=.08*(rs['win_rate']-.5)
        score+=.05*(stability-.8)
        if s20['total']<14:score-=.025
        if s50['total']<32:score-=.020
        out[n]={'short':s20,'mid':s50,'long':s100,'xl':s200,'xxl':s400,'regime':rs,'regime_name':current_reg,'stability':round(stability,4),'score':round(score,5),'samples':len(vals),'recent_samples':len(recent_vals),'wf_span':len(seq),'wf_sparse_stride':6}
    _WF_CACHE.clear();_WF_CACHE[key]=out
    return out

def _combined_quality(board,name,live,wf):
    ls=live.get(name,{});ws=wf.get(name,{})
    l20=ls.get('short',{});l50=ls.get('mid',{});w20=ws.get('short',{});w50=ws.get('mid',{});w100=ws.get('long',{})
    ln=int(l20.get('total',0));wn=int(w20.get('total',0))
    lw=min(.52,ln/44*.52);ww=1-lw
    l20r=_bayes_rate(int(l20.get('win',0)),int(l20.get('total',0)),12,.5)
    l50r=_bayes_rate(int(l50.get('win',0)),int(l50.get('total',0)),18,.5)
    lr=.58*l20r+.42*l50r
    wxl=ws.get('xl',{});wxxl=ws.get('xxl',{})
    wr=.34*float(w20.get('win_rate',.5))+.22*float(w50.get('win_rate',.5))+.12*float(w100.get('win_rate',.5))
    wr+=.08*float(wxl.get('win_rate',.5))+.05*float(wxxl.get('win_rate',.5))
    wr+=.12*float(w20.get('ewma',.5))+.07*max(.42,float(w20.get('lower',.0)))
    q=lw*lr+ww*wr
    rs=ws.get('regime',{})
    if int(rs.get('total',0))>=8:q+=.10*(float(rs.get('win_rate',.5))-.5)
    stability=float(ws.get('stability',.88))
    if stability<.78:q-=.030
    elif stability>.92:q+=.012
    if name in _profile_for(board).get('prefer',()):q+=.012
    imported={'REFERENCE_PATTERN_PRIOR','JS_TREND_BLEND','JS_BREAK_CALIBRATOR','JS_ULTRA_STACK'}
    newv47={'CHANGEPOINT_ADAPTIVE','WILSON_CONTEXT','KNN_RECENCY','RUN_MATRIX','ENTROPY_GATE','CROSS_HORIZON_BAYES'}
    newv48={'DIRICHLET_VOM','SEQUENTIAL_CHANGE','MOTIF_SURVIVAL','REGIME_POSTERIOR','MULTIRESOLUTION_EDGE','BAYES_RUN_MIXTURE'}
    newv49={'CTW_APPROX','HIERARCHICAL_BAYES','TRANSITION_DRIFT','RUN_CONTEXT_JOINT','SPECTRAL_LAG','ROBUST_STACK'}
    if name in imported and int(ws.get('samples',0))<42:q-=.040
    if name in newv47 and int(ws.get('samples',0))<48:q-=.045
    if name in newv48 and int(ws.get('samples',0))<60:q-=.050
    if name in newv49 and int(ws.get('samples',0))<72:q-=.055
    if wn<18:q-=.022
    if int(l20.get('loss_streak',0))>=3:q-=.045
    if wn>=18 and float(w20.get('raw_win_rate',.5))<.44:q-=.040
    if wn>=18 and float(w20.get('ewma',.5))<.43:q-=.035
    return _clamp(q,.34,.705)

def _meta_consensus(board,preds,live,wf,seq=None):
    prof=_profile_for(board);c=[];seq=seq or [];rnd=_js_randomness_score(seq) if seq else .5
    for n,p in preds.items():
        if p.get('prediction') not in ('TÀI','XỈU'):continue
        q=_combined_quality(board,n,live,wf)
        if n=='ANTI_RAW' and live.get(n,{}).get('short',{}).get('total',0)<14:continue
        if q<.485 and wf.get(n,{}).get('short',{}).get('total',0)>=18:continue
        c.append({'name':n,'prediction':p['prediction'],'quality':q,'edge':q-.5,'local_confidence':p.get('local_confidence',52)})
    c.sort(key=lambda x:x['quality'],reverse=True)
    families={
      'markov':{'MARKOV_TRANSITION','MARKOV_ORDER2','HIGH_ORDER_MARKOV','DECAYED_TRANSITION','FLIP_STATE_MARKOV','RUN_LENGTH_MARKOV','CONTEXT_ENTROPY','WILSON_CONTEXT','DIRICHLET_VOM','CTW_APPROX','HIERARCHICAL_BAYES'},
      'motif':{'SUFFIX_CONTEXT','MOTIF_WEIGHTED','PERIODIC_MATCH','ANALOG_KNN','KNN_RECENCY','MOTIF_SURVIVAL'},
      'regime':{'REGIME_ADAPTIVE','REGIME_SWITCH','CHANGEPOINT_ADAPTIVE','ENTROPY_GATE','MULTI_WINDOW','DUAL_HORIZON','BIAS_MOMENTUM','BIAS_MEAN_REVERSION','SEQUENTIAL_CHANGE','REGIME_POSTERIOR','TRANSITION_DRIFT'},
      'run':{'RUN_HAZARD','RUN_BREAK','RUN_FOLLOW','RUN_SURVIVAL','JS_BREAK_CALIBRATOR','RUN_MATRIX','BAYES_RUN_MIXTURE','RUN_CONTEXT_JOINT'},
      'adaptive':{'JS_TREND_BLEND','JS_ULTRA_STACK','MULTISCALE_TRANSITION','CROSS_HORIZON_BAYES','HORIZON_CONSENSUS','LAG_ENSEMBLE','MULTIRESOLUTION_EDGE','SPECTRAL_LAG','ROBUST_STACK'},
      'longmem':{'VOM_CONTEXT_6','LONG_MEMORY_BAYES','RUN_PROFILE_LONG'},
      'reference':{'REFERENCE_PATTERN_PRIOR'},
      'other':{'FOLLOW_LAST','REVERSE_LAST','ALTERNATING_PATTERN','ANTI_RAW','FUSION_CORE'}
    }
    def fam(name):
        for k,v in families.items():
            if name in v:return k
        return 'other'
    target=max(1,int(prof.get('top_k',3)))
    if rnd>=.74:target=min(6,target+1)
    top=[];used=set()
    # First pass: one expert per family gives real diversity.
    for x in c:
        f=fam(x['name'])
        if f in used:continue
        if rnd>=.76 and f in ('reference','motif') and x['quality']<.535:continue
        top.append(x);used.add(f)
        if len(top)>=target:break
    # Second pass: fill only with genuinely strong extra experts.
    if len(top)<target:
        for x in c:
            if x in top:continue
            if x['quality']<.505 and len(top)>=2:continue
            top.append(x)
            if len(top)>=target:break
    vt=vx=0.0
    for x in top:
        n=x['name'];lc=_clamp((float(x.get('local_confidence',52))-50)/22,0,1)
        ws=wf.get(n,{});w20=ws.get('short',{});rs=ws.get('regime',{})
        lower=max(.40,float(w20.get('lower',.0)));ew=float(w20.get('ewma',.5))
        reliability=_clamp(.72+max(0,lower-.45)*1.4+max(0,ew-.5)*.7,.68,1.15)
        if int(rs.get('total',0))>=8:reliability*=_clamp(.90+(float(rs.get('win_rate',.5))-.5)*.8,.80,1.10)
        w=max(.012,x['edge']+.018)*(.88+.22*lc)*reliability
        if rnd>=.78 and fam(n) in ('reference','motif'):w*=.72
        if x['prediction']=='TÀI':vt+=w
        else:vx+=w
    if abs(vt-vx)<.012:final=top[0]['prediction'] if top else 'TÀI'
    else:final='TÀI' if vt>vx else 'XỈU'
    total=max(.001,vt+vx);agree=max(vt,vx)/total
    return final,top,agree

def _strategy_predictors(board,rows,fusion):
    seq=_seq(rows)
    if not seq: seq=['TÀI']
    last=seq[-1]; run=_run_len(seq)
    q6=seq[-6:]
    flips=sum(1 for i in range(1,len(q6)) if q6[i]!=q6[i-1])
    alt_rate=flips/max(1,len(q6)-1)
    p20=seq[-20:].count('TÀI')/max(1,len(seq[-20:]))
    p12=seq[-12:].count('TÀI')/max(1,len(seq[-12:]))
    markov=_markov_prediction(seq,1)
    high=_markov_prediction(seq,3)
    final_hist=_recent_final_stats(board,20)
    raw_bad=(sum(1 for h in final_hist if not h['ok'])/max(1,len(final_hist))) if final_hist else 0.0
    fusion_pred=fusion.get('prediction') if fusion.get('prediction') in ('TÀI','XỈU') else markov
    preds={}
    def put(name,pred,conf,reason):
        preds[name]={'name':name,'prediction':pred,'local_confidence':int(_clamp(conf,45,72)),'reason':reason}
    put('FOLLOW_LAST',last,51,'Theo kết quả gần nhất')
    put('REVERSE_LAST',_opp(last),51,'Đảo kết quả gần nhất')
    put('ALTERNATING_PATTERN',_opp(last) if alt_rate>=.60 else markov,50+abs(alt_rate-.5)*20,f'Alt rate {alt_rate:.2f}')
    put('RUN_BREAK',_opp(last) if run>=3 else markov,50+min(10,run*1.5),f'Run {run}')
    put('RUN_FOLLOW',last if 2<=run<=3 else (_opp(last) if run>=5 else markov),50+min(9,run*1.3),f'Run {run}')
    put('BIAS_MEAN_REVERSION','XỈU' if p20>=.60 else 'TÀI' if p20<=.40 else _opp(last),50+abs(p20-.5)*25,f'pT20 {p20:.2f}')
    put('BIAS_MOMENTUM','TÀI' if p12>=.58 else 'XỈU' if p12<=.42 else last,50+abs(p12-.5)*28,f'pT12 {p12:.2f}')
    put('MARKOV_TRANSITION',markov,53,'Markov chuyển trạng thái bậc 1')
    put('ANTI_RAW',_opp(fusion_pred) if raw_bad>=.55 else _opp(last),50+min(10,raw_bad*12),f'Wrong rate {raw_bad:.2f}')
    put('HIGH_ORDER_MARKOV',high,53,'Markov ngữ cảnh bậc 3')
    put('MARKOV_ORDER2',_markov_prediction(seq,2),53,'Markov ngữ cảnh bậc 2')
    put('RUN_HAZARD',_run_hazard_prediction(seq),52,'Xác suất tiếp/bẻ theo độ dài bệt')
    put('MULTI_WINDOW',_multi_window_prediction(seq),52,'Bỏ phiếu W8/W16/W32/W64')
    put('DECAYED_TRANSITION',_decayed_transition_prediction(seq,2),54,'Transition có trọng số recency')
    put('REGIME_ADAPTIVE',_regime_adaptive_prediction(seq),54,'Tự đổi logic theo alternating/run/bias regime')
    put('MOTIF_WEIGHTED',_motif_weighted_prediction(seq),53,'Motif 2–6 có trọng số độ dài + độ mới')
    put('FLIP_STATE_MARKOV',_flip_state_markov_prediction(seq),53,'Markov theo trạng thái flip/repeat')
    put('RUN_LENGTH_MARKOV',_run_length_markov_prediction(seq),54,'Markov theo side + độ dài bệt')
    put('PERIODIC_MATCH',_periodic_match_prediction(seq),52,'Chu kỳ 2–12 kiểm định trên lịch sử')
    put('DUAL_HORIZON',_dual_horizon_prediction(seq),53,'Nhịp W8 kết hợp xu hướng W28')
    put('ANALOG_KNN',_analog_knn_prediction(seq),54,'So khớp ngữ cảnh lịch sử gần giống')
    put('RUN_SURVIVAL',_run_survival_prediction(seq),53,'Tỷ lệ bệt cùng side sống tiếp/bẻ')
    put('CONTEXT_ENTROPY',_context_entropy_prediction(seq),54,'Context entropy thấp + đủ mẫu')
    put('BAYES_CONTEXT',_bayes_context_prediction(seq),55,'Bayes context 1–5 có smoothing + recency')
    put('HORIZON_CONSENSUS',_horizon_consensus_prediction(seq),54,'Đồng thuận đa cửa sổ W6/W10/W20/W40/W80')
    put('REGIME_SWITCH',_regime_switch_prediction(seq),55,'Tự chuyển logic theo bệt/đảo/bias regime')
    put('LAG_ENSEMBLE',_lag_ensemble_prediction(seq),54,'Ensemble chu kỳ lag 2–15 có kiểm định')
    ref=_reference_pattern_signal(seq) if _reference_allowed(board) else {'ready':False,'prediction':_bayes_context_prediction(seq),'score':0,'support':0,'length':0}
    ref_conf=50+min(14,abs(float(ref.get('score',0)))*20)+min(4,float(ref.get('support',0))/20)
    put('REFERENCE_PATTERN_PRIOR',ref.get('prediction'),ref_conf,f"Reference prior L{ref.get('length',0)} n={ref.get('support',0)} score={ref.get('score',0)}")
    put('JS_TREND_BLEND',_js_trend_blend_prediction(seq),54,'JS blend: trend ngắn/dài + mean-reversion + momentum')
    br=_js_break_signal(seq)
    put('JS_BREAK_CALIBRATOR',br.get('prediction'),52+abs(float(br.get('p_break',.5))-.5)*26,f"Break p={br.get('p_break',.5)} · run={br.get('run',0)} · n={br.get('support',0)}")
    rnd=_js_randomness_score(seq)
    put('JS_ULTRA_STACK',_js_ultra_stack_prediction(seq,_reference_allowed(board)),55-min(5,max(0,rnd-.65)*20),f"Adaptive stack · randomness {rnd:.2f}")
    put('VOM_CONTEXT_6',_vom_context6_prediction(seq),55,'Variable-order context 2–8 · long memory')
    put('LONG_MEMORY_BAYES',_long_memory_bayes_prediction(seq),55,'Bayes context học tối đa 5.000 phiên')
    put('RUN_PROFILE_LONG',_run_profile_long_prediction(seq),54,'Run profile dài · tiếp/bẻ theo lịch sử lớn')
    put('MULTISCALE_TRANSITION',_multiscale_transition_prediction(seq),55,'Transition đa khung W32→W10000')
    put('CHANGEPOINT_ADAPTIVE',_changepoint_adaptive_prediction(seq),55,'Phát hiện đổi regime rồi ưu tiên lịch sử gần')
    put('WILSON_CONTEXT',_wilson_context_prediction(seq),55,'Context 2–9 có Wilson lower-bound chống mẫu ảo')
    put('KNN_RECENCY',_knn_recency_prediction(seq),54,'KNN pattern 5–12 + similarity + recency')
    put('RUN_MATRIX',_run_matrix_prediction(seq),54,'Ma trận side × độ dài bệt với long-memory')
    put('ENTROPY_GATE',_entropy_gate_prediction(seq),55,'Entropy gate chọn bệt/đảo/bias/change-point')
    put('CROSS_HORIZON_BAYES',_cross_horizon_bayes_prediction(seq),56,'Bayes đa horizon W24→W3000')
    put('DIRICHLET_VOM',_dirichlet_vom_prediction(seq),56,'Dirichlet VOM bậc 1–10 + recency + evidence shrink')
    put('SEQUENTIAL_CHANGE',_sequential_change_prediction(seq),55,'Sequential drift filter tự rút ngắn memory khi đổi regime')
    put('MOTIF_SURVIVAL',_motif_survival_prediction(seq),55,'Motif 3–12 + Beta smoothing + survival/recency')
    put('REGIME_POSTERIOR',_regime_posterior_prediction(seq),56,'Posterior mixture bệt/đảo/bias/mixed')
    put('MULTIRESOLUTION_EDGE',_multiresolution_edge_prediction(seq),55,'Edge đa độ phân giải W8→W1024 có shrinkage')
    put('BAYES_RUN_MIXTURE',_bayes_run_mixture_prediction(seq),56,'Bayes run continuation/break + context mixture')
    put('CTW_APPROX',_ctw_approx_prediction(seq),57,'Context Tree Weighting gần đúng · order 1–12 · recency')
    put('HIERARCHICAL_BAYES',_hierarchical_bayes_prediction(seq),57,'Bayes phân cấp · context dài chỉ được tin khi đủ evidence')
    put('TRANSITION_DRIFT',_transition_drift_prediction(seq),56,'Transition short/long + drift detector')
    put('RUN_CONTEXT_JOINT',_run_context_joint_prediction(seq),56,'Joint state side × run × flip context')
    put('SPECTRAL_LAG',_spectral_lag_prediction(seq),56,'Lag 2–40 · shrinkage · kiểm tra chu kỳ')
    put('ROBUST_STACK',_robust_stack_prediction(seq),58,'Stack đa family · chống một họ model áp đảo')
    put('SUFFIX_CONTEXT',_suffix_prediction(seq),52,'Suffix/motif context 2–6')
    put('FUSION_CORE',fusion_pred,int(fusion.get('confidence',50)),'V31 fusion core độc lập')
    return preds

def _strategy_rows(board):
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute(
            '''SELECT session,strategy,prediction,actual,ok,settled_at
               FROM strategy_logs WHERE board=? AND actual IS NOT NULL AND ok IS NOT NULL
               ORDER BY settled_at DESC''',(board,)
        ).fetchall()
    by={}
    for session,name,pred,actual,ok,settled in rows:
        by.setdefault(name,[]).append({'session':session,'prediction':pred,'actual':actual,'ok':bool(ok),'settled_at':settled})
    return by

def _stats_for(rows,window):
    q=rows[:window]; n=len(q); wins=sum(1 for r in q if r['ok'])
    streak=0
    for r in q:
        if r['ok']: break
        streak+=1
    return {'total':n,'win':wins,'loss':n-wins,'win_rate':wins/n if n else .5,'loss_streak':streak}

def get_strategy_stats_map(board):
    by=_strategy_rows(board); out={}
    for name in STRATEGY_NAMES:
        rows=by.get(name,[])
        s20=_stats_for(rows,20); s50=_stats_for(rows,50); s100=_stats_for(rows,100)
        score=.50*s20['win_rate']+.35*s50['win_rate']+.15*s100['win_rate']
        if s20['total']<10: score-=.05
        if s50['total']<25: score-=.05
        if s20['loss_streak']>=3: score-=.07
        if s20['total']>=10 and s20['win_rate']<.45: score-=.10
        if s50['total']>=20 and s50['win_rate']<.48: score-=.05
        if s20['total']>=10 and s20['win_rate']>=.55: score+=.05
        if s50['total']>=20 and s50['win_rate']>=.53: score+=.05
        valid=((s20['total']>=10 or s50['total']>=25) and score>=.50)
        out[name]={'short':s20,'mid':s50,'long':s100,'performance_score':round(score,4),'valid':valid}
    return out

def _champion_locked(board,candidate,stats):
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute('SELECT champion FROM champion_state WHERE board=?',(board,)).fetchone()
    old=r[0] if r else None
    if old and old in stats and candidate in stats:
        os=stats[old]; ns=stats[candidate]; o20=os['short']
        keep=(o20['loss_streak']<3 and (o20['win_rate']>=.48 or o20['total']<10))
        if keep and ns['performance_score'] < os['performance_score']+.08:
            candidate=old
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            '''INSERT INTO champion_state(board,champion,updated_at) VALUES(?,?,?)
               ON CONFLICT(board) DO UPDATE SET champion=excluded.champion,updated_at=excluded.updated_at''',
            (board,candidate,time.time())
        ); db.commit()
    return candidate

def select_champion(board,preds):
    stats=get_strategy_stats_map(board)
    valid=[n for n in STRATEGY_NAMES if n in preds and stats.get(n,{}).get('valid')]
    candidate=max(valid,key=lambda n:stats[n]['performance_score']) if valid else ('MARKOV_TRANSITION' if 'MARKOV_TRANSITION' in preds else 'REVERSE_LAST')
    candidate=_champion_locked(board,candidate,stats)
    if candidate not in preds: candidate='MARKOV_TRANSITION' if 'MARKOV_TRANSITION' in preds else next(iter(preds))
    return candidate,stats

def _final_performance(board):
    h=_recent_final_stats(board,50); q20=h[:20]; q50=h[:50]
    wr20=sum(1 for x in q20 if x['ok'])/len(q20) if q20 else .5
    wr50=sum(1 for x in q50 if x['ok'])/len(q50) if q50 else .5
    streak=0
    for x in h:
        if x['ok']: break
        streak+=1
    reverse=(sum(1 for x in q20 if not x['ok'])/len(q20)) if q20 else .5
    return {'n20':len(q20),'n50':len(q50),'wr20':wr20,'wr50':wr50,'loss_streak':streak,
            'normal_win_rate':wr20,'reverse_win_rate':reverse}

def model_snapshot(rows, game=None, board=None):
    fusion=fusion_model_snapshot(rows,game,board)
    if not board:return fusion
    seq=_seq(rows)
    if len(seq)<2:
        fusion['engine']='BOARD-META 55 + ELITE ADAPTIVE V49';return fusion
    preds=_strategy_predictors(board,rows,fusion)
    live=get_strategy_stats_map(board);wf=walk_forward_strategy_stats(board,rows);prof=_profile_for(board)
    champion,_=select_champion(board,preds);recent=_final_performance(board)
    if prof.get('mode')=='champion':
        raw=preds[champion]['prediction'];decision=champion;decision_mode='CHAMPION'
        top=[{'name':champion,'prediction':raw,'quality':_combined_quality(board,champion,live,wf)}];agree=1.0
    else:
        raw,top,agree=_meta_consensus(board,preds,live,wf,seq);decision='META['+', '.join(x['name'] for x in top[:3])+']';decision_mode='BOARD_META'

    sicbo_hash=None;sicbo_dice=None
    if board=='sunwin:sicbo':
        sicbo_hash=sicbo_hash_signal(rows)
        sicbo_dice=sicbo_dice_side(rows)
        if sicbo_hash.get('usable'):
            hpred=sicbo_hash.get('prediction');hq=float(sicbo_hash.get('quality',.5))
            top.append({'name':'SICBO_HASH_CAL','prediction':hpred,'quality':hq})
            if hpred==raw:
                agree=_clamp(agree+min(.07,max(0,hq-.5)*.8),.5,.95)
            elif agree<.585 and hq>=.545:
                raw=hpred;decision='SICBO_HASH_TIEBREAK';decision_mode='SICBO_META';agree=max(.56,hq)
            else:
                agree=max(.50,agree-.025)
        if sicbo_dice.get('ready'):
            dpred=sicbo_dice.get('prediction');dq=float(sicbo_dice.get('quality',.5))
            top.append({'name':'SICBO_DICE_META','prediction':dpred,'quality':dq})
            if dpred==raw:
                agree=_clamp(agree+min(.05,max(0,dq-.5)*.7),.5,.95)
            elif agree<.555 and dq>=.535:
                raw=dpred;decision='SICBO_DICE_TIEBREAK';decision_mode='SICBO_META';agree=max(.54,dq)

    rmin=int(prof.get('reverse_min',34));gap=float(prof.get('reverse_gap',.20))
    reverse_mode=(recent['n20']>=rmin and recent['normal_win_rate']<.43 and
                  recent['reverse_win_rate']-recent['normal_win_rate']>=gap)
    recovery=((recent['n50']>=40 and recent['wr50']<.44) or
              (recent['n20']>=20 and recent['wr20']<.38) or recent['loss_streak']>=5)
    final=_opp(raw) if reverse_mode else raw
    qvals=[float(x.get('quality',.5)) for x in top[:4]] or [.5];q=sum(qvals)/len(qvals)
    conf=50+max(0,q-.5)*88+max(0,agree-.5)*15
    if recent['n20']>=12:conf+=(recent['wr20']-.5)*18
    if recovery:conf-=7
    if reverse_mode:conf-=3
    randomness=_js_randomness_score(seq)
    randomness_penalty=max(0.0,(randomness-.66)*15.0)
    conf-=randomness_penalty
    structure=_structure_score(seq)
    # Multiple-expert safeguard: on data that looks statistically close to IID,
    # never turn a lucky recent walk-forward streak into a very strong display.
    if len(seq)>=120:
        if structure<.16:conf=min(conf,54)
        elif structure<.24:conf=min(conf,58)
        elif structure<.32:conf=min(conf,63)
    top_quality=max((float(x.get('quality',.5)) for x in top),default=.5)
    # V48 calibration: a hot strategy cannot display a strong signal unless its
    # causal walk-forward lower bound and current-regime sample also support it.
    wf_lowers=[];reg_rates=[];reg_ns=[]
    for x in top[:4]:
        ws=wf.get(x.get('name'),{});w20=ws.get('short',{});rs=ws.get('regime',{})
        if int(w20.get('total',0))>=12:wf_lowers.append(float(w20.get('lower',0)))
        if int(rs.get('total',0))>=8:
            reg_rates.append(float(rs.get('win_rate',.5)));reg_ns.append(int(rs.get('total',0)))
    wf_floor=(sum(wf_lowers)/len(wf_lowers)) if wf_lowers else .44
    reg_q=(sum(reg_rates)/len(reg_rates)) if reg_rates else .5
    if wf_lowers and wf_floor<.43:conf=min(conf,55)
    elif wf_lowers and wf_floor<.47:conf=min(conf,60)
    if reg_rates and reg_q<.47:conf-=3
    elif reg_rates and reg_q>.54 and agree>=.61:conf+=1.5
    if agree<.56:conf=min(conf,54)
    if randomness>=.76 and agree<.64:conf=min(conf,55)
    if top_quality<.525:conf=min(conf,55)
    elif top_quality<.545:conf=min(conf,59)
    calibration=_confidence_bucket_calibration(board,conf)
    conf=min(conf,float(calibration.get('cap',72)))+float(calibration.get('bonus',0))
    conf=_clamp(conf,45,72);display=int(round(_clamp(conf+3,48,74)))
    anti=_anti_phase(board)
    mode='RECOVERY + REVERSE' if recovery and reverse_mode else 'RECOVERY' if recovery else 'REVERSE' if reverse_mode else decision_mode
    rank=[]
    for n in STRATEGY_NAMES:
        if n not in preds:continue
        rank.append({'name':n,'quality':round(_combined_quality(board,n,live,wf),4),
                     'wf20':round(float(wf.get(n,{}).get('short',{}).get('raw_win_rate',.5)),3),
                     'wfN':int(wf.get(n,{}).get('short',{}).get('total',0)),
                     'live20':round(float(live.get(n,{}).get('short',{}).get('win_rate',.5)),3),
                     'liveN':int(live.get(n,{}).get('short',{}).get('total',0)),
                     'prediction':preds[n]['prediction']})
    rank.sort(key=lambda x:x['quality'],reverse=True)
    if conf>=63 and agree>=.62:status='MẠNH'
    elif conf>=56:status='TRUNG BÌNH'
    elif conf>=49:status='YẾU'
    else:status='NGUY HIỂM'
    if max((x.get('wfN',0) for x in rank),default=0)<18 and status in ('MẠNH','TRUNG BÌNH'):status='YẾU'
    fusion.update({'prediction':final,'raw_prediction':raw,'confidence':display,'percent':display,
      'model_confidence':round(conf,2),'strategy_champion':decision,'champion_raw':champion,
      'strategy_predictions':{k:v['prediction'] for k,v in preds.items()},
      'strategy_reasons':{k:v['reason'] for k,v in preds.items()},'strategy_rankings':rank,
      'meta_top':top[:4],'meta_agreement':round(agree,4),'decision_mode':decision_mode,
      'board_profile':prof.get('mode','consensus'),'recovery_mode':bool(recovery),'reverse_mode':bool(reverse_mode),'mode':mode,
      'anti_tai':anti['anti_tai'],'anti_xiu':anti['anti_xiu'],'normal_win_rate':round(recent['normal_win_rate'],4),
      'reverse_win_rate':round(recent['reverse_win_rate'],4),'final_loss_streak':recent['loss_streak'],'status':status,
      'sicbo_hash':sicbo_hash if board=='sunwin:sicbo' else None,
      'sicbo_dice_meta':sicbo_dice if board=='sunwin:sicbo' else None,
      'randomness_score':round(randomness,4),'randomness_penalty':round(randomness_penalty,3),
      'structure_score':round(structure,4),'regime_label':_regime_label(seq),
      'wf_floor':round(wf_floor,4),'regime_quality':round(reg_q,4),
      'signal_calibration':calibration,
      'reference_pattern':_reference_pattern_signal(seq) if _reference_allowed(board) else None,
      'engine':'BOARD-META 67 + HASH-36 TURBO ENSEMBLE V56','totalStrategies':len(STRATEGY_NAMES),'updated_at':time.time()})
    return fusion

def log_strategy_predictions(board,session,model):
    preds=(model or {}).get('strategy_predictions') or {}
    if not preds: return
    now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        for name,pred in preds.items():
            if name not in STRATEGY_NAMES or pred not in ('TÀI','XỈU'): continue
            db.execute(
                '''INSERT INTO strategy_logs(board,session,strategy,prediction,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(board,session,strategy) DO UPDATE SET prediction=excluded.prediction''',
                (board,str(session),name,pred,now)
            )
        db.commit()

def settle_strategy_predictions(board,session,actual):
    if actual not in ('TÀI','XỈU'): return
    now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute('SELECT strategy,prediction FROM strategy_logs WHERE board=? AND session=?',(board,str(session))).fetchall()
        for name,pred in rows:
            db.execute(
                '''UPDATE strategy_logs SET actual=?,ok=?,settled_at=?
                   WHERE board=? AND session=? AND strategy=?''',
                (actual,1 if pred==actual else 0,now,board,str(session),name)
            )
        db.commit()

async def store_rows(board, rows):
    if not rows: return
    async with _db_lock:
        with sqlite3.connect(DB_PATH) as db:
            now=time.time()
            for r in rows:
                d=(r.get('dice') or [])+[None,None,None]
                db.execute('''INSERT INTO rounds(board,session,result,d1,d2,d3,total,md5,seen_at,meta_json)
                              VALUES(?,?,?,?,?,?,?,?,?,?)
                              ON CONFLICT(board,session) DO UPDATE SET
                              result=excluded.result,d1=COALESCE(excluded.d1,rounds.d1),
                              d2=COALESCE(excluded.d2,rounds.d2),d3=COALESCE(excluded.d3,rounds.d3),
                              total=COALESCE(excluded.total,rounds.total),md5=COALESCE(excluded.md5,rounds.md5),
                              meta_json=COALESCE(excluded.meta_json,rounds.meta_json),seen_at=excluded.seen_at''',
                           (board,str(r['id']),r['result'],d[0],d[1],d[2],r.get('sum'),r.get('md5'),now,
                            json.dumps(r.get('meta'),ensure_ascii=False) if r.get('meta') else None))
            # bound rows per board
            db.execute('''DELETE FROM rounds WHERE board=? AND rowid NOT IN
                          (SELECT rowid FROM rounds WHERE board=? ORDER BY seen_at DESC LIMIT ?)''',(board,board,MAX_HISTORY))
            db.commit()

def load_rows(board, limit=500):
    with sqlite3.connect(DB_PATH) as db:
        rows=[]
        for s,r,d1,d2,d3,total,md5,seen,mj in db.execute('SELECT session,result,d1,d2,d3,total,md5,seen_at,meta_json FROM rounds WHERE board=?',(board,)):
            try: meta=json.loads(mj) if mj else {}
            except: meta={}
            rid=canonical_session(s,s)
            rows.append({'id':rid,'result':r,'dice':[x for x in (d1,d2,d3) if x is not None],
                         'sum':total,'md5':md5,'seen_at':seen,'meta':meta})
        return _stable_rows(rows)[-limit:]

def get_prediction_history(board, limit=20):
    with sqlite3.connect(DB_PATH) as db:
        cur=db.execute('''SELECT p.session,p.prediction,p.confidence,p.score,p.created_at,p.actual,p.ok,p.settled_at,p.model_json,
                                 r.d1,r.d2,r.d3,r.total,r.md5
                          FROM shared_predictions p
                          LEFT JOIN rounds r ON r.board=p.board AND r.session=p.session
                          WHERE p.board=? ORDER BY p.created_at DESC LIMIT ?''',(board,limit))
        out=[]
        for session,pred,conf,score,created,actual,ok,settled,mj,d1,d2,d3,total,md5 in cur.fetchall():
            try: model=json.loads(mj) if mj else {}
            except: model={}
            dice=[x for x in (d1,d2,d3) if x is not None]
            out.append({'session':session,'prediction':pred,'confidence':conf,'score':score,'created_at':created,
                        'actual':actual,'ok':None if ok is None else bool(ok),'settled_at':settled,'model':model,
                        'dice':dice,'sum':total,'md5':md5})
        return out

def get_shared_prediction(board):
    hist=get_prediction_history(board,5)
    for x in hist:
        if x['actual'] is None: return x
    return hist[0] if hist else None

def _settle_predictions(board, rows):
    actual={str(r['id']):r['result'] for r in rows if r.get('result') in ('TÀI','XỈU')}
    if not actual: return []
    settled=[]
    with sqlite3.connect(DB_PATH) as db:
        pend=db.execute('SELECT session,prediction FROM shared_predictions WHERE board=? AND actual IS NULL',(board,)).fetchall()
        now=time.time()
        for session,pred in pend:
            if str(session) not in actual: continue
            act=actual[str(session)]
            ok=1 if pred==act else 0
            db.execute('UPDATE shared_predictions SET actual=?,ok=?,settled_at=? WHERE board=? AND session=?',
                       (act,ok,now,board,str(session)))
            settled.append({'session':str(session),'prediction':pred,'actual':act,'ok':bool(ok)})
        db.commit()
    for item in settled:
        settle_strategy_predictions(board,item['session'],item['actual'])
    return settled

def _current_anchor(current_rows):
    nums=[_session_num(r.get('id')) for r in (current_rows or [])
          if r.get('result') in ('TÀI','XỈU') and _session_num(r.get('id')) is not None]
    return str(max(nums)) if nums else None

def _drop_stale_pending(board,target_session):
    # V33: keep unresolved predictions. History APIs can lag behind current APIs;
    # deleting them caused SUNWIN history to vanish instead of settling later.
    return

def _create_shared_prediction(board, rows, current_session=None):
    if not rows:return None,False
    latest=str(current_session) if current_session is not None else None
    session=str(_session_num(latest)+1) if latest is not None and _session_num(latest) is not None else _next_session(rows)
    if not session:return None,False
    if latest is None:latest=str(int(session)-1)
    _drop_stale_pending(board,session)
    with sqlite3.connect(DB_PATH) as db:
        old=db.execute('SELECT prediction,confidence,score,model_json,created_at,actual,ok,settled_at FROM shared_predictions WHERE board=? AND session=?',(board,session)).fetchone()
    if old:
        try:mj=json.loads(old[3]) if old[3] else {}
        except:mj={}
        if mj:_state_model_cache[board]=mj
        return {'session':session,'prediction':old[0],'confidence':old[1],'score':old[2],'model':mj,'created_at':old[4],'actual':old[5],'ok':None if old[6] is None else bool(old[6]),'settled_at':old[7]},False
    game=board.split(':',1)[0];model=model_snapshot(rows,game,board)
    if board=='sunwin:sicbo':model['dice_forecast']=dice_position_forecast(rows)
    if board=='lc79:xocdia' and model.get('prediction'):model['xocdia_forecast']=xocdia_detail_forecast(rows,model['prediction'])
    if not model.get('prediction'):return None,False
    _state_model_cache[board]=model
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT INTO board_cursor(board,last_completed_session,updated_at) VALUES(?,?,?) ON CONFLICT(board) DO UPDATE SET last_completed_session=excluded.last_completed_session,updated_at=excluded.updated_at",(board,latest,time.time()))
        now=time.time();db.execute("INSERT OR IGNORE INTO shared_predictions(board,session,prediction,confidence,score,model_json,created_at) VALUES(?,?,?,?,?,?,?)",(board,session,model['prediction'],model['confidence'],model['score'],json.dumps(model,ensure_ascii=False),now));db.commit()
    log_strategy_predictions(board,session,model)
    return {'session':session,'prediction':model['prediction'],'confidence':model['confidence'],'score':model['score'],'model':model,'created_at':now,'actual':None,'ok':None,'settled_at':None},True

async def set_state(board, ok, error=None):
    model=_state_model_cache.get(board)
    if model is None:
        rows=load_rows(board,500)
        model=model_snapshot(rows,board.split(':',1)[0],board) if rows else {'engine':'BOARD-META 67 + HASH-36 TURBO ENSEMBLE V56'}
        _state_model_cache[board]=model
    async with _db_lock:
        with sqlite3.connect(DB_PATH) as db:
            db.execute("INSERT INTO board_state(board,updated_at,source_ok,last_error,model_json) VALUES(?,?,?,?,?) ON CONFLICT(board) DO UPDATE SET updated_at=excluded.updated_at,source_ok=excluded.source_ok,last_error=excluded.last_error,model_json=excluded.model_json",(board,time.time(),1 if ok else 0,error,json.dumps(model,ensure_ascii=False)));db.commit()

def effective_cfg(board, cfg):
    out=dict(cfg)
    try:
        with sqlite3.connect(DB_PATH) as db:
            r=db.execute('SELECT current_url,history_url FROM api_overrides WHERE board=?',(board,)).fetchone()
        if r:
            if r[0]: out['current']=r[0]
            if r[1]: out['history']=r[1]
    except Exception:
        pass
    return out

def set_api_override(board,current_url=None,history_url=None):
    if board not in BOARDS: return False
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''INSERT INTO api_overrides(board,current_url,history_url,updated_at) VALUES(?,?,?,?)
                      ON CONFLICT(board) DO UPDATE SET current_url=excluded.current_url,
                      history_url=excluded.history_url,updated_at=excluded.updated_at''',
                   (board,current_url or None,history_url or None,time.time()))
        db.commit()
    return True

async def fetch_first(client, urls):
    last=None
    for url in [u for u in urls if u]:
        try:
            return await fetch_json(client,url),url
        except Exception as e:
            last=e
    if last: raise last
    raise RuntimeError('không có URL API')

async def fetch_json(client,url):
    r=await client.get(url,headers={'Accept':'application/json','Cache-Control':'no-cache'},timeout=2.0)
    r.raise_for_status(); return r.json()

def board_label(board):
    labels={
      'sunwin:hu':'SUNWIN HŨ','sunwin:sicbo':'SUNWIN SICBO',
      'lc79:hu':'LC79 HŨ','lc79:md5':'LC79 MD5','lc79:xocdia':'LC79 XÓC ĐĨA',
      'betvip:hu':'BETVIP HŨ','betvip:md5':'BETVIP MD5',
      'gb68:hu':'68GB HŨ','gb68:md5':'68GB MD5',
      'b52:hu':'B52 HŨ','b52:md5':'B52 MD5',
      'max789:hu':'MAX789 HŨ','max789:md5':'MAX789 MD5',
      'son789:hu':'SON789 HŨ','son789:md5':'SON789 MD5',
      'hitclub:hu':'HITCLUB HŨ','hitclub:md5':'HITCLUB MD5'
    }
    if board.startswith('baccarat:') and board!='baccarat:main': return 'BACCARAT · '+board.split(':',1)[1]
    return labels.get(board,board.upper())

def display_pred(board,p):
    if not p: return '---'
    if board.startswith('baccarat:'):
        return 'PLAYER' if p=='TÀI' else 'BANKER' if p=='XỈU' else p
    if board=='lc79:xocdia':
        return 'CHẴN' if p=='TÀI' else 'LẺ' if p=='XỈU' else p
    return p

def available_bot_boards():
    return list(BOARDS.keys())

def is_group_chat_id(chat_id):
    try:return int(chat_id)<0
    except:return False

def get_group_settings(chat_id):
    defaults={'enabled':False,'auto_delete':True,'delete_after':5.0,'anti_spam':True,
              'spam_limit':5,'spam_window':6.0,'mute_seconds':60,'locked':False,
              'warn_limit':3,'title':None,'enabled_by':None,'updated_at':None}
    if not is_group_chat_id(chat_id):
        return {**defaults,'auto_delete':False,'anti_spam':False}
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute(
            '''SELECT title,enabled,auto_delete,delete_after,anti_spam,spam_limit,spam_window,
                      mute_seconds,locked,warn_limit,enabled_by,updated_at
               FROM bot_group_settings WHERE chat_id=?''',(int(chat_id),)
        ).fetchone()
    if not r:return defaults
    return {'title':r[0],'enabled':bool(r[1]),'auto_delete':bool(r[2]),'delete_after':float(r[3] or 5),
            'anti_spam':bool(r[4]),'spam_limit':int(r[5] or 5),'spam_window':float(r[6] or 6),
            'mute_seconds':int(r[7] or 60),'locked':bool(r[8]),'warn_limit':int(r[9] or 3),
            'enabled_by':r[10],'updated_at':r[11]}

def group_enabled(chat_id):
    return bool(get_group_settings(chat_id).get('enabled'))

def _ensure_group_row(chat_id,admin_id=None,title=None):
    now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            '''INSERT INTO bot_group_settings(chat_id,title,enabled,enabled_by,updated_at)
               VALUES(?,?,0,?,?) ON CONFLICT(chat_id) DO UPDATE SET
               title=COALESCE(excluded.title,bot_group_settings.title),
               enabled_by=COALESCE(excluded.enabled_by,bot_group_settings.enabled_by),
               updated_at=excluded.updated_at''',
            (int(chat_id),title,int(admin_id) if admin_id is not None else None,now))
        db.commit()

def set_group_enabled(chat_id,enabled,admin_id=None,title=None):
    if not is_group_chat_id(chat_id):raise ValueError('group only')
    _ensure_group_row(chat_id,admin_id,title);now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        db.execute('UPDATE bot_group_settings SET enabled=?,enabled_by=COALESCE(?,enabled_by),updated_at=? WHERE chat_id=?',
                   (1 if enabled else 0,int(admin_id) if admin_id is not None else None,now,int(chat_id)))
        if not enabled:db.execute('UPDATE bot_subscriptions SET enabled=0 WHERE chat_id=?',(int(chat_id),))
        db.commit()

def set_selected_board(chat_id,board):
    with sqlite3.connect(DB_PATH) as db:
        db.execute('INSERT INTO bot_chat_state(chat_id,selected_board) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET selected_board=excluded.selected_board',(chat_id,board));db.commit()

def get_selected_board(chat_id):
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute('SELECT selected_board FROM bot_chat_state WHERE chat_id=?',(chat_id,)).fetchone()
    return r[0] if r else None

def set_sub(chat_id,board,enabled):
    with sqlite3.connect(DB_PATH) as db:
        db.execute('INSERT INTO bot_subscriptions(chat_id,board,enabled) VALUES(?,?,?) ON CONFLICT(chat_id,board) DO UPDATE SET enabled=excluded.enabled',(chat_id,board,1 if enabled else 0));db.commit()

def all_subscribers(board):
    with sqlite3.connect(DB_PATH) as db:
        ids=[r[0] for r in db.execute('SELECT chat_id FROM bot_subscriptions WHERE board=? AND enabled=1',(board,))]
    return [x for x in ids if has_access(x)]

def register_bot_user(msg):
    if not isinstance(msg,dict):return False
    chat=msg.get('chat') or {}; u=msg.get('from') or {}
    chat_id=chat.get('id')
    if not chat_id or is_group_chat_id(chat_id):return False
    now=time.time();text=str(msg.get('text') or '').strip();action=(text.split(maxsplit=1)[0] if text else 'message')[:80]
    is_start=1 if action.split('@',1)[0].lower()=='/start' else 0
    with sqlite3.connect(DB_PATH) as db:
        existed=bool(db.execute('SELECT 1 FROM bot_users WHERE chat_id=?',(int(chat_id),)).fetchone())
        db.execute('''INSERT INTO bot_users(chat_id,username,first_name,last_name,balance,created_at,updated_at,last_seen,last_action,action_count,start_count,callback_count,last_chat_type)
                      VALUES(?,?,?,?,0,?,?,?,?,1,?,0,?)
                      ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username,
                      first_name=excluded.first_name,last_name=excluded.last_name,updated_at=excluded.updated_at,
                      last_seen=excluded.last_seen,last_action=excluded.last_action,
                      action_count=bot_users.action_count+1,start_count=bot_users.start_count+excluded.start_count,
                      last_chat_type=excluded.last_chat_type''',
                   (int(chat_id),u.get('username') or '',u.get('first_name') or '',u.get('last_name') or '',now,now,now,action,is_start,chat.get('type') or 'private'))
        db.execute('INSERT INTO bot_user_events(chat_id,event_type,action,created_at) VALUES(?,?,?,?)',
                   (int(chat_id),'message',action,now))
        db.commit()
    return not existed

def register_callback_user(q):
    if not isinstance(q,dict):return
    msg=q.get('message') or {};chat=msg.get('chat') or {};u=q.get('from') or {};chat_id=chat.get('id')
    if not chat_id or is_group_chat_id(chat_id):return
    now=time.time();action=('BTN:'+str(q.get('data') or ''))[:80]
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''INSERT INTO bot_users(chat_id,username,first_name,last_name,balance,created_at,updated_at,last_seen,last_action,action_count,start_count,callback_count,last_chat_type)
                      VALUES(?,?,?,?,0,?,?,?,?,1,0,1,?)
                      ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username,
                      first_name=excluded.first_name,last_name=excluded.last_name,updated_at=excluded.updated_at,
                      last_seen=excluded.last_seen,last_action=excluded.last_action,
                      action_count=bot_users.action_count+1,callback_count=bot_users.callback_count+1,
                      last_chat_type=excluded.last_chat_type''',
                   (int(chat_id),u.get('username') or '',u.get('first_name') or '',u.get('last_name') or '',now,now,now,action,chat.get('type') or 'private'))
        db.execute('INSERT INTO bot_user_events(chat_id,event_type,action,created_at) VALUES(?,?,?,?)',
                   (int(chat_id),'callback',action,now));db.commit()

def bot_user_row(chat_id):
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute('''SELECT username,first_name,last_name,balance,created_at,updated_at,last_seen,last_action,
                               action_count,start_count,callback_count,last_chat_type
                        FROM bot_users WHERE chat_id=?''',(int(chat_id),)).fetchone()
    if not r:return {'username':'','first_name':'','last_name':'','balance':0,'action_count':0,'start_count':0,'callback_count':0}
    keys=('username','first_name','last_name','balance','created_at','updated_at','last_seen','last_action','action_count','start_count','callback_count','last_chat_type')
    out=dict(zip(keys,r));out['balance']=int(out.get('balance') or 0);return out

def game_setting(game):
    game=str(game or '').lower().strip()
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute('SELECT enabled,status,reason,play_url,updated_by,updated_at FROM bot_game_settings WHERE game=?',(game,)).fetchone()
    if not r:return {'game':game,'enabled':True,'status':'online','reason':'','play_url':'','updated_by':None,'updated_at':None}
    return {'game':game,'enabled':bool(r[0]),'status':r[1] or 'online','reason':r[2] or '',
            'play_url':r[3] or '','updated_by':r[4],'updated_at':r[5]}

def game_operational(game):
    g=game_setting(game);return bool(g.get('enabled')) and g.get('status')=='online'

def game_state_icon(game):
    st=game_setting(game)
    return '🟢' if game_operational(game) else ('🛠' if st.get('status')=='maintenance' else '🔴')

def game_state_text(game):
    st=game_setting(game);name=GAME_TITLES.get(game,str(game).upper())
    state='ĐANG HOẠT ĐỘNG' if game_operational(game) else ('BẢO TRÌ' if st.get('status')=='maintenance' else 'TẠM TẮT DO LỖI' if st.get('status')=='error' else 'ĐANG TẮT')
    reason=st.get('reason') or ('Hệ thống hoạt động bình thường.' if game_operational(game) else 'Admin chưa ghi lý do.')
    link=st.get('play_url') or 'CHƯA CÀI'
    return (f"<b>{game_state_icon(game)} {html.escape(name)}</b>\n"
            f"<i>TRẠNG THÁI GAME</i>\n{BOT_DIV}\n"
            f"📌 Trạng thái  <b>{state}</b>\n"
            f"📝 Lý do  {html.escape(reason)}\n"
            f"🌐 Link chơi  <i>{html.escape(link)}</i>")

def set_game_link(game,url,admin_id=None):
    game=str(game or '').lower().strip();url=str(url or '').strip()
    if game not in {c.get('game') for c in BOARDS.values()}:raise ValueError('Game không tồn tại')
    if url and not url.startswith(('http://','https://')):raise ValueError('Link phải bắt đầu bằng http:// hoặc https://')
    now=time.time();st=game_setting(game)
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''INSERT INTO bot_game_settings(game,enabled,status,reason,play_url,updated_by,updated_at)
                      VALUES(?,?,?,?,?,?,?) ON CONFLICT(game) DO UPDATE SET play_url=excluded.play_url,
                      updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                   (game,1 if st.get('enabled') else 0,st.get('status') or 'online',st.get('reason') or '',url,
                    int(admin_id) if admin_id is not None else None,now));db.commit()
    return game_setting(game)

def _fmt_dt(ts):
    if not ts:return '---'
    try:return time.strftime('%d/%m/%Y %H:%M:%S',time.localtime(float(ts)))
    except:return '---'

def is_admin(chat_id):
    try:return int(chat_id) in ADMIN_IDS
    except:return False

def _access_row(chat_id):
    with sqlite3.connect(DB_PATH) as db:
        return db.execute(
            'SELECT enabled,granted_by,updated_at,expires_at,access_label,purchased_at FROM bot_access WHERE chat_id=?',
            (int(chat_id),)
        ).fetchone()

def access_info(chat_id):
    if is_group_chat_id(chat_id):
        g=get_group_settings(chat_id)
        return {'active':bool(g.get('enabled')),'expires_at':None,'remaining':None,
                'label':'GROUP','enabled':bool(g.get('enabled'))}
    if is_admin(chat_id): return {'active':True,'expires_at':None,'remaining':None,'label':'ADMIN','enabled':True}
    if not BOT_REQUIRE_ACCESS: return {'active':True,'expires_at':None,'remaining':None,'label':'OPEN','enabled':True}
    r=_access_row(chat_id)
    if not r:return {'active':False,'expires_at':None,'remaining':0,'label':'NONE','enabled':False}
    enabled,granted_by,updated_at,expires_at,label,purchased_at=r; now=time.time()
    expired=expires_at is not None and float(expires_at)<=now
    if enabled and expired:
        with sqlite3.connect(DB_PATH) as db:
            db.execute('UPDATE bot_access SET enabled=0,updated_at=? WHERE chat_id=?',(now,int(chat_id)))
            db.execute('UPDATE bot_subscriptions SET enabled=0 WHERE chat_id=?',(int(chat_id),));db.commit()
        enabled=0
    remaining=None if expires_at is None else max(0,float(expires_at)-now)
    return {'active':bool(enabled) and not expired,'expires_at':expires_at,'remaining':remaining,
            'label':label or 'manual','enabled':bool(enabled),'granted_by':granted_by,'updated_at':updated_at,'purchased_at':purchased_at}

def has_access(chat_id):
    if is_group_chat_id(chat_id): return group_enabled(chat_id)
    if is_admin(chat_id): return True
    if not BOT_REQUIRE_ACCESS: return True
    return bool(access_info(chat_id).get('active'))

def grant_access(chat_id,admin_id=None,enabled=True,preset=None,expires_at=None,access_label=None):
    now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """INSERT INTO bot_access(chat_id,enabled,granted_by,updated_at,expires_at,access_label,purchased_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled,
               granted_by=excluded.granted_by,updated_at=excluded.updated_at,
               expires_at=excluded.expires_at,access_label=excluded.access_label,
               purchased_at=COALESCE(bot_access.purchased_at,excluded.purchased_at)""",
            (int(chat_id),1 if enabled else 0,int(admin_id) if admin_id is not None else None,now,
             expires_at,access_label or ('manual' if enabled else 'locked'),now if enabled else None)
        )
        if not enabled: db.execute('UPDATE bot_subscriptions SET enabled=0 WHERE chat_id=?',(int(chat_id),))
        db.commit()

def admin_health_text():
    with sqlite3.connect(DB_PATH) as db:
        state={b:(u,ok,err) for b,u,ok,err in db.execute('SELECT board,updated_at,source_ok,last_error FROM board_state')}
    now=time.time();lines=[f'<b>📡 {BOT_NAME} • API STATUS</b>',BOT_DIV]
    for b in BOARDS:
        u,ok,err=state.get(b,(0,0,'chưa có dữ liệu'));age=max(0,int(now-u)) if u else -1
        icon='🟢' if ok and age<=max(15,int(POLL_SECONDS*8)) else '🟡' if ok else '🔴';suffix=f' • {age}s' if age>=0 else ''
        lines.append(f"{icon} <b>{html.escape(board_label(b))}</b>{suffix}")
        if not ok and err:lines.append(f"<i>↳ {html.escape(str(err)[:90])}</i>")
    return '\n'.join(lines)[:4000]

GAME_TITLES={'sunwin':'☀️ SUNWIN','lc79':'🎲 LC79'}

def boards_for_game(game):
    return [b for b in available_bot_boards() if b.split(':',1)[0]==game]

def cau_token(board,result):
    if board=='lc79:xocdia':
        return 'C' if result=='TÀI' else 'L' if result=='XỈU' else '?'
    if board.startswith('baccarat:'):
        return 'P' if result=='TÀI' else 'B' if result=='XỈU' else '?'
    return 'T' if result=='TÀI' else 'X' if result=='XỈU' else '?'

def cau_icon(board,result):
    if board=='lc79:xocdia':
        return '⚪' if result=='TÀI' else '🟣'
    if board.startswith('baccarat:'):
        return '🔵' if result=='TÀI' else '🔴'
    return '🔴' if result=='TÀI' else '🔵'

def current_cau(board,limit=12):
    rows=load_rows(board,max(20,limit))[-limit:]
    vals=[r.get('result') for r in rows if r.get('result') in ('TÀI','XỈU')]
    if not vals:return {'text':'---','icons':'','count':0}
    return {'text':' '.join(cau_token(board,x) for x in vals),
            'icons':' '.join(cau_icon(board,x) for x in vals),
            'count':len(vals)}

def game_cau_overview(game):
    lines=[f"{GAME_TITLES.get(game,game)} · CẦU HIỆN TẠI"]
    for b in boards_for_game(game):
        c=current_cau(b,10)
        label=board_label(b)
        if game!='baccarat':
            game_name=GAME_TITLES.get(game,game).split(' ',1)[-1]
            label=label.replace(game_name+' ','')
        else:
            label=label.replace('BACCARAT · ','')
        lines.append(f"• {label}: {c['text']}")
        if c['icons']: lines.append(f"  {c['icons']}")
    return '\n'.join(lines)[:3500]

BOT_NAME='ONGCHUNHACAI💯'

BOT_DIV='━━━━━━━━━━━━━━━━'

BOT_DIV_SOFT='┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄'

def _board_source(board):
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute('SELECT updated_at,source_ok,last_error FROM board_state WHERE board=?',(board,)).fetchone()
    if not r:return {'icon':'⚪','ok':False,'age':None,'error':'chưa có dữ liệu'}
    updated,ok,err=r
    age=max(0,int(time.time()-updated)) if updated else None
    fresh=bool(ok) and age is not None and age<=max(18,int(POLL_SECONDS*10))
    return {'icon':'🟢' if fresh else ('🟡' if ok else '🔴'),'ok':bool(ok),'age':age,'error':err}

def _short_board_label(board):
    game=board.split(':',1)[0]; label=board_label(board)
    if game!='baccarat':
        game_name=GAME_TITLES.get(game,game).split(' ',1)[-1]
        label=label.replace(game_name+' ','')
    else: label=label.replace('BACCARAT · ','')
    return label

def _compact_cau(board,limit=7):
    return current_cau(board,limit)['text'].replace(' ','')

def bot_cau_text(board,limit=24):
    c=current_cau(board,limit); rows=load_rows(board,max(30,limit))[-limit:]
    lines=[f"<b>〽️ CẦU • {html.escape(board_label(board))}</b>","<i>24 PHIÊN GẦN NHẤT</i>",BOT_DIV]
    if not rows:return '\n'.join(lines+['<i>Chưa có dữ liệu.</i>'])
    lines += [f"<b>{c['text']}</b>"]
    if c['icons']:lines.append(c['icons'])
    vals=[r.get('result') for r in rows if r.get('result') in ('TÀI','XỈU')]
    rs=_run_stats(vals)
    lines += ['',BOT_DIV_SOFT]
    if rs.get('current'):lines.append(f"⚡ Nhịp hiện tại  <b>{display_pred(board,rs.get('current_side'))} ×{rs.get('current')}</b>")
    lines.append(f"📚 Mẫu hiển thị  <b>{len(vals)} phiên</b>")
    return '\n'.join(lines)[:4000]

async def tg_panel(client,q,text,reply_markup=None):
    msg=(q or {}).get('message') or {};chat_id=(msg.get('chat') or {}).get('id');message_id=msg.get('message_id')
    if not chat_id:return None
    payload={'chat_id':chat_id,'message_id':message_id,'text':text,'disable_web_page_preview':True}
    if isinstance(text,str) and ('<b>' in text or '<i>' in text):payload['parse_mode']='HTML'
    if reply_markup is not None:payload['reply_markup']=reply_markup
    try:
        url=f'https://api.telegram.org/bot{BOT_TOKEN}/editMessageText'
        r=await client.post(url,json=payload,timeout=30);data=r.json()
        if data.get('ok'):return data.get('result')
        if 'message is not modified' in str(data.get('description','')).lower():return msg
    except Exception:pass
    send={'chat_id':chat_id,'text':text,'disable_web_page_preview':True}
    if isinstance(text,str) and ('<b>' in text or '<i>' in text):send['parse_mode']='HTML'
    if reply_markup is not None:send['reply_markup']=reply_markup
    return await tg_call(client,'sendMessage',send)

def history_stats(board,limit=100):
    h=get_prediction_history(board,limit)
    settled=[x for x in h if x.get('actual') is not None and x.get('ok') is not None]
    wins=sum(1 for x in settled if x.get('ok'))
    losses=len(settled)-wins
    pending=sum(1 for x in h if x.get('actual') is None)
    # result streak over settled items newest -> older
    streak=0; streak_ok=None
    for x in settled:
        v=bool(x.get('ok'))
        if streak_ok is None: streak_ok=v;streak=1
        elif v==streak_ok: streak+=1
        else: break
    return {
        'wins':wins,'losses':losses,'settled':len(settled),'pending':pending,
        'accuracy':round(wins/len(settled)*100,1) if settled else None,
        'streak':streak,'streak_ok':streak_ok
    }

def _round_line(board,r):
    rid=str(r.get('id','---'))
    side=display_pred(board,r.get('result'))
    d=r.get('dice') or []
    sm=r.get('sum')
    extra=''
    if len(d)>=3:
        extra=f" · 🎲{d[0]}-{d[1]}-{d[2]}={sm if sm is not None else sum(d[:3])}"
    elif board=='lc79:xocdia':
        m=r.get('meta') or {}
        red=m.get('red_count');white=m.get('white_count')
        if isinstance(red,int):
            extra=f" · 🔴{red}/⚪{white if isinstance(white,int) else 4-red}"
    elif sm is not None:
        extra=f" · tổng {sm}"
    return f"#{rid} · {side}{extra}"

def format_round_history(board,limit=12):
    rows=load_rows(board,max(20,limit))[-limit:]
    if not rows:return f"🧾 {board_label(board)} · chưa có lịch sử kết quả."
    lines=[f"<b>🧾 KẾT QUẢ • {html.escape(board_label(board))}</b>",f"<i>{len(rows)} phiên gần nhất</i>",BOT_DIV]
    for r in reversed(rows):lines.append('• '+_round_line(board,r))
    return '\n'.join(lines)[:4000]

def format_all_history(limit_per_board=40):
    lines=[f"<b>📚 {BOT_NAME} • TỔNG LỊCH SỬ</b>",BOT_DIV];count=0
    for b in available_bot_boards():
        st=history_stats(b,limit_per_board);rows=load_rows(b,1);last=rows[-1] if rows else None
        if st['settled']==0 and not last:continue
        acc=f"{st['accuracy']}%" if st['accuracy'] is not None else '--';streak=''
        if st['streak']:streak=f" • {'🔥' if st['streak_ok'] else '👾'}x{st['streak']}"
        lines.append(f"<b>{html.escape(board_label(b))}</b>")
        lines.append(f"<i>🔥 {st['wins']} • 👾 {st['losses']} • {acc}{streak}</i>")
        if last:lines.append(f"KQ #{last.get('id')}  •  {display_pred(b,last.get('result'))}")
        lines.append('')
        count+=1
        if len('\n'.join(lines))>3600:break
    if count==0:lines.append('<i>Chưa có lịch sử.</i>')
    return '\n'.join(lines).strip()[:4000]

def prediction_result_detail(board,item):
    """Use joined history details first, then exact-session fallback from rounds."""
    if not item:return {'dice':[],'sum':None,'meta':{}}
    d=list(item.get('dice') or [])[:3]
    total=item.get('sum')
    if len(d)>=3 or total is not None:
        return {'dice':d,'sum':total,'meta':{}}
    sess=canonical_session(item.get('session'),item.get('session'))
    with sqlite3.connect(DB_PATH) as db:
        r=db.execute('SELECT d1,d2,d3,total,meta_json FROM rounds WHERE board=? AND session=?',
                     (board,str(sess))).fetchone()
    if not r:return {'dice':[],'sum':None,'meta':{}}
    d=[x for x in r[:3] if x is not None]
    try:meta=json.loads(r[4]) if r[4] else {}
    except:meta={}
    return {'dice':d[:3],'sum':r[3],'meta':meta}

def format_prediction(board,pred):
    src=_board_source(board);title=board_label(board)
    if not pred:
        return (f"<b>🎯 {html.escape(title)}</b>  {src['icon']}\n"
                f"<i>⏳ Đang đồng bộ dữ liệu…</i>")
    model=pred.get('model') or {};st=history_stats(board,20)
    acc=f"{st['accuracy']}%" if st['accuracy'] is not None else '--'
    recent=get_prediction_history(board,12);last=next((x for x in recent if x.get('actual') is not None),None)
    cau=current_cau(board,8);agree=round(float(model.get('meta_agreement',.5))*100)
    conf=int(pred.get('confidence',50) or 50);next_pred=display_pred(board,pred.get('prediction'))
    if conf>=68:strength='MẠNH';strength_icon='🔥'
    elif conf>=60:strength='KHÁ';strength_icon='⚡'
    else:strength='THẬN TRỌNG';strength_icon='🟡'
    lines=[f"<b>🎯 {html.escape(title)}</b>  {src['icon']}",f"<code>{cau['text']}</code>",BOT_DIV]
    if last:
        verdict='🔥 HÚP' if last.get('ok') else '👾 GÃY';detail=prediction_result_detail(board,last)
        prev=display_pred(board,last.get('prediction'));actual=display_pred(board,last.get('actual'))
        lines += [f"↩ <b>#{last.get('session')} · {verdict}</b>  {prev} → <b>{actual}</b>"]
        if board!='lc79:xocdia' and not board.startswith('baccarat:'):
            d=detail.get('dice') or [];total=detail.get('sum')
            if len(d)>=3:
                if total is None:total=sum(int(v) for v in d[:3])
                lines.append(f"<i>🎲 {d[0]} • {d[1]} • {d[2]}  =  {total}</i>")
        lines += [BOT_DIV_SOFT]
    lines += [f"⚡ <b>#{pred.get('session','---')} · {next_pred}</b>",
              f"{strength_icon} <b>{conf}% · {strength}</b>",
              f"<i>W20 {st['wins']}-{st['losses']} · {acc}  •  Đồng thuận {agree}%</i>"]
    return '\n'.join(lines)[:4000]

def format_history(board,limit=12):
    h=get_prediction_history(board,limit)
    if not h:return f"📜 {board_label(board)} · chưa có lịch sử."
    st=history_stats(board,max(20,limit));acc=f"{st['accuracy']}%" if st['accuracy'] is not None else '--'
    lines=[f"<b>📜 LỊCH SỬ • {html.escape(board_label(board))}</b>",f"<i>W20  🔥 {st['wins']}  •  👾 {st['losses']}  •  {acc}</i>",BOT_DIV]
    for x in h:
        pred=display_pred(board,x.get('prediction'))
        if x.get('actual') is None:
            lines.append(f"⏳ <b>#{x.get('session')}</b>  •  {pred}  •  {x.get('confidence')}%")
            continue
        mark='🔥' if x.get('ok') else '👾';label='HÚP' if x.get('ok') else 'GÃY';actual=display_pred(board,x.get('actual'))
        detail=prediction_result_detail(board,x);suffix=''
        if not board.startswith('baccarat:') and board!='lc79:xocdia':
            d=detail.get('dice') or []
            if len(d)>=3:
                total=detail.get('sum');total=sum(int(v) for v in d[:3]) if total is None else total
                suffix=f"  •  🎲 {d[0]}-{d[1]}-{d[2]}={total}"
        lines.append(f"{mark} <b>#{x.get('session')} • {label}</b>  {pred} → {actual}{suffix}")
    return '\n'.join(lines)[:4000]

async def tg_call(client,method,payload=None):
    if not BOT_TOKEN: return None
    payload=dict(payload or {})
    txt=payload.get('text')
    if method in ('sendMessage','editMessageText') and isinstance(txt,str) and ('<b>' in txt or '<i>' in txt):
        payload.setdefault('parse_mode','HTML')
    url=f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    r=await client.post(url,json=payload,timeout=30)
    r.raise_for_status(); data=r.json()
    return data.get('result') if data.get('ok') else None

async def bot_notify_prediction(board,pred):
    if not pred: return
    chats=all_subscribers(board)
    if not chats: return
    text='🔔 AUTO · '+format_prediction(board,pred)
    async with httpx.AsyncClient() as c:
        for chat in chats:
            try:
                old=None
                with sqlite3.connect(DB_PATH) as db:
                    old=db.execute('SELECT message_id FROM bot_auto_messages WHERE chat_id=? AND board=?',(chat,board)).fetchone()
                if old:
                    try: await tg_call(c,'deleteMessage',{'chat_id':chat,'message_id':old[0]})
                    except: pass
                msg=await tg_call(c,'sendMessage',{'chat_id':chat,'text':text,'disable_web_page_preview':True,'reply_markup':bot_board_keyboard(board,chat)})
                if msg and msg.get('message_id'):
                    with sqlite3.connect(DB_PATH) as db:
                        db.execute('''INSERT INTO bot_auto_messages(chat_id,board,session,message_id,created_at)
                                      VALUES(?,?,?,?,?) ON CONFLICT(chat_id,board) DO UPDATE SET
                                      session=excluded.session,message_id=excluded.message_id,created_at=excluded.created_at''',
                                   (chat,board,str(pred.get('session','')),int(msg['message_id']),time.time()))
                        db.commit()
            except Exception:
                pass

async def bot_clear_settled_prediction(board,session):
    async with httpx.AsyncClient() as c:
        with sqlite3.connect(DB_PATH) as db:
            rows=db.execute('SELECT chat_id,message_id FROM bot_auto_messages WHERE board=? AND session=?',(board,str(session))).fetchall()
        for chat,message_id in rows:
            try: await tg_call(c,'deleteMessage',{'chat_id':chat,'message_id':message_id})
            except: pass
        if rows:
            with sqlite3.connect(DB_PATH) as db:
                db.execute('DELETE FROM bot_auto_messages WHERE board=? AND session=?',(board,str(session)));db.commit()

def _run_stats(seq):
    if not seq:return {'current':0,'current_side':None,'max_tai':0,'max_xiu':0,'runs':[]}
    runs=[];side=seq[0];n=1
    for x in seq[1:]:
        if x==side:n+=1
        else:runs.append((side,n));side=x;n=1
    runs.append((side,n))
    return {'current':runs[-1][1],'current_side':runs[-1][0],
            'max_tai':max([n for side,n in runs if side=='TÀI'] or [0]),
            'max_xiu':max([n for side,n in runs if side=='XỈU'] or [0]),
            'runs':runs[-20:]}

def _v49_user_name(chat_id):
    u=bot_user_row(chat_id)
    if u.get('username'):return '@'+u['username'].lstrip('@')
    name=((u.get('first_name') or '')+' '+(u.get('last_name') or '')).strip()
    return name or '---'

def v49_access_card(chat_id):
    active=has_access(chat_id)
    return (f"<b>💯 {BOT_NAME}</b>\n"
            f"<i>SUNWIN • LC79 · ELITE ENGINE</i>\n{BOT_DIV}\n"
            f"👤 <b>{html.escape(_v49_user_name(chat_id))}</b>\n"
            f"🆔 <code>{chat_id}</code>\n"
            f"🔐 Quyền  <b>{'ĐÃ MỞ' if active else 'CHƯA CẤP'}</b>\n"
            f"{BOT_DIV_SOFT}\n"
            + ("<i>Chọn game bên dưới để bắt đầu.</i>" if active else "<i>Gửi ID trên cho admin để được cấp quyền sử dụng.</i>"))

def v49_guest_keyboard():
    return {'inline_keyboard':[[{'text':'↻ KIỂM TRA QUYỀN','callback_data':'checkaccess'}]]}

def bot_home_text(chat_id):
    boards=available_bot_boards();live=sum(1 for b in boards if _board_source(b)['icon']=='🟢')
    selected=get_selected_board(chat_id)
    lastline='Chưa chọn bàn'
    if selected in boards:
        p=get_shared_prediction(selected) or {}
        lastline=f"{_short_board_label(selected)} · {display_pred(selected,p.get('prediction'))} · {p.get('confidence','--')}%"
    return (f"<b>💯 {BOT_NAME}</b>\n"
            f"<i>2 GAME • LIVE PREDICTION</i>\n{BOT_DIV}\n"
            f"☀️ <b>SUNWIN</b>    🎲 <b>LC79</b>\n"
            f"📡 API  <b>{live}/{len(boards)}</b>  •  🧠 <b>55 MODEL</b>\n"
            f"👤 {html.escape(_v49_user_name(chat_id))}\n"
            f"🔐 <i>Gửi MD5/SHA256 trực tiếp để phân tích.</i>\n"
            f"{BOT_DIV_SOFT}\n"
            f"<i>🎯 {html.escape(lastline)}</i>")

def bot_games_keyboard(chat_id):
    if not has_access(chat_id) and not is_admin(chat_id):return v49_guest_keyboard()
    rows=[
      [{'text':f"{game_state_icon('sunwin')} ☀️ SUNWIN",'callback_data':'game|sunwin'},
       {'text':f"{game_state_icon('lc79')} 🎲 LC79",'callback_data':'game|lc79'}],
      [{'text':'📜 LỊCH SỬ','callback_data':'histall'}]
    ]
    if is_admin(chat_id):rows.append([{'text':'◆ QUẢN TRỊ','callback_data':'adminhome'}])
    return {'inline_keyboard':rows}

def bot_game_keyboard(game,chat_id):
    rows=[]
    for board in boards_for_game(game):
        src=_board_source(board);p=get_shared_prediction(board) or {};pred=display_pred(board,p.get('prediction')) if p else '---'
        conf=p.get('confidence','--') if p else '--';cau=_compact_cau(board,6)
        rows.append([{'text':f"{src['icon']} {_short_board_label(board)}  •  {pred} {conf}%  •  {cau}",'callback_data':'sel|'+board}])
    link=game_setting(game).get('play_url')
    if link:rows.append([{'text':'↗ MỞ GAME','url':link}])
    rows.append([{'text':'‹ 2 GAME','callback_data':'games'},{'text':'⌂ HOME','callback_data':'home'}])
    return {'inline_keyboard':rows}

def bot_board_keyboard(board,chat_id=None):
    game=board.split(':',1)[0]
    rows=[
      [{'text':'📜 LỊCH SỬ','callback_data':'hist|'+board},{'text':'〽️ CẦU','callback_data':'cau|'+board}]
    ]
    link=game_setting(game).get('play_url')
    if link:rows.append([{'text':'↗ CHƠI TRỰC TIẾP','url':link}])
    rows.append([{'text':'‹ BÀN GAME','callback_data':'game|'+game},{'text':'⌂ HOME','callback_data':'home'}])
    return {'inline_keyboard':rows}

def _v50_stop_auto(chat_id):
    for _board in BOARDS:
        if _board.split(':',1)[0] in ('sunwin','lc79'):
            try:set_sub(chat_id,_board,False)
            except Exception:pass

def _v50_start_auto(chat_id,board):
    _v50_stop_auto(chat_id)
    try:set_sub(chat_id,board,True)
    except Exception:pass

def permission_text(chat_id):
    active=has_access(chat_id)
    u=bot_user_row(chat_id)
    return (f"<b>👤 THÔNG TIN USER</b>\n{BOT_DIV}\n"
            f"🆔 <code>{chat_id}</code>\n"
            f"👤 {html.escape(_v49_user_name(chat_id))}\n"
            f"🔐 Quyền  <b>{'✅ ĐANG MỞ' if active else '⛔ ĐANG KHÓA'}</b>\n"
            f"📲 Lượt dùng  <b>{int(u.get('action_count') or 0)}</b>  •  Nút <b>{int(u.get('callback_count') or 0)}</b>\n"
            f"🕘 Gần nhất  <b>{html.escape(str(u.get('last_action') or '---'))}</b>")

def v49_users_text(limit=40):
    now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute('''SELECT u.chat_id,u.username,u.first_name,u.last_name,u.last_action,
                                  COALESCE(u.last_seen,u.updated_at),u.action_count,
                                  COALESCE(a.enabled,0),a.expires_at
                           FROM bot_users u LEFT JOIN bot_access a ON a.chat_id=u.chat_id
                           ORDER BY COALESCE(u.last_seen,u.updated_at) DESC LIMIT ?''',(int(limit),)).fetchall()
    lines=[f"<b>👥 NGƯỜI DÙNG · {len(rows)}</b>",BOT_DIV]
    for uid,un,fn,ln,act,seen,cnt,en,exp in rows:
        ok=bool(en) and (exp is None or float(exp)>now)
        name='@'+un if un else ((fn or '')+' '+(ln or '')).strip() or str(uid)
        lines.append(f"{'🟢' if ok else '⚪'} <code>{uid}</code> · {html.escape(name)}")
        lines.append(f"   {int(cnt or 0)} lượt · {html.escape(str(act or '---'))}")
    if not rows:lines.append('<i>Chưa có user.</i>')
    lines += [BOT_DIV_SOFT,"<i>/thongtin ID · /capquyen ID · /thuquyen ID</i>"]
    return '\n'.join(lines)[:4000]

def v49_user_detail(uid):
    u=bot_user_row(uid);info=access_info(uid)
    created=u.get('created_at');seen=u.get('last_seen') or u.get('updated_at')
    return (f"<b>👤 USER DETAIL</b>\n{BOT_DIV}\n"
            f"🆔 <code>{uid}</code>\n"
            f"👤 {html.escape(_v49_user_name(uid))}\n"
            f"🔐 <b>{'ĐÃ CẤP QUYỀN' if info.get('active') else 'CHƯA CÓ QUYỀN'}</b>\n"
            f"📲 Tổng thao tác  <b>{int(u.get('action_count') or 0)}</b>\n"
            f"▶️ /start  <b>{int(u.get('start_count') or 0)}</b>  •  Nút <b>{int(u.get('callback_count') or 0)}</b>\n"
            f"🧭 Cuối  <b>{html.escape(str(u.get('last_action') or '---'))}</b>\n"
            f"📅 Tạo  {(_fmt_dt(created) if created else '---')}\n"
            f"🕘 Online  {(_fmt_dt(seen) if seen else '---')}")

def v49_admin_user_keyboard(uid):
    return {'inline_keyboard':[
      [{'text':'✅ CẤP QUYỀN','callback_data':f'v49grant|{int(uid)}'},{'text':'⛔ THU QUYỀN','callback_data':f'v49revoke|{int(uid)}'}],
      [{'text':'↻ XEM LẠI','callback_data':f'v49user|{int(uid)}'},{'text':'‹ ADMIN','callback_data':'adminhome'}]
    ]}

def _v49_send_payload(chat_id,text,reply_markup=None):
    p={'chat_id':chat_id,'text':text,'disable_web_page_preview':True}
    if '<b>' in text or '<i>' in text or '<code>' in text:p['parse_mode']='HTML'
    if reply_markup:p['reply_markup']=reply_markup
    return p

def ensure_hash_tables():
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS bot_hash_analyses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,user_id INTEGER,chat_type TEXT,
            hash_type TEXT NOT NULL,hash_value TEXT NOT NULL,prediction TEXT NOT NULL,
            tai_pct REAL NOT NULL,xiu_pct REAL NOT NULL,agreement REAL NOT NULL,created_at REAL NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_hash_analyses_created ON bot_hash_analyses(created_at)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_hash_analyses_user ON bot_hash_analyses(user_id,created_at)')
        db.commit()

def _hash_kind(text):
    z=(text or '').strip().lower()
    if re.fullmatch(r'[0-9a-f]{32}',z): return 'MD5',z
    if re.fullmatch(r'[0-9a-f]{64}',z): return 'SHA256',z
    return None,None

def _looks_like_hash_attempt(text):
    z=(text or '').strip()
    if not z:return False
    if len(z) in (32,64):return True
    return bool(re.fullmatch(r'[0-9a-fA-F]{16,80}',z))

def _hex_entropy(z):
    if not z:return 0.0
    cnt={}
    for c in z:cnt[c]=cnt.get(c,0)+1
    n=len(z);e=0.0
    for v in cnt.values():
        p=v/n
        if p>0:e-=p*math.log2(p)
    return e

def _clip(v,lo,hi):return max(lo,min(hi,float(v)))

def _prob_from_total(total):return _clip(0.5+(float(total)-10.5)/15.0*0.34,0.34,0.66)

def hash_ultra_predict(hash_hex):
    z=(hash_hex or '').lower()
    cached=_hash_fast_cache.get(z)
    if cached is not None:return dict(cached)
    L=len(z);kind='MD5' if L==32 else 'SHA256'
    n=int(z,16);nibs=[int(c,16) for c in z];bs=bytes.fromhex(z);models=[]
    def add(name,p,w):models.append((name,_clip(p,0.18,0.82),float(w)))
    d1=((n>>0)%6)+1;d2=((n>>8)%6)+1;d3=((n>>16)%6)+1
    add('DICE_BYTE',_prob_from_total(d1+d2+d3),1.15)
    last12=int(z[-12:],16);q1=(last12%6)+1;q2=((last12//6)%6)+1;q3=((last12//36)%6)+1
    add('DICE_LAST12',_prob_from_total(q1+q2+q3),1.00)
    thirds=[z[:L//3],z[L//3:2*L//3],z[2*L//3:]];sd=[(int(x,16)%6)+1 for x in thirds if x]
    add('DICE_SEGMENT',_prob_from_total(sum(sd[:3])),1.05)
    dec=str(n);odd=sum((ord(c)-48)%2 for c in dec);even=len(dec)-odd
    add('DECIMAL_PARITY',0.5+((odd-even)/max(1,len(dec)))*0.22,0.75)
    digit_vals=[int(c,16) for c in z if c.isdigit()];letter_vals=[ord(c) for c in z if c.isalpha()]
    if digit_vals and letter_vals:
        ev=sum(1 for x in digit_vals if x%2==0);od=len(digit_vals)-ev
        raw=(sum(digit_vals)+sum(letter_vals)+ev*5-od*3)%100
        add('COMPLEX_SCORE',0.5+(raw-50)/100*0.38,0.85)
    votes=[1 if int(z[-2:],16)%2==0 else 0,1 if sum(nibs)%2==0 else 0]
    digits=sum(c.isdigit() for c in z);letters=L-digits;votes.append(1 if digits>=letters else 0)
    add('BIT_VOTING',0.38+(sum(votes)/3)*0.24,0.95)
    raw_xiu=n%100;raw_tai=100-raw_xiu;add('MOD100',0.5+(raw_tai-50)/100*0.24,0.62)
    char_sum=sum(ord(c) for c in z);add('CHARCODE_PARITY',0.57 if char_sum%2==0 else 0.43,0.55)
    mean=sum(nibs)/L;add('HEX_MEAN',0.5+(mean-7.5)/15*0.36,0.92)
    one_bits=sum(b.bit_count() for b in bs);ratio=one_bits/(8*len(bs));add('BIT_DENSITY',0.5+(ratio-0.5)*0.52,0.88)
    k=8 if L==64 else 4;seg_len=max(1,L//k);sv=[]
    for i in range(k):
        seg=nibs[i*seg_len:(i+1)*seg_len] if i<k-1 else nibs[i*seg_len:]
        if seg:sv.append(1 if sum(seg)/len(seg)>=7.5 else 0)
    add('SEGMENT_VOTE',0.38+(sum(sv)/max(1,len(sv)))*0.24,1.00)
    half=L//2;mirror_delta=sum(nibs[i]-nibs[-1-i] for i in range(half));add('MIRROR_FLOW',0.5+math.tanh(mirror_delta/max(8,half*5))*0.13,0.70)
    ups=sum(bs[i]>bs[i-1] for i in range(1,len(bs)));downs=sum(bs[i]<bs[i-1] for i in range(1,len(bs)));add('BYTE_TREND',0.5+((ups-downs)/max(1,len(bs)-1))*0.16,0.78)
    pos=sum((i+1)*v for i,v in enumerate(nibs))%101;add('POSITIONAL',0.5+(pos-50)/100*0.28,0.76)
    xorv=0
    for b in bs:xorv^=b
    add('XOR_FOLD',0.5+(xorv-127.5)/255*0.22,0.72)
    edge=(sum(nibs[:L//4])-sum(nibs[-L//4:]))/max(1,L//4)
    add('PREFIX_SUFFIX',0.5+math.tanh(edge/5.0)*0.12,0.76)
    qlen=max(1,L//4);qmeans=[]
    for i in range(4):
        q=nibs[i*qlen:(i+1)*qlen] if i<3 else nibs[i*qlen:]
        if q:qmeans.append(sum(q)/len(q))
    qscore=sum(1 if x>=7.5 else -1 for x in qmeans)/max(1,len(qmeans));add('QUARTILE_VOTE',0.5+qscore*0.10,0.86)
    rises=sum(nibs[i]>nibs[i-1] for i in range(1,L));falls=sum(nibs[i]<nibs[i-1] for i in range(1,L));add('NIBBLE_FLOW',0.5+((rises-falls)/max(1,L-1))*0.15,0.74)
    byte_even=sum((b&1)==0 for b in bs);add('BYTE_PARITY',0.5+((byte_even/len(bs))-.5)*0.28,0.72)
    adjxor=[bs[i]^bs[i-1] for i in range(1,len(bs))];axmean=sum(adjxor)/max(1,len(adjxor));add('ADJ_XOR',0.5+(axmean-127.5)/255*0.20,0.70)
    edgefold=(int(z[:8],16)^int(z[-8:],16))&0xffffffff;add('EDGE_FOLD',0.5+((edgefold/0xffffffff)-0.5)*0.22,0.73)
    runs=1+sum(z[i]!=z[i-1] for i in range(1,L));run_ratio=runs/L;add('HEX_RUNS',0.5+(run_ratio-0.82)*0.28,0.64)
    b2=hashlib.blake2s(z.encode(),digest_size=16).digest();b2mean=sum(b2)/len(b2);add('BLAKE2S_DEEP',0.5+(b2mean-127.5)/255*0.18,0.88)
    derived=hashlib.sha256(z.encode()).hexdigest();dn=[int(c,16) for c in derived];dmean=sum(dn)/len(dn);dedge=(int(derived[:8],16)^int(derived[-8:],16))&0xffffffff
    add('SHA_DEEP',0.5+(dmean-7.5)/15*0.20+((dedge/0xffffffff)-0.5)*0.10,1.05)
    ent=_hex_entropy(z);ent_norm=_clip(ent/4.0,0,1);unique=len(set(z))/16.0
    counts={c:z.count(c) for c in set(z)};repeated=sum(1 for v in counts.values() if v>max(2,L//12))/max(1,len(counts))
    quality=_clip(0.50+0.34*ent_norm+0.16*_clip(unique,0,1)-0.12*repeated,0.45,1.0)
    tw=sum(w for _,_,w in models);rawp=sum(p*w for _,p,w in models)/tw;sign_tai=sum(w for _,p,w in models if p>=0.5)/tw
    fused=0.66*rawp+0.34*sign_tai;direction=1 if fused>=0.5 else 0;agree=sign_tai if direction else (1-sign_tai)
    strength=50.0+max(0.0,agree-0.5)*30.0+abs(fused-0.5)*110.0+max(-2.0,min(2.0,(quality-0.75)*8.0))
    if agree<0.54:strength=min(strength,54.5)
    elif agree<0.58:strength=min(strength,58.5)
    if ent_norm<0.78:strength=min(strength,58.0)
    strength=_clip(strength,51.0,70.0)
    tai=strength if direction else 100.0-strength;tai=round(tai,2);xiu=round(100-tai,2);pred='TÀI' if direction else 'XỈU';strength=max(tai,xiu)
    level='MẠNH' if strength>=66 else 'KHÁ' if strength>=59 else 'NHẸ'
    result={'type':kind,'prediction':pred,'tai_pct':tai,'xiu_pct':xiu,'agreement':round(agree*100,1),'entropy':round(ent,3),'level':level,'models':len(models),'dice':(d1,d2,d3),'dice_total':d1+d2+d3}
    _hash_fast_cache[z]=dict(result);_hash_fast_cache_order.append(z)
    if len(_hash_fast_cache_order)>2048:
        old=_hash_fast_cache_order.pop(0);_hash_fast_cache.pop(old,None)
    return result

def format_hash_prediction(hash_hex,result=None):
    r=result or hash_ultra_predict(hash_hex)
    return (f"<b>🔐 {r['type']}</b>\nTÀI <b>{r['tai_pct']:.2f}%</b>  •  XỈU <b>{r['xiu_pct']:.2f}%</b>\n🎯 <b>{r['prediction']} · {r['level']}</b>\n<i>{r['models']} tín hiệu · đồng thuận {r['agreement']:.1f}%</i>")

def record_hash_analysis(chat_id,user_id,chat_type,hash_hex,result):
    try:
        with sqlite3.connect(DB_PATH) as db:
            db.execute('''INSERT INTO bot_hash_analyses(chat_id,user_id,chat_type,hash_type,hash_value,prediction,tai_pct,xiu_pct,agreement,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',(int(chat_id),int(user_id) if user_id else None,str(chat_type or ''),result['type'],hash_hex,result['prediction'],float(result['tai_pct']),float(result['xiu_pct']),float(result['agreement']),time.time()));db.commit()
    except Exception:pass

def register_group_actor(msg,action='hash'):
    u=msg.get('from') or {};uid=u.get('id')
    if not uid:return
    now=time.time();username=(u.get('username') or '').strip();first=(u.get('first_name') or '').strip();last=(u.get('last_name') or '').strip()
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''INSERT INTO bot_users(chat_id,username,first_name,last_name,balance,created_at,updated_at,last_seen,last_action,action_count,start_count,callback_count,last_chat_type) VALUES(?,?,?,?,0,?,?,?,?,1,0,0,'group') ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,updated_at=excluded.updated_at,last_seen=excluded.last_seen,last_action=excluded.last_action,action_count=bot_users.action_count+1,last_chat_type='group' ''',(int(uid),username,first,last,now,now,now,action));db.commit()

def hash_admin_stats():
    try:
        with sqlite3.connect(DB_PATH) as db:
            total=db.execute('SELECT COUNT(*) FROM bot_hash_analyses').fetchone()[0] or 0;md5=db.execute("SELECT COUNT(*) FROM bot_hash_analyses WHERE hash_type='MD5'").fetchone()[0] or 0;sha=db.execute("SELECT COUNT(*) FROM bot_hash_analyses WHERE hash_type='SHA256'").fetchone()[0] or 0;today=db.execute('SELECT COUNT(*) FROM bot_hash_analyses WHERE created_at>=?',(time.time()-86400,)).fetchone()[0] or 0;groups=db.execute('SELECT COUNT(*) FROM bot_group_settings WHERE enabled=1').fetchone()[0] or 0
        return int(total),int(md5),int(sha),int(today),int(groups)
    except Exception:return 0,0,0,0,0

def v49_admin_stats_text():
    now=time.time()
    with sqlite3.connect(DB_PATH) as db:
        total=int(db.execute('SELECT COUNT(*) FROM bot_users').fetchone()[0] or 0);active24=int(db.execute('SELECT COUNT(*) FROM bot_users WHERE COALESCE(last_seen,updated_at)>=?',(now-86400,)).fetchone()[0] or 0);actions=int(db.execute('SELECT COALESCE(SUM(action_count),0) FROM bot_users').fetchone()[0] or 0);starts=int(db.execute('SELECT COALESCE(SUM(start_count),0) FROM bot_users').fetchone()[0] or 0);callbacks=int(db.execute('SELECT COALESCE(SUM(callback_count),0) FROM bot_users').fetchone()[0] or 0);access=int(db.execute('SELECT COUNT(*) FROM bot_access WHERE enabled=1 AND (expires_at IS NULL OR expires_at>?)',(now,)).fetchone()[0] or 0);recent=db.execute('SELECT chat_id,username,last_action,COALESCE(last_seen,updated_at),action_count FROM bot_users ORDER BY COALESCE(last_seen,updated_at) DESC LIMIT 6').fetchall()
    htotal,hmd5,hsha,h24,groups=hash_admin_stats();boards=available_bot_boards();live=sum(1 for b in boards if _board_source(b)['icon']=='🟢')
    lines=[f"<b>📊 {BOT_NAME} · THỐNG KÊ</b>",BOT_DIV,f"👥 User <b>{total}</b>  •  24h <b>{active24}</b>  •  quyền <b>{access}</b>",f"🔐 Hash <b>{htotal}</b>  •  MD5 <b>{hmd5}</b>  •  SHA256 <b>{hsha}</b>  •  24h <b>{h24}</b>",f"👥 Nhóm tự cấp <b>{groups}</b>  •  📡 API <b>{live}/{len(boards)}</b>",f"📲 Hành động <b>{actions}</b>  •  /start <b>{starts}</b>  •  nút <b>{callbacks}</b>",BOT_DIV_SOFT,"<b>HOẠT ĐỘNG GẦN NHẤT</b>"]
    for uid,uname,act,seen,cnt in recent:
        who='@'+uname if uname else str(uid);lines.append(f"• {html.escape(who)} · {html.escape(str(act or '---'))} · {int(cnt or 0)} lượt")
    return '\n'.join(lines)[:4000]

async def bot_handle_my_chat_member(client,upd):
    chat=upd.get('chat') or {};chat_id=chat.get('id');ctype=chat.get('type') or ''
    if not chat_id or ctype not in ('group','supergroup'):return
    old=((upd.get('old_chat_member') or {}).get('status') or '').lower();new=((upd.get('new_chat_member') or {}).get('status') or '').lower();active={'member','administrator','creator'};actor=upd.get('from') or {};actor_id=actor.get('id');title=chat.get('title') or 'Telegram Group'
    if new in active and old not in active:
        try:set_group_enabled(chat_id,True,actor_id,title)
        except Exception:
            try:_ensure_group_row(chat_id,actor_id,title);set_group_enabled(chat_id,True,actor_id,title)
            except Exception:pass
        try:grant_access(chat_id,actor_id,True,'group',None,'AUTO_GROUP')
        except Exception:pass
        who='@'+actor.get('username') if actor.get('username') else (actor.get('first_name') or str(actor_id or '---'))
        try:count=int(await tg_call(client,'getChatMemberCount',{'chat_id':chat_id}) or 0)
        except Exception:count=0
        notice=(f"<b>👥 BOT ĐƯỢC THÊM VÀO NHÓM</b>\n{BOT_DIV}\n🏷 <b>{html.escape(str(title))}</b>\n🆔 <code>{chat_id}</code>\n👤 Thêm bởi {html.escape(str(who))} · <code>{actor_id or '---'}</code>\n👥 Thành viên <b>{count}</b>\n🔐 Quyền nhóm <b>ĐÃ TỰ CẤP</b>")
        for aid in ADMIN_IDS:
            try:await tg_call(client,'sendMessage',_v49_send_payload(aid,notice))
            except Exception:pass
    elif old in active and new not in active:
        try:set_group_enabled(chat_id,False,actor_id,title)
        except Exception:pass

async def bot_handle_message(client,msg):
    chat=msg.get('chat') or {};chat_id=chat.get('id');ctype=chat.get('type') or 'private';text=(msg.get('text') or '').strip();actor=(msg.get('from') or {}).get('id')
    if not chat_id:return
    cmd=text.split(maxsplit=1)[0].split('@',1)[0].lower() if text.startswith('/') else '';hkind,hval=_hash_kind(text)
    if is_group_chat_id(chat_id):
        if not group_enabled(chat_id):
            try:set_group_enabled(chat_id,True,actor,chat.get('title') or 'Telegram Group')
            except Exception:pass
        if cmd=='/start':
            register_group_actor(msg,'/start group');await tg_call(client,'sendMessage',_v49_send_payload(chat_id,f"<b>💯 {BOT_NAME}</b>\n<i>Đã hoạt động trong nhóm.</i>\n{BOT_DIV}\nGửi trực tiếp <b>MD5 32 HEX</b> hoặc <b>SHA256 64 HEX</b>."));return
        if hkind:
            result=hash_ultra_predict(hval);await tg_call(client,'sendMessage',_v49_send_payload(chat_id,format_hash_prediction(hval,result)));asyncio.create_task(asyncio.to_thread(register_group_actor,msg,'hash '+hkind));asyncio.create_task(asyncio.to_thread(record_hash_analysis,chat_id,actor,ctype,hval,result));return
        return
    new=register_bot_user(msg)
    if new:
        u=msg.get('from') or {};who='@'+u.get('username') if u.get('username') else (u.get('first_name') or '---');notice=(f"<b>👤 USER MỚI</b>\n{BOT_DIV}\nID <code>{chat_id}</code>\nUser {html.escape(who)}\nTên {html.escape(((u.get('first_name') or '')+' '+(u.get('last_name') or '')).strip())}\nLúc {_fmt_dt(time.time())}")
        for aid in ADMIN_IDS:
            try:await tg_call(client,'sendMessage',_v49_send_payload(aid,notice))
            except:pass
    if hkind:
        if not has_access(chat_id) and not is_admin(actor):return
        result=hash_ultra_predict(hval);await tg_call(client,'sendMessage',_v49_send_payload(chat_id,format_hash_prediction(hval,result)));asyncio.create_task(asyncio.to_thread(record_hash_analysis,chat_id,actor,ctype,hval,result));return
    if _looks_like_hash_attempt(text):return
    if is_admin(actor) and cmd in ('/quantri','/admin'):
        await tg_call(client,'sendMessage',_v49_send_payload(chat_id,bot_admin_home_text(),bot_admin_keyboard()));return
    if is_admin(actor) and cmd=='/thongke':await tg_call(client,'sendMessage',_v49_send_payload(chat_id,v49_admin_stats_text(),bot_admin_keyboard()));return
    if is_admin(actor) and cmd=='/nguoidung':await tg_call(client,'sendMessage',_v49_send_payload(chat_id,v49_users_text(),bot_admin_keyboard()));return
    if is_admin(actor) and cmd=='/thongtin':
        try:uid=int(text.split()[1])
        except:await tg_call(client,'sendMessage',{'chat_id':chat_id,'text':'Cú pháp: /thongtin USER_ID'});return
        await tg_call(client,'sendMessage',_v49_send_payload(chat_id,v49_user_detail(uid),v49_admin_user_keyboard(uid)));return
    if is_admin(actor) and cmd in ('/capquyen','/thuquyen'):
        try:uid=int(text.split()[1])
        except:await tg_call(client,'sendMessage',{'chat_id':chat_id,'text':f'Cú pháp: {cmd} USER_ID'});return
        grant_access(uid,actor,cmd=='/capquyen','vip' if cmd=='/capquyen' else None,None,'ACCESS' if cmd=='/capquyen' else None);await tg_call(client,'sendMessage',_v49_send_payload(chat_id,v49_user_detail(uid),v49_admin_user_keyboard(uid)));return
    if is_admin(actor) and cmd=='/kiemtraapi':await tg_call(client,'sendMessage',_v49_send_payload(chat_id,admin_health_text(),bot_admin_keyboard()));return
    if is_admin(actor) and cmd=='/doapi':
        parts=text.split(maxsplit=3)
        if len(parts)<3 or parts[1] not in BOARDS:out='Cú pháp: /doapi BOARD CURRENT_URL [HISTORY_URL]'
        elif not parts[2].startswith(('http://','https://')):out='❌ URL không hợp lệ.'
        else:set_api_override(parts[1],parts[2],parts[3] if len(parts)>3 else None);out=f'✅ Đã đổi API {parts[1]}'
        await tg_call(client,'sendMessage',{'chat_id':chat_id,'text':out});return
    if is_admin(actor) and cmd=='/linkgame':
        parts=text.split(maxsplit=2)
        if len(parts)<3 or parts[1].lower() not in ('sunwin','lc79') or not parts[2].startswith(('http://','https://')):out='Cú pháp: /linkgame sunwin|lc79 https://...'
        else:
            st=game_setting(parts[1].lower())
            with sqlite3.connect(DB_PATH) as db:db.execute('''INSERT INTO bot_game_settings(game,enabled,status,reason,play_url,updated_by,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(game) DO UPDATE SET play_url=excluded.play_url,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',(parts[1].lower(),1,st.get('status','online'),st.get('reason',''),parts[2],actor,time.time()));db.commit()
            out='✅ Đã cập nhật link '+parts[1].upper()
        await tg_call(client,'sendMessage',{'chat_id':chat_id,'text':out});return
    if cmd in ('/start','/menu','/game','/games'):
        _v50_stop_auto(chat_id)
        if not has_access(chat_id) and not is_admin(chat_id):await tg_call(client,'sendMessage',_v49_send_payload(chat_id,v49_access_card(chat_id),v49_guest_keyboard()));return
        await tg_call(client,'sendMessage',_v49_send_payload(chat_id,bot_home_text(chat_id),bot_games_keyboard(chat_id)));return
    if cmd in ('/quyen','/me','/taikhoan'):
        await tg_call(client,'sendMessage',_v49_send_payload(chat_id,permission_text(chat_id),bot_games_keyboard(chat_id) if has_access(chat_id) else v49_guest_keyboard()));return
    if not has_access(chat_id) and not is_admin(chat_id):return
    board=get_selected_board(chat_id)
    if cmd in ('/dudoan','/status'):
        txt=format_prediction(board,get_shared_prediction(board)) if board else 'Chưa chọn bàn. Bấm /game.';await tg_call(client,'sendMessage',_v49_send_payload(chat_id,txt,bot_board_keyboard(board,chat_id) if board else bot_games_keyboard(chat_id)));return
    if cmd in ('/lichsu','/history'):
        txt=format_history(board) if board else 'Chưa chọn bàn. Bấm /game.';await tg_call(client,'sendMessage',_v49_send_payload(chat_id,txt,bot_board_keyboard(board,chat_id) if board else bot_games_keyboard(chat_id)));return
    return

async def bot_handle_callback(client,q):
    msg=q.get('message') or {};chat_id=(msg.get('chat') or {}).get('id');actor=(q.get('from') or {}).get('id');data=q.get('data') or ''
    if not chat_id or is_group_chat_id(chat_id):return
    register_callback_user(q)
    try:await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id')})
    except:pass
    if data=='checkaccess':
        if has_access(chat_id) or is_admin(chat_id):await tg_panel(client,q,bot_home_text(chat_id),bot_games_keyboard(chat_id))
        else:await tg_panel(client,q,v49_access_card(chat_id),v49_guest_keyboard())
        return
    if data=='adminhome':
        if is_admin(actor):await tg_panel(client,q,bot_admin_home_text(),bot_admin_keyboard())
        return
    if data.startswith(('v49grant|','v49revoke|','v49user|')):
        if not is_admin(actor):return
        act,uidtxt=data.split('|',1)
        try:uid=int(uidtxt)
        except:return
        if act=='v49grant':grant_access(uid,actor,True,'vip',None,'ACCESS')
        elif act=='v49revoke':grant_access(uid,actor,False)
        await tg_panel(client,q,v49_user_detail(uid),v49_admin_user_keyboard(uid));return
    if data.startswith('adm|'):
        if not is_admin(actor):return
        act=data.split('|',1)[1]
        if act=='users':txt=v49_users_text()
        elif act=='stats':txt=v49_admin_stats_text()
        elif act=='health':txt=admin_health_text()
        elif act=='access':txt=(f"<b>🔐 CẤP / THU QUYỀN</b>\n{BOT_DIV}\n"
                                "/capquyen USER_ID\n/thuquyen USER_ID\n/thongtin USER_ID\n\n<i>Hoặc mở danh sách Người dùng rồi chọn user.</i>")
        else:txt=bot_admin_home_text()
        await tg_panel(client,q,txt,bot_admin_keyboard());return
    if data=='home':
        _v50_stop_auto(chat_id)
        await tg_panel(client,q,bot_home_text(chat_id) if has_access(chat_id) or is_admin(chat_id) else v49_access_card(chat_id),bot_games_keyboard(chat_id) if has_access(chat_id) or is_admin(chat_id) else v49_guest_keyboard());return
    if data=='games':
        _v50_stop_auto(chat_id)
        await tg_panel(client,q,bot_home_text(chat_id),bot_games_keyboard(chat_id));return
    if not has_access(chat_id) and not is_admin(chat_id):
        await tg_panel(client,q,v49_access_card(chat_id),v49_guest_keyboard());return
    if data.startswith('game|'):
        _v50_stop_auto(chat_id)
        game=data.split('|',1)[1]
        if game not in ('sunwin','lc79'):return
        if not game_operational(game):await tg_panel(client,q,game_state_text(game),bot_games_keyboard(chat_id));return
        await tg_panel(client,q,game_cau_overview(game),bot_game_keyboard(game,chat_id));return
    if data=='histall':
        await tg_panel(client,q,format_all_history(),bot_games_keyboard(chat_id));return
    if '|' not in data:return
    action,board=data.split('|',1)
    if board not in BOARDS:return
    if board.split(':',1)[0] not in ('sunwin','lc79'):return
    set_selected_board(chat_id,board)
    if action=='sel':
        _v50_start_auto(chat_id,board)
        txt=format_prediction(board,get_shared_prediction(board))
    elif action=='now':txt=format_prediction(board,get_shared_prediction(board))
    elif action=='auto':
        _v50_start_auto(chat_id,board);txt=format_prediction(board,get_shared_prediction(board))
    elif action=='hist':txt=format_history(board)
    elif action=='rounds':txt=format_round_history(board,15)
    elif action=='cau':txt=bot_cau_text(board,24)
    else:return
    await tg_panel(client,q,txt,bot_board_keyboard(board,chat_id))

_v52_bot_handle_message = bot_handle_message

_v52_bot_handle_callback = bot_handle_callback

_v52_bot_home_text = bot_home_text

def _v53_group_reply_payload(chat_id, text, msg=None, reply_markup=None):
    payload = _v49_send_payload(chat_id, text, reply_markup)
    mid = (msg or {}).get('message_id')
    if mid:
        payload['reply_parameters'] = {
            'message_id': int(mid),
            'allow_sending_without_reply': True,
        }
    return payload

def bot_home_text(chat_id):
    if not is_group_chat_id(chat_id):
        return _v52_bot_home_text(chat_id)
    boards = available_bot_boards()
    live = sum(1 for b in boards if _board_source(b)['icon'] == '🟢')
    selected = get_selected_board(chat_id)
    title = (get_group_settings(chat_id).get('title') or 'Telegram Group')
    lastline = 'Chưa chọn bàn'
    if selected in boards:
        p = get_shared_prediction(selected) or {}
        lastline = f"{_short_board_label(selected)} · {display_pred(selected,p.get('prediction'))} · {p.get('confidence','--')}%"
    return (f"<b>💯 {BOT_NAME}</b>\n"
            f"<i>GROUP FULL TOOL • SUNWIN + LC79</i>\n{BOT_DIV}\n"
            f"👥 <b>{html.escape(str(title))}</b>\n"
            f"☀️ <b>SUNWIN</b>    🎲 <b>LC79</b>\n"
            f"📡 API  <b>{live}/{len(boards)}</b>  •  🧠 <b>55 MODEL</b>\n"
            f"🔐 <i>MD5/SHA256 gửi trực tiếp sẽ reply đúng người gửi.</i>\n"
            f"{BOT_DIV_SOFT}\n"
            f"<i>🎯 {html.escape(lastline)}</i>")

async def bot_handle_message(client, msg):
    chat = msg.get('chat') or {}
    chat_id = chat.get('id')
    if not chat_id or not is_group_chat_id(chat_id):
        return await _v52_bot_handle_message(client, msg)

    ctype = chat.get('type') or 'group'
    text = (msg.get('text') or '').strip()
    actor = (msg.get('from') or {}).get('id')
    cmd = text.split(maxsplit=1)[0].split('@',1)[0].lower() if text.startswith('/') else ''
    hkind, hval = _hash_kind(text)

    # Group is auto-enabled when the bot can see the message.
    if not group_enabled(chat_id):
        try:
            set_group_enabled(chat_id, True, actor, chat.get('title') or 'Telegram Group')
            grant_access(chat_id, actor, True, 'group', None, 'AUTO_GROUP')
        except Exception:
            pass

    # Valid hash: reply exactly to the sender's source message.
    if hkind:
        result = hash_ultra_predict(hval)
        await tg_call(client, 'sendMessage', _v53_group_reply_payload(
            chat_id, format_hash_prediction(hval, result), msg
        ))
        asyncio.create_task(asyncio.to_thread(register_group_actor, msg, 'hash '+hkind))
        asyncio.create_task(asyncio.to_thread(record_hash_analysis, chat_id, actor, ctype, hval, result))
        return

    # Looks like a hash but invalid -> complete silence.
    if _looks_like_hash_attempt(text):
        return

    # Only tool commands are handled; ordinary group messages remain silent.
    tool_commands = {'/start','/menu','/game','/games','/dudoan','/status','/lichsu','/history'}
    if cmd not in tool_commands:
        return

    try:
        await asyncio.to_thread(register_group_actor, msg, cmd+' group')
    except Exception:
        pass

    if cmd in ('/start','/menu','/game','/games'):
        _v50_stop_auto(chat_id)
        await tg_call(client, 'sendMessage', _v53_group_reply_payload(
            chat_id, bot_home_text(chat_id), msg, bot_games_keyboard(chat_id)
        ))
        return

    board = get_selected_board(chat_id)
    if cmd in ('/dudoan','/status'):
        txt = format_prediction(board, get_shared_prediction(board)) if board else 'Chưa chọn bàn. Dùng /game.'
        kb = bot_board_keyboard(board, chat_id) if board else bot_games_keyboard(chat_id)
        await tg_call(client, 'sendMessage', _v53_group_reply_payload(chat_id, txt, msg, kb))
        return

    if cmd in ('/lichsu','/history'):
        txt = format_history(board) if board else 'Chưa chọn bàn. Dùng /game.'
        kb = bot_board_keyboard(board, chat_id) if board else bot_games_keyboard(chat_id)
        await tg_call(client, 'sendMessage', _v53_group_reply_payload(chat_id, txt, msg, kb))
        return

async def bot_handle_callback(client, q):
    msg = q.get('message') or {}
    chat_id = (msg.get('chat') or {}).get('id')
    actor = (q.get('from') or {}).get('id')
    data = q.get('data') or ''
    if not chat_id or not is_group_chat_id(chat_id):
        return await _v52_bot_handle_callback(client, q)

    if not group_enabled(chat_id):
        try:
            await tg_call(client, 'answerCallbackQuery', {
                'callback_query_id': q.get('id'), 'text': 'Bot chưa hoạt động trong nhóm.'
            })
        except Exception:
            pass
        return

    try:
        await tg_call(client, 'answerCallbackQuery', {'callback_query_id': q.get('id')})
    except Exception:
        pass

    # Home / game list stops current group auto stream.
    if data in ('home','games'):
        _v50_stop_auto(chat_id)
        await tg_panel(client, q, bot_home_text(chat_id), bot_games_keyboard(chat_id))
        return

    if data.startswith('game|'):
        _v50_stop_auto(chat_id)
        game = data.split('|',1)[1]
        if game not in ('sunwin','lc79'):
            return
        if not game_operational(game):
            await tg_panel(client, q, game_state_text(game), bot_games_keyboard(chat_id))
            return
        await tg_panel(client, q, game_cau_overview(game), bot_game_keyboard(game, chat_id))
        return

    if data == 'histall':
        await tg_panel(client, q, format_all_history(), bot_games_keyboard(chat_id))
        return

    if '|' not in data:
        return
    action, board = data.split('|',1)
    if board not in BOARDS or board.split(':',1)[0] not in ('sunwin','lc79'):
        return

    set_selected_board(chat_id, board)
    if action == 'sel':
        _v50_start_auto(chat_id, board)
        txt = format_prediction(board, get_shared_prediction(board))
    elif action == 'hist':
        txt = format_history(board)
    elif action == 'cau':
        txt = bot_cau_text(board, 24)
    elif action == 'now':
        txt = format_prediction(board, get_shared_prediction(board))
    else:
        return
    await tg_panel(client, q, txt, bot_board_keyboard(board, chat_id))

_v53_full_message_handler = bot_handle_message

_v53_full_callback_handler = bot_handle_callback

_PENDING_GAME_LINK = {}

def _v54_link_label(game):
    return '☀️ SUNWIN' if game == 'sunwin' else '🎲 LC79'

def v54_links_text():
    lines=[f"<b>🔗 LINK CHƠI TRỰC TIẾP</b>", BOT_DIV,
           "<i>Chọn game để thêm, sửa hoặc xóa link.</i>"]
    for game in ('sunwin','lc79'):
        st=game_setting(game); url=(st.get('play_url') or '').strip()
        lines += ['', f"{_v54_link_label(game)}  •  <b>{'ĐÃ CÀI' if url else 'CHƯA CÀI'}</b>"]
        if url: lines.append(f"<code>{html.escape(url[:220])}</code>")
    lines += ['', BOT_DIV_SOFT, '<i>Link đã lưu sẽ tự xuất hiện ở nút ↗ CHƠI TRỰC TIẾP của game và từng bàn.</i>']
    return '\n'.join(lines)[:4000]

def v54_links_keyboard():
    return {'inline_keyboard':[
      [{'text':'☀️ SUNWIN','callback_data':'admlink|sunwin'},
       {'text':'🎲 LC79','callback_data':'admlink|lc79'}],
      [{'text':'‹ QUẢN TRỊ','callback_data':'adminhome'},{'text':'⌂ HOME','callback_data':'home'}]
    ]}

def v54_link_detail_text(game):
    game=str(game or '').lower(); st=game_setting(game); url=(st.get('play_url') or '').strip()
    return (f"<b>🔗 {_v54_link_label(game)}</b>\n{BOT_DIV}\n"
            f"Trạng thái  <b>{'✅ ĐÃ CÀI' if url else '⚪ CHƯA CÀI'}</b>\n"
            + (f"🌐 <code>{html.escape(url[:300])}</code>\n" if url else "")
            + f"{BOT_DIV_SOFT}\n<i>Bấm THÊM/SỬA rồi gửi nguyên link http:// hoặc https:// cho bot.</i>")

def v54_link_detail_keyboard(game):
    game=str(game or '').lower(); url=(game_setting(game).get('play_url') or '').strip()
    rows=[[{'text':'✏️ THÊM / SỬA LINK','callback_data':f'admlinkedit|{game}'}]]
    if url:
        rows.append([{'text':'🌐 MỞ LINK HIỆN TẠI','url':url}])
        rows.append([{'text':'🗑 XÓA LINK','callback_data':f'admlinkdel|{game}'}])
    rows.append([{'text':'‹ DANH SÁCH LINK','callback_data':'adm|links'},{'text':'⌂ QUẢN TRỊ','callback_data':'adminhome'}])
    return {'inline_keyboard':rows}

def bot_admin_keyboard():
    return {'inline_keyboard':[
      [{'text':'👥 NGƯỜI DÙNG','callback_data':'adm|users'},{'text':'📊 THỐNG KÊ','callback_data':'adm|stats'}],
      [{'text':'🔐 CẤP / THU QUYỀN','callback_data':'adm|access'},{'text':'📡 API','callback_data':'adm|health'}],
      [{'text':'🔗 LINK CHƠI','callback_data':'adm|links'}],
      [{'text':'⌂ TRANG CHỦ','callback_data':'home'}]
    ]}

def bot_admin_home_text():
    return (f"<b>◆ {BOT_NAME} · ADMIN</b>\n"
            f"<i>ACCESS • USERS • API • DIRECT LINK</i>\n{BOT_DIV}\n"
            f"👥 Quản lý user và quyền sử dụng\n"
            f"📊 Thống kê hoạt động realtime\n"
            f"📡 Theo dõi API SUNWIN / LC79\n"
            f"🔗 Thêm / sửa link CHƠI TRỰC TIẾP\n"
            f"{BOT_DIV_SOFT}\n"
            f"<i>Không key • không ví • không nạp tiền • không quản lý nhóm.</i>")

async def bot_handle_message(client, msg):
    chat=msg.get('chat') or {}; chat_id=chat.get('id'); actor=(msg.get('from') or {}).get('id')
    text=(msg.get('text') or '').strip(); cmd=text.split(maxsplit=1)[0].split('@',1)[0].lower() if text.startswith('/') else ''

    # Interactive URL input is intentionally admin-private only.
    if chat_id and not is_group_chat_id(chat_id) and actor and is_admin(actor):
        pending=_PENDING_GAME_LINK.get(int(actor))
        if pending:
            if cmd in ('/cancel','/huy'):
                _PENDING_GAME_LINK.pop(int(actor),None)
                await tg_call(client,'sendMessage',_v49_send_payload(chat_id,'✖ Đã hủy thêm link.',v54_link_detail_keyboard(pending)))
                return
            if text.startswith(('http://','https://')) and ' ' not in text:
                try:
                    set_game_link(pending,text,actor)
                    _PENDING_GAME_LINK.pop(int(actor),None)
                    await tg_call(client,'sendMessage',_v49_send_payload(
                        chat_id,f"✅ ĐÃ LƯU LINK {_v54_link_label(pending)}\n<code>{html.escape(text[:300])}</code>",
                        v54_link_detail_keyboard(pending)))
                except Exception as e:
                    await tg_call(client,'sendMessage',{'chat_id':chat_id,'text':'❌ Link không hợp lệ: '+str(e)[:180]})
                return
            # Ignore commands that should still work; ordinary text gets a concise reminder.
            if not text.startswith('/'):
                await tg_call(client,'sendMessage',{'chat_id':chat_id,'text':'Gửi nguyên link bắt đầu bằng https:// hoặc bấm /huy để hủy.'})
                return

        if cmd=='/xoalinkgame':
            parts=text.split(maxsplit=1)
            if len(parts)<2 or parts[1].lower() not in ('sunwin','lc79'):
                out='Cú pháp: /xoalinkgame sunwin|lc79'
            else:
                game=parts[1].lower(); set_game_link(game,'',actor); out='🗑 Đã xóa link '+game.upper()
            await tg_call(client,'sendMessage',_v49_send_payload(chat_id,out,v54_links_keyboard()))
            return

    return await _v53_full_message_handler(client,msg)

async def bot_handle_callback(client, q):
    msg=q.get('message') or {}; chat_id=(msg.get('chat') or {}).get('id'); actor=(q.get('from') or {}).get('id'); data=q.get('data') or ''
    if chat_id and not is_group_chat_id(chat_id) and actor and is_admin(actor):
        if data=='adm|links':
            try: await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id')})
            except Exception: pass
            await tg_panel(client,q,v54_links_text(),v54_links_keyboard()); return
        if data.startswith('admlink|'):
            game=data.split('|',1)[1]
            if game not in ('sunwin','lc79'): return
            try: await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id')})
            except Exception: pass
            await tg_panel(client,q,v54_link_detail_text(game),v54_link_detail_keyboard(game)); return
        if data.startswith('admlinkedit|'):
            game=data.split('|',1)[1]
            if game not in ('sunwin','lc79'): return
            _PENDING_GAME_LINK[int(actor)]=game
            try: await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id'),'text':'Gửi link ở tin nhắn tiếp theo'})
            except Exception: pass
            await tg_panel(client,q,
                f"<b>✏️ THÊM / SỬA LINK {_v54_link_label(game)}</b>\n{BOT_DIV}\n"
                "Gửi <b>nguyên URL</b> ở tin nhắn tiếp theo.\n"
                "Ví dụ: <code>https://example.com/game</code>\n\n"
                "<i>Dùng /huy để hủy.</i>",
                {'inline_keyboard':[[{'text':'✖ HỦY','callback_data':f'admlinkcancel|{game}'}]]})
            return
        if data.startswith('admlinkdel|'):
            game=data.split('|',1)[1]
            if game not in ('sunwin','lc79'): return
            set_game_link(game,'',actor)
            _PENDING_GAME_LINK.pop(int(actor),None)
            try: await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id'),'text':'Đã xóa link'})
            except Exception: pass
            await tg_panel(client,q,v54_link_detail_text(game),v54_link_detail_keyboard(game)); return
        if data.startswith('admlinkcancel|'):
            game=data.split('|',1)[1]
            _PENDING_GAME_LINK.pop(int(actor),None)
            try: await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id'),'text':'Đã hủy'})
            except Exception: pass
            await tg_panel(client,q,v54_link_detail_text(game),v54_link_detail_keyboard(game)); return
    return await _v53_full_callback_handler(client,q)

_v54_pure_strategy_predictions = _pure_strategy_predictions

_v54_strategy_predictors = _strategy_predictors

_v54_hash_ultra_predict = hash_ultra_predict

V55_STRATEGIES = (
    'EWMA_MARKOV_BLEND','LOCAL_GLOBAL_BAYES','MOTIF_KNN_BLEND',
    'RUN_REGIME_GUARD','DRIFT_CONSENSUS','CALIBRATED_STACK'
)

STRATEGY_NAMES = tuple(dict.fromkeys(tuple(STRATEGY_NAMES) + V55_STRATEGIES))

def _v55_majority(items, fallback='TÀI'):
    vals=[x for x in items if x in ('TÀI','XỈU')]
    if not vals:return fallback
    t=vals.count('TÀI'); x=len(vals)-t
    return fallback if t==x else ('TÀI' if t>x else 'XỈU')

def _v55_ewma_markov(seq):
    return _v55_majority([
        _decayed_transition_prediction(seq,1),
        _decayed_transition_prediction(seq,2),
        _markov_prediction(seq,2),
        _markov_prediction(seq,3),
    ], _markov_prediction(seq,1))

def _v55_local_global_bayes(seq):
    return _v55_majority([
        _bayes_context_prediction(seq),
        _long_memory_bayes_prediction(seq),
        _cross_horizon_bayes_prediction(seq),
        _hierarchical_bayes_prediction(seq),
    ], _bayes_context_prediction(seq))

def _v55_motif_knn(seq):
    return _v55_majority([
        _motif_weighted_prediction(seq),
        _motif_survival_prediction(seq),
        _knn_recency_prediction(seq),
        _suffix_prediction(seq),
    ], _motif_weighted_prediction(seq))

def _v55_run_regime(seq):
    return _v55_majority([
        _run_hazard_prediction(seq),
        _run_length_markov_prediction(seq),
        _run_survival_prediction(seq),
        _regime_posterior_prediction(seq),
        _run_context_joint_prediction(seq),
    ], _run_hazard_prediction(seq))

def _v55_drift_consensus(seq):
    return _v55_majority([
        _changepoint_adaptive_prediction(seq),
        _sequential_change_prediction(seq),
        _transition_drift_prediction(seq),
        _multiresolution_edge_prediction(seq),
    ], _sequential_change_prediction(seq))

def _v55_calibrated_stack(seq):
    return _v55_majority([
        _robust_stack_prediction(seq),
        _ctw_approx_prediction(seq),
        _hierarchical_bayes_prediction(seq),
        _entropy_gate_prediction(seq),
        _horizon_consensus_prediction(seq),
    ], _robust_stack_prediction(seq))

def _pure_strategy_predictions(seq, board=None):
    out=_v54_pure_strategy_predictions(seq,board)
    if not seq:return out
    out.update({
        'EWMA_MARKOV_BLEND':_v55_ewma_markov(seq),
        'LOCAL_GLOBAL_BAYES':_v55_local_global_bayes(seq),
        'MOTIF_KNN_BLEND':_v55_motif_knn(seq),
        'RUN_REGIME_GUARD':_v55_run_regime(seq),
        'DRIFT_CONSENSUS':_v55_drift_consensus(seq),
        'CALIBRATED_STACK':_v55_calibrated_stack(seq),
    })
    return out

def _strategy_predictors(board,rows,fusion):
    out=_v54_strategy_predictors(board,rows,fusion)
    seq=_seq(rows)
    if not seq:return out
    def put(name,pred,conf,reason):
        out[name]={'name':name,'prediction':pred,'local_confidence':int(_clamp(conf,45,72)),'reason':reason}
    put('EWMA_MARKOV_BLEND',_v55_ewma_markov(seq),57,'Decayed Markov bậc 1–3 + EWMA consensus')
    put('LOCAL_GLOBAL_BAYES',_v55_local_global_bayes(seq),58,'Bayes local/global + hierarchical evidence')
    put('MOTIF_KNN_BLEND',_v55_motif_knn(seq),57,'Motif + KNN recency + suffix consensus')
    put('RUN_REGIME_GUARD',_v55_run_regime(seq),58,'Run survival/hazard + regime posterior guard')
    put('DRIFT_CONSENSUS',_v55_drift_consensus(seq),58,'Change-point + transition drift + multiresolution')
    put('CALIBRATED_STACK',_v55_calibrated_stack(seq),59,'Robust/CTW/Bayes stack có entropy guard')
    return out

_hash_v55_cache={}

_hash_v55_order=[]

def hash_ultra_predict(hash_hex):
    z=(hash_hex or '').lower()
    hit=_hash_v55_cache.get(z)
    if hit is not None:return dict(hit)
    base=_v54_hash_ultra_predict(z)
    L=len(z); nib=[int(c,16) for c in z]; bs=bytes.fromhex(z)
    signals=[]
    def sig(p,w=1.0):signals.append((_clip(p,0.25,0.75),float(w)))
    # 25. Prime-position hex balance.
    prime_idx=[i for i in range(L) if i in (2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61)]
    pm=sum(nib[i] for i in prime_idx)/max(1,len(prime_idx)); sig(0.5+(pm-7.5)/15*0.20,0.75)
    # 26. Alternating nibble lanes.
    a=sum(nib[::2])/max(1,len(nib[::2])); b=sum(nib[1::2])/max(1,len(nib[1::2]));sig(0.5+math.tanh((a-b)/3.5)*0.10,0.72)
    # 27. Byte quartile balance.
    q=max(1,len(bs)//4); qm=[]
    for i in range(4):
        part=bs[i*q:(i+1)*q] if i<3 else bs[i*q:]
        if part:qm.append(sum(part)/len(part))
    sig(0.5+((sum(qm)/max(1,len(qm))-127.5)/255)*0.22,0.78)
    # 28. Rotate-XOR fold.
    rv=0
    for i,bv in enumerate(bs):rv ^= ((bv << (i%5)) | (bv >> (8-(i%5) or 8))) & 255
    sig(0.5+(rv-127.5)/255*0.18,0.68)
    # 29. Edge hamming density.
    half=max(1,len(bs)//2); hd=sum((bs[i]^bs[-1-i]).bit_count() for i in range(half))/(8*half)
    sig(0.5+(hd-.5)*0.28,0.74)
    # 30. SHA-512 derived deep balance; deterministic and cheap.
    deep=hashlib.sha512(z.encode()).digest(); dm=sum(deep)/len(deep)
    sig(0.5+(dm-127.5)/255*0.20,0.88)
    base_p=float(base.get('tai_pct',50))/100.0
    extra_w=sum(w for _,w in signals);extra_p=sum(p*w for p,w in signals)/max(.001,extra_w)
    # Keep the proven 24-signal block dominant; extras are a calibrated refinement.
    p=.78*base_p+.22*extra_p
    direction='TÀI' if p>=.5 else 'XỈU'
    extra_agree=sum(w for pp,w in signals if (pp>=.5)==(p>=.5))/max(.001,extra_w)
    old_agree=float(base.get('agreement',50))/100.0
    agree=.80*old_agree+.20*extra_agree
    strength=50+min(20,abs(p-.5)*105)+max(0,agree-.5)*18
    ent=float(base.get('entropy',0))
    if agree<.55:strength=min(strength,56)
    if ent<3.1:strength=min(strength,57)
    strength=_clip(strength,51,71)
    tai=round(strength if direction=='TÀI' else 100-strength,2);xiu=round(100-tai,2)
    level='MẠNH' if max(tai,xiu)>=66 else 'KHÁ' if max(tai,xiu)>=59 else 'NHẸ'
    result=dict(base,prediction=direction,tai_pct=tai,xiu_pct=xiu,agreement=round(agree*100,1),level=level,models=30)
    _hash_v55_cache[z]=dict(result);_hash_v55_order.append(z)
    if len(_hash_v55_order)>4096:
        old=_hash_v55_order.pop(0);_hash_v55_cache.pop(old,None)
    return result

_v55_anchor={}

_v55_heartbeat={}

_v55_history_ts={}

_v55_history_tasks={}

def _v55_parse_rows(cfg,data):
    kind=cfg.get('kind')
    if kind=='sicbo_pair' or kind=='sicbo':return parse_sicbo(data)
    if kind=='xocdia':return parse_xocdia(data)
    return parse_tx(data)

async def _v55_backfill_history(client,board,cfg):
    try:
        url=cfg.get('history')
        if not url:return
        raw=await fetch_json(client,url)
        rows=_v55_parse_rows(cfg,raw)
        if rows:await store_rows(board,rows)
    except Exception:
        pass
    finally:
        _v55_history_ts[board]=time.time();_v55_history_tasks.pop(board,None)

def _v55_refresh_sync(board,current_session):
    rows=load_rows(board,MAX_HISTORY)
    settled=_settle_predictions(board,rows)
    pred,created=_create_shared_prediction(board,rows,current_session)
    return settled,pred,created

async def refresh_shared_prediction(board,current_session=None):
    settled,pred,created=await asyncio.to_thread(_v55_refresh_sync,board,current_session)
    if settled and BOT_TOKEN:
        for item in settled:asyncio.create_task(bot_clear_settled_prediction(board,item['session']))
    if created and BOT_TOKEN:asyncio.create_task(bot_notify_prediction(board,pred))
    return pred

async def poll_board(client,board,cfg):
    cfg=effective_cfg(board,cfg)
    try:
        data,_=await fetch_first(client,[cfg.get('current')]+cfg.get('current_fallbacks',[]))
        rows=_v55_parse_rows(cfg,data)
        anchor=_current_anchor(rows)
        if not rows or anchor is None:raise RuntimeError('current API không có phiên hợp lệ')
        anchor=str(anchor)
        now=time.time();changed=(_v55_anchor.get(board)!=anchor)
        if changed:
            _v55_anchor[board]=anchor
            await store_rows(board,rows)
            # Heavy prediction work is offloaded from the event loop.
            await refresh_shared_prediction(board,anchor)
            await set_state(board,True)
            # Backfill large history independently; it never blocks the live result.
            if cfg.get('history') and now-_v55_history_ts.get(board,0)>20 and board not in _v55_history_tasks:
                t=asyncio.create_task(_v55_backfill_history(client,board,cfg));_v55_history_tasks[board]=t
        elif now-_v55_heartbeat.get(board,0)>4.0:
            _v55_heartbeat[board]=now
            await set_state(board,True)
    except Exception as e:
        await set_state(board,False,str(e)[:240])

async def worker_loop():
    global _last_cycle
    limits=httpx.Limits(max_connections=24,max_keepalive_connections=16,keepalive_expiry=20.0)
    timeout=httpx.Timeout(2.5,connect=1.5,pool=1.0)
    async with httpx.AsyncClient(follow_redirects=True,limits=limits,timeout=timeout) as client:
        while True:
            started=time.perf_counter()
            targets=[(b,c) for b,c in BOARDS.items() if game_operational(c.get('game'))]
            await asyncio.gather(*(poll_board(client,b,c) for b,c in targets),return_exceptions=True)
            _last_cycle=time.time()
            elapsed=time.perf_counter()-started
            await asyncio.sleep(max(.05,POLL_SECONDS-elapsed))

def ensure_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    now=time.time()
    with sqlite3.connect(DB_PATH, timeout=4) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA busy_timeout=3000')
        db.execute("""CREATE TABLE IF NOT EXISTS rounds(
            board TEXT NOT NULL, session TEXT NOT NULL, result TEXT NOT NULL,
            d1 INTEGER,d2 INTEGER,d3 INTEGER,total INTEGER,md5 TEXT,seen_at REAL NOT NULL,meta_json TEXT,
            PRIMARY KEY(board,session))""")
        db.execute("""CREATE TABLE IF NOT EXISTS board_state(
            board TEXT PRIMARY KEY,updated_at REAL NOT NULL,source_ok INTEGER NOT NULL,last_error TEXT,model_json TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS shared_predictions(
            board TEXT NOT NULL,session TEXT NOT NULL,prediction TEXT NOT NULL,confidence INTEGER NOT NULL,score REAL NOT NULL,
            model_json TEXT,created_at REAL NOT NULL,actual TEXT,ok INTEGER,settled_at REAL,PRIMARY KEY(board,session))""")
        db.execute("""CREATE TABLE IF NOT EXISTS strategy_logs(
            board TEXT NOT NULL,session TEXT NOT NULL,strategy TEXT NOT NULL,prediction TEXT NOT NULL,actual TEXT,ok INTEGER,
            created_at REAL NOT NULL,settled_at REAL,PRIMARY KEY(board,session,strategy))""")
        db.execute("""CREATE TABLE IF NOT EXISTS champion_state(
            board TEXT PRIMARY KEY,champion TEXT,updated_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS board_cursor(
            board TEXT PRIMARY KEY,last_completed_session TEXT,updated_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_subscriptions(
            chat_id INTEGER NOT NULL,board TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(chat_id,board))""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_chat_state(
            chat_id INTEGER PRIMARY KEY,selected_board TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_auto_messages(
            chat_id INTEGER NOT NULL,board TEXT NOT NULL,session TEXT NOT NULL,message_id INTEGER NOT NULL,created_at REAL NOT NULL,
            PRIMARY KEY(chat_id,board))""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_access(
            chat_id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1,granted_by INTEGER,updated_at REAL NOT NULL,
            expires_at REAL,access_label TEXT DEFAULT 'manual',purchased_at REAL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS api_overrides(
            board TEXT PRIMARY KEY,current_url TEXT,history_url TEXT,updated_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_group_settings(
            chat_id INTEGER PRIMARY KEY,title TEXT,enabled INTEGER NOT NULL DEFAULT 0,
            auto_delete INTEGER NOT NULL DEFAULT 0,delete_after REAL NOT NULL DEFAULT 5,anti_spam INTEGER NOT NULL DEFAULT 0,
            spam_limit INTEGER NOT NULL DEFAULT 5,spam_window REAL NOT NULL DEFAULT 6,mute_seconds INTEGER NOT NULL DEFAULT 60,
            locked INTEGER NOT NULL DEFAULT 0,warn_limit INTEGER NOT NULL DEFAULT 3,enabled_by INTEGER,updated_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_users(
            chat_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,last_name TEXT,balance INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,updated_at REAL NOT NULL,last_seen REAL,last_action TEXT NOT NULL DEFAULT '',
            action_count INTEGER NOT NULL DEFAULT 0,start_count INTEGER NOT NULL DEFAULT 0,callback_count INTEGER NOT NULL DEFAULT 0,
            last_chat_type TEXT NOT NULL DEFAULT 'private')""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_user_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,event_type TEXT NOT NULL,action TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_game_settings(
            game TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL DEFAULT 'online',reason TEXT NOT NULL DEFAULT '',
            play_url TEXT NOT NULL DEFAULT '',updated_by INTEGER,updated_at REAL NOT NULL)""")
        for game in ('sunwin','lc79'):
            db.execute("""INSERT OR IGNORE INTO bot_game_settings(game,enabled,status,reason,play_url,updated_by,updated_at)
                          VALUES(?,1,'online','','',NULL,?)""",(game,now))
        # Forward-compatible migrations for users upgrading an older DB.
        rcols={r[1] for r in db.execute('PRAGMA table_info(rounds)')}
        if 'meta_json' not in rcols: db.execute('ALTER TABLE rounds ADD COLUMN meta_json TEXT')
        acols={r[1] for r in db.execute('PRAGMA table_info(bot_access)')}
        if 'expires_at' not in acols: db.execute('ALTER TABLE bot_access ADD COLUMN expires_at REAL')
        if 'access_label' not in acols: db.execute("ALTER TABLE bot_access ADD COLUMN access_label TEXT DEFAULT 'manual'")
        if 'purchased_at' not in acols: db.execute('ALTER TABLE bot_access ADD COLUMN purchased_at REAL')
        ucols={r[1] for r in db.execute('PRAGMA table_info(bot_users)')}
        for col,ddl in {
            'last_seen':'REAL','last_action':"TEXT NOT NULL DEFAULT ''",'action_count':'INTEGER NOT NULL DEFAULT 0',
            'start_count':'INTEGER NOT NULL DEFAULT 0','callback_count':'INTEGER NOT NULL DEFAULT 0',
            'last_chat_type':"TEXT NOT NULL DEFAULT 'private'"}.items():
            if col not in ucols: db.execute(f'ALTER TABLE bot_users ADD COLUMN {col} {ddl}')
        db.execute('CREATE INDEX IF NOT EXISTS idx_rounds_board_seen ON rounds(board,seen_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_pred_board_created ON shared_predictions(board,created_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_bot_users_seen ON bot_users(last_seen DESC)')
        db.commit()

_v55_board_source = _board_source

_v55_game_setting = game_setting

_v55_get_shared_prediction = get_shared_prediction

_v55_get_selected_board = get_selected_board

_v55_set_selected_board = set_selected_board

_v55_set_game_link = set_game_link

_v55_set_state = set_state

_v56_board_source_cache = {}

_v56_game_setting_cache = {}

_v56_pred_cache = {}

_v56_selected_cache = {}

def _v56_ttl_get(cache,key,ttl):
    item=cache.get(key)
    if not item:return None
    ts,val=item
    if time.monotonic()-ts>ttl:
        cache.pop(key,None);return None
    return val

def _board_source(board):
    hit=_v56_ttl_get(_v56_board_source_cache,board,0.45)
    if hit is not None:return dict(hit)
    val=_v55_board_source(board);_v56_board_source_cache[board]=(time.monotonic(),dict(val));return val

def game_setting(game):
    key=str(game or '').lower().strip()
    hit=_v56_ttl_get(_v56_game_setting_cache,key,0.80)
    if hit is not None:return dict(hit)
    val=_v55_game_setting(key);_v56_game_setting_cache[key]=(time.monotonic(),dict(val));return val

def get_shared_prediction(board):
    hit=_v56_ttl_get(_v56_pred_cache,board,0.25)
    if hit is not None:return dict(hit) if hit else None
    val=_v55_get_shared_prediction(board);_v56_pred_cache[board]=(time.monotonic(),dict(val) if val else None);return val

def get_selected_board(chat_id):
    hit=_v56_ttl_get(_v56_selected_cache,int(chat_id),2.0)
    if hit is not None:return hit or None
    val=_v55_get_selected_board(chat_id);_v56_selected_cache[int(chat_id)]=(time.monotonic(),val or '');return val

def set_selected_board(chat_id,board):
    _v55_set_selected_board(chat_id,board);_v56_selected_cache[int(chat_id)]=(time.monotonic(),board or '')

def set_game_link(game,url,admin_id=None):
    val=_v55_set_game_link(game,url,admin_id);_v56_game_setting_cache.pop(str(game or '').lower().strip(),None);return val

async def set_state(board,ok,error=None):
    val=await _v55_set_state(board,ok,error);_v56_board_source_cache.pop(board,None);return val

_v55_pure_strategy_predictions_v56 = _pure_strategy_predictions

_v55_strategy_predictors_v56 = _strategy_predictors

_v55_hash_ultra_predict_v56 = hash_ultra_predict

V56_STRATEGIES=(
    'CONTEXT_DRIFT_BLEND','MOTIF_LAG_POSTERIOR','RUN_BAYES_SWITCH',
    'ANALOG_MULTISCALE','SUFFIX_HORIZON_STACK','STABILITY_GUARD_STACK'
)

STRATEGY_NAMES=tuple(dict.fromkeys(tuple(STRATEGY_NAMES)+V56_STRATEGIES))

def _v56_vote(seq, funcs, fallback='TÀI'):
    vals=[]
    for fn in funcs:
        try:
            p=fn(seq)
            if p in ('TÀI','XỈU'):vals.append(p)
        except Exception:pass
    if not vals:return fallback
    t=vals.count('TÀI');x=len(vals)-t
    return fallback if t==x else ('TÀI' if t>x else 'XỈU')

def _v56_context_drift(seq):
    fb=_decayed_transition_prediction(seq,1)
    return _v56_vote(seq,[lambda s:_decayed_transition_prediction(s,2),_transition_drift_prediction,_ctw_approx_prediction,_hierarchical_bayes_prediction],fb)

def _v56_motif_lag(seq):
    fb=_motif_weighted_prediction(seq)
    return _v56_vote(seq,[_motif_weighted_prediction,_motif_survival_prediction,_lag_ensemble_prediction,_spectral_lag_prediction,_regime_posterior_prediction],fb)

def _v56_run_bayes(seq):
    fb=_run_hazard_prediction(seq)
    return _v56_vote(seq,[_bayes_run_mixture_prediction,_run_context_joint_prediction,_run_survival_prediction,_run_length_markov_prediction,_entropy_gate_prediction],fb)

def _v56_analog_multiscale(seq):
    fb=_knn_recency_prediction(seq)
    return _v56_vote(seq,[_analog_knn_prediction,_knn_recency_prediction,_multiscale_transition_prediction,_multiresolution_edge_prediction,_multi_window_prediction],fb)

def _v56_suffix_horizon(seq):
    fb=_suffix_prediction(seq)
    return _v56_vote(seq,[_suffix_prediction,_horizon_consensus_prediction,_dual_horizon_prediction,_cross_horizon_bayes_prediction,_long_memory_bayes_prediction],fb)

def _v56_stability_guard(seq):
    fb=_robust_stack_prediction(seq)
    return _v56_vote(seq,[_robust_stack_prediction,_sequential_change_prediction,_changepoint_adaptive_prediction,_wilson_context_prediction,_context_entropy_prediction],fb)

def _pure_strategy_predictions(seq,board=None):
    out=_v55_pure_strategy_predictions_v56(seq,board)
    if not seq:return out
    out.update({
      'CONTEXT_DRIFT_BLEND':_v56_context_drift(seq),
      'MOTIF_LAG_POSTERIOR':_v56_motif_lag(seq),
      'RUN_BAYES_SWITCH':_v56_run_bayes(seq),
      'ANALOG_MULTISCALE':_v56_analog_multiscale(seq),
      'SUFFIX_HORIZON_STACK':_v56_suffix_horizon(seq),
      'STABILITY_GUARD_STACK':_v56_stability_guard(seq),
    })
    return out

def _strategy_predictors(board,rows,fusion):
    out=_v55_strategy_predictors_v56(board,rows,fusion);seq=_seq(rows)
    if not seq:return out
    def put(name,pred,conf,reason):
        out[name]={'name':name,'prediction':pred,'local_confidence':int(_clamp(conf,45,70)),'reason':reason}
    put('CONTEXT_DRIFT_BLEND',_v56_context_drift(seq),58,'Context + drift + CTW/hierarchical consensus')
    put('MOTIF_LAG_POSTERIOR',_v56_motif_lag(seq),58,'Motif + spectral/lag + regime posterior')
    put('RUN_BAYES_SWITCH',_v56_run_bayes(seq),58,'Run survival + Bayes run + entropy guard')
    put('ANALOG_MULTISCALE',_v56_analog_multiscale(seq),57,'Analog/KNN + multiscale transition')
    put('SUFFIX_HORIZON_STACK',_v56_suffix_horizon(seq),58,'Suffix context + multi-horizon Bayes')
    put('STABILITY_GUARD_STACK',_v56_stability_guard(seq),59,'Robust stack + change-point stability guard')
    return out

_hash_v56_cache={}

_hash_v56_order=[]

def hash_ultra_predict(hash_hex):
    z=(hash_hex or '').lower();hit=_hash_v56_cache.get(z)
    if hit is not None:return dict(hit)
    base=_v55_hash_ultra_predict_v56(z);L=len(z)
    if L not in (32,64) or not re.fullmatch(r'[0-9a-f]+',z):return base
    nib=[int(c,16) for c in z];bs=bytes.fromhex(z);signals=[]
    def sig(p,w=1.0):signals.append((_clip(float(p),0.25,0.75),float(w)))
    # 31: SHA3 derived byte balance.
    d=hashlib.sha3_256(z.encode()).digest();sig(0.5+((sum(d)/len(d))-127.5)/255*0.20,0.90)
    # 32: BLAKE2b derived balance.
    d2=hashlib.blake2b(z.encode(),digest_size=32).digest();sig(0.5+((sum(d2)/len(d2))-127.5)/255*0.20,0.90)
    # 33: Chunk variance around hex midpoint.
    step=max(4,L//8);means=[]
    for i in range(0,L,step):
        part=nib[i:i+step]
        if part:means.append(sum(part)/len(part))
    var=sum((x-7.5)**2 for x in means)/max(1,len(means));sig(0.5+math.tanh((var-5.0)/7.0)*0.08,0.66)
    # 34: Adjacent byte autocorrelation direction.
    if len(bs)>2:
        av=sum(bs)/len(bs);num=sum((bs[i]-av)*(bs[i-1]-av) for i in range(1,len(bs)));den=sum((b-av)**2 for b in bs) or 1
        sig(0.5+_clip(num/den,-1,1)*0.09,0.72)
    else:sig(0.5,0.5)
    # 35: High/low nibble transition balance.
    trans=0
    for a,b in zip(nib,nib[1:]):trans += 1 if (a<8 and b>=8) else -1 if (a>=8 and b<8) else 0
    sig(0.5+math.tanh(trans/max(2,L/6))*0.10,0.70)
    # 36: Three-way edge/middle fold.
    q=max(2,L//4);edge=sum(nib[:q])+sum(nib[-q:]);mid=sum(nib[q:-q]) if L>2*q else 0
    denom=max(1,2*q+(L-2*q));delta=(edge-mid)/denom
    sig(0.5+math.tanh(delta/3.5)*0.09,0.68)
    base_p=float(base.get('tai_pct',50))/100.0;sw=sum(w for _,w in signals);ep=sum(p*w for p,w in signals)/max(.001,sw)
    p=.84*base_p+.16*ep;direction='TÀI' if p>=.5 else 'XỈU';extra_agree=sum(w for pp,w in signals if (pp>=.5)==(p>=.5))/max(.001,sw)
    agree=.86*(float(base.get('agreement',50))/100.0)+.14*extra_agree
    strength=50+min(19,abs(p-.5)*102)+max(0,agree-.5)*17
    ent=float(base.get('entropy',0))
    if agree<.55:strength=min(strength,56)
    if ent<3.1:strength=min(strength,57)
    strength=_clip(strength,51,70)
    tai=round(strength if direction=='TÀI' else 100-strength,2);xiu=round(100-tai,2)
    level='MẠNH' if max(tai,xiu)>=66 else 'KHÁ' if max(tai,xiu)>=59 else 'NHẸ'
    result=dict(base,prediction=direction,tai_pct=tai,xiu_pct=xiu,agreement=round(agree*100,1),level=level,models=36)
    _hash_v56_cache[z]=dict(result);_hash_v56_order.append(z)
    if len(_hash_v56_order)>4096:
        old=_hash_v56_order.pop(0);_hash_v56_cache.pop(old,None)
    return result


# ============================================================
# V57 · HASH CALIBRATED — giảm false-confidence cho MD5/SHA256
# Hash một chiều tự thân không chứa bảo đảm dự đoán kết quả. Khối này:
# 1) shrink tín hiệu cấu trúc về 50%; 2) với MD5, chỉ dùng lịch sử LC79
#    khi mô hình lịch sử qua holdout; 3) cap confidence nếu edge chưa ổn định.
# ============================================================
_v56_hash_ultra_predict_v57 = hash_ultra_predict
_hash_v57_cache = {}
_hash_v57_order = []
_hash_v57_hist_state = {'ts':0.0,'payload':None}


def _v57_hash_feature_keys(z):
    """Feature rời rạc, support cao, tránh học thuộc full hash."""
    nib=[int(c,16) for c in z]
    bs=bytes.fromhex(z)
    s=sum(nib)
    xv=0
    for b in bs:xv ^= b
    bit=sum(b.bit_count() for b in bs)
    L=len(z)
    return {
        'p0':nib[0], 'p7':nib[min(7,L-1)], 'p15':nib[min(15,L-1)], 'plast':nib[-1],
        'prefix2':int(z[:2],16)//16,
        'suffix2':int(z[-2:],16)//16,
        'sum16':s%16,
        'xor16':xv%16,
        'bit8':min(7,int((bit/(8*len(bs)))*8)),
        'mean8':min(7,int((sum(nib)/L)/16*8)),
    }


def _v57_train_hist(rows):
    tables={k:{} for k in ('p0','p7','p15','plast','prefix2','suffix2','sum16','xor16','bit8','mean8')}
    tai=sum(1 for z,y in rows if y=='TÀI'); n=len(rows)
    prior=(tai+8)/(n+16) if n else .5
    for z,y in rows:
        f=_v57_hash_feature_keys(z)
        for name,val in f.items():
            t,x=tables[name].get(val,(0,0))
            if y=='TÀI':t+=1
            else:x+=1
            tables[name][val]=(t,x)
    return {'prior':prior,'tables':tables,'n':n}


def _v57_hist_prob(model,z):
    if not model:return .5,0
    f=_v57_hash_feature_keys(z); vals=[]; support=0
    prior=float(model.get('prior',.5)); tables=model.get('tables') or {}
    for name,val in f.items():
        t,x=(tables.get(name) or {}).get(val,(0,0)); n=t+x
        if n<6:continue
        # Beta shrinkage lớn để không biến nhiễu thành edge giả.
        p=(t+10*prior)/(n+10)
        reliability=min(1.0,n/45.0)
        vals.append((p,reliability));support+=n
    if not vals:return prior,0
    sw=sum(w for _,w in vals) or 1
    p=sum(v*w for v,w in vals)/sw
    # Kéo mạnh về prior; chỉ giữ edge lặp lại ở nhiều feature.
    p=prior + (p-prior)*0.55
    return _clip(p,.42,.58),support


def _v57_hash_history_model():
    now=time.monotonic(); st=_hash_v57_hist_state
    if st.get('payload') is not None and now-float(st.get('ts',0))<90:
        return st['payload']
    payload={'ready':False,'valid':False,'sample':0,'accuracy':.5,'brier':.25,'model':None}
    try:
        with sqlite3.connect(DB_PATH,timeout=1.5) as db:
            raw=db.execute("""SELECT md5,result FROM rounds
                              WHERE board='lc79:md5' AND md5 IS NOT NULL
                                AND result IN ('TÀI','XỈU')
                              ORDER BY seen_at DESC LIMIT 2400""").fetchall()
        rows=[]
        seen=set()
        for z,y in reversed(raw):
            z=str(z or '').strip().lower()
            if z in seen or not re.fullmatch(r'[0-9a-f]{32}',z):continue
            seen.add(z);rows.append((z,y))
        payload['sample']=len(rows)
        if len(rows)>=180:
            cut=max(120,int(len(rows)*.78)); train=rows[:cut]; test=rows[cut:]
            if len(test)>=40:
                m=_v57_train_hist(train); correct=0;brier=0.0
                for z,y in test:
                    p,_=_v57_hist_prob(m,z); pred='TÀI' if p>=.5 else 'XỈU'
                    correct += pred==y
                    yy=1.0 if y=='TÀI' else 0.0;brier+=(p-yy)**2
                acc=correct/len(test); brier/=len(test)
                full=_v57_train_hist(rows)
                # Gate chặt: nếu holdout không có edge thật thì không cho model lịch sử tham gia.
                valid=(acc>=.535 and brier<=.2495)
                payload.update({'ready':True,'valid':valid,'accuracy':acc,'brier':brier,'model':full})
    except Exception:
        pass
    st['ts']=now;st['payload']=payload
    return payload


def hash_ultra_predict(hash_hex):
    z=(hash_hex or '').strip().lower()
    hit=_hash_v57_cache.get(z)
    if hit is not None:return dict(hit)
    base=_v56_hash_ultra_predict_v57(z)
    if len(z) not in (32,64) or not re.fullmatch(r'[0-9a-f]+',z):return base

    base_p=float(base.get('tai_pct',50))/100.0
    base_agree=float(base.get('agreement',50))/100.0
    # Structural hash heuristics are intentionally weak: shrink 76% toward neutral.
    p=.5+(base_p-.5)*.24
    hist=None;hist_used=False;hist_p=.5
    if len(z)==32:
        hist=_v57_hash_history_model()
        if hist.get('valid') and hist.get('model'):
            hist_p,support=_v57_hist_prob(hist['model'],z)
            # Holdout-validated history gets most of the edge; raw-hash stays only a tie-breaker.
            p=.5+(hist_p-.5)*.72+(base_p-.5)*.14
            hist_used=True

    direction='TÀI' if p>=.5 else 'XỈU'
    edge=abs(p-.5)
    # Confidence now means signal strength, not claimed win probability.
    cap=58.0
    if hist_used:
        acc=float(hist.get('accuracy',.5)); sample=int(hist.get('sample',0))
        cap=60.0 if acc<.56 else 62.0 if sample>=400 else 60.5
    strength=50+min(cap-50,edge*100*1.35)
    # Disagreement in the old ensemble can only reduce confidence.
    if base_agree<.56:strength=min(strength,54.5)
    strength=_clip(strength,50.5,cap)
    tai=round(strength if direction=='TÀI' else 100-strength,2);xiu=round(100-tai,2)
    level='MẠNH' if hist_used and max(tai,xiu)>=60.5 else 'KHÁ' if max(tai,xiu)>=56.0 else 'NHẸ'
    result=dict(base,prediction=direction,tai_pct=tai,xiu_pct=xiu,
                agreement=round(base_agree*100,1),level=level,models=36,
                calibrated=True,hist_used=hist_used,
                hist_sample=int(hist.get('sample',0)) if hist else 0,
                hist_accuracy=round(float(hist.get('accuracy',.5))*100,1) if hist else 50.0)
    _hash_v57_cache[z]=dict(result);_hash_v57_order.append(z)
    if len(_hash_v57_order)>4096:
        old=_hash_v57_order.pop(0);_hash_v57_cache.pop(old,None)
    return result


def format_hash_prediction(hash_hex,result=None):
    r=result or hash_ultra_predict(hash_hex)
    note=(f" · học LS {r.get('hist_accuracy',50):.1f}%" if r.get('hist_used') else '')
    return (f"<b>🔐 {r['type']}</b>\n"
            f"TÀI <b>{r['tai_pct']:.2f}%</b>  •  XỈU <b>{r['xiu_pct']:.2f}%</b>\n"
            f"🎯 <b>{r['prediction']} · {r['level']}</b>\n"
            f"<i>{r['models']} tín hiệu · đã hiệu chỉnh{note}</i>")

_v55_refresh_shared_prediction_v56 = refresh_shared_prediction

async def refresh_shared_prediction(board,current_session=None):
    pred=await _v55_refresh_shared_prediction_v56(board,current_session);_v56_pred_cache.pop(board,None);return pred

def tao_xoai_tips_text():
    return ("<b>🍏🥭 TÁO XOÀI TOOL — 5 NGUYÊN TẮC</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<b>🟢 01 · NHÌN NHỊP</b>\n"
            "👀 Xem vài phiên trước\n📊 Đọc cả chuỗi, không nhìn 1 tay\n🔥 Tín hiệu rõ → theo dõi\n🌫️ Nhiễu mạnh → đứng ngoài\n"
            "<i>Không rõ nhịp thì không cần vào.</i>\n\n"
            "<b>🔵 02 · ĐỌC TÍN HIỆU</b>\n"
            "🔥 MẠNH → nhiều tín hiệu cùng hướng\n⚡ KHÁ → có xu hướng, vẫn cần quan sát\n🌪️ YẾU → xung đột cao, ưu tiên bỏ\n"
            "📈 % = độ nghiêng của engine, không phải chắc thắng\n\n"
            "<b>🟡 03 · MẤT NHỊP THÌ DỪNG</b>\n"
            "❌ Sai 1 phiên → bình thường\n❌❌ Sai liên tiếp → dừng quan sát\n🔀 T/X đảo liên tục → không đuổi cầu\n"
            "<i>Tool mất nhịp → chờ nhịp mới.</i>\n\n"
            "<b>🟠 04 · GIỮ VỐN</b>\n"
            "💰 Chia vốn nhỏ\n🚫 Không all-in\n🚫 Không gấp thếp\n📉 Chạm mức lỗ → dừng\n📈 Đạt mục tiêu → chốt\n\n"
            "<b>🔴 05 · GIỮ CÁI ĐẦU</b>\n"
            "😤 Nóng → nghỉ\n😵 Mệt → nghỉ\n🍺 Say → nghỉ\n💸 Muốn gỡ → nghỉ\n❤️ Mất bình tĩnh → tắt tool\n\n"
            "<b>🍏🥭 4 CÂU NHỚ NHANH</b>\n"
            "👀 Không rõ → CHỜ\n🌫️ Nhiễu → BỎ\n😤 Nóng → NGHỈ\n✅ Đủ → DỪNG\n\n"
            "⚠️ <i>Tool chỉ hỗ trợ phân tích tín hiệu thống kê, không bảo đảm kết quả.</i>")

_v55_bot_games_keyboard_v56 = bot_games_keyboard

_v55_bot_home_text_v56 = bot_home_text

_v55_bot_handle_message_v56 = bot_handle_message

_v55_bot_handle_callback_v56 = bot_handle_callback

def bot_home_text(chat_id):
    txt=_v55_bot_home_text_v56(chat_id)
    return txt.replace('55 MODEL','67 MODEL').replace('61 MODEL','67 MODEL').replace('HASH-30','HASH-36')

def bot_games_keyboard(chat_id):
    kb=_v55_bot_games_keyboard_v56(chat_id)
    rows=[list(r) for r in (kb.get('inline_keyboard') or [])]
    # Keep admin row at the bottom and add the tips card before it.
    insert_at=len(rows)
    for i,row in enumerate(rows):
        if any((b.get('callback_data')=='adminhome') for b in row if isinstance(b,dict)):
            insert_at=i;break
    if not any(any((b.get('callback_data')=='tips') for b in row if isinstance(b,dict)) for row in rows):
        rows.insert(insert_at,[{'text':'🍏🥭 MẸO DÙNG TOOL','callback_data':'tips'}])
    return {'inline_keyboard':rows}

async def bot_handle_message(client,msg):
    chat=msg.get('chat') or {};chat_id=chat.get('id');text=(msg.get('text') or '').strip();cmd=text.split(maxsplit=1)[0].split('@',1)[0].lower() if text.startswith('/') else ''
    if chat_id and cmd in ('/meo','/tips','/huongdan'):
        kb={'inline_keyboard':[[{'text':'⌂ HOME','callback_data':'home'}]]}
        payload=_v53_group_reply_payload(chat_id,tao_xoai_tips_text(),msg,kb) if is_group_chat_id(chat_id) else _v49_send_payload(chat_id,tao_xoai_tips_text(),kb)
        await tg_call(client,'sendMessage',payload);return
    return await _v55_bot_handle_message_v56(client,msg)

async def bot_handle_callback(client,q):
    msg=q.get('message') or {};chat_id=(msg.get('chat') or {}).get('id');data=q.get('data') or ''
    if chat_id and data=='tips':
        try:await tg_call(client,'answerCallbackQuery',{'callback_query_id':q.get('id')})
        except Exception:pass
        await tg_panel(client,q,tao_xoai_tips_text(),{'inline_keyboard':[[{'text':'⌂ HOME','callback_data':'home'}]]});return
    return await _v55_bot_handle_callback_v56(client,q)

_v56_update_sem=asyncio.Semaphore(24)

_v56_update_tasks=set()

async def _v56_dispatch_update(client,upd):
    async with _v56_update_sem:
        try:
            if upd.get('callback_query'):await bot_handle_callback(client,upd['callback_query'])
            elif upd.get('message'):await bot_handle_message(client,upd['message'])
            elif upd.get('my_chat_member'):await bot_handle_my_chat_member(client,upd['my_chat_member'])
        except Exception:pass

async def telegram_loop():
    offset=0
    limits=httpx.Limits(max_connections=40,max_keepalive_connections=28,keepalive_expiry=30.0)
    timeout=httpx.Timeout(10.0,connect=3.0,pool=2.0)
    async with httpx.AsyncClient(limits=limits,timeout=timeout) as client:
        try:
            await tg_call(client,'setMyName',{'name':BOT_NAME})
            await tg_call(client,'setMyShortDescription',{'short_description':'💯 SUNWIN • LC79 • ULTRA • HASH-36'})
            await tg_call(client,'setMyDescription',{'description':f'{BOT_NAME} · SUNWIN & LC79 · 67 strategy · HASH-36 · group full tool.'})
        except Exception:pass
        try:
            user_commands=[
              {'command':'start','description':'💯 Mở bot'},
              {'command':'game','description':'🎮 Chọn SUNWIN / LC79'},
              {'command':'dudoan','description':'🎯 Dự đoán bàn đang chọn'},
              {'command':'lichsu','description':'📜 Lịch sử húp/gãy'},
              {'command':'meo','description':'🍏🥭 5 nguyên tắc dùng tool'}]
            await tg_call(client,'setMyCommands',{'commands':user_commands})
            admin_commands=user_commands+[
              {'command':'quantri','description':'◆ Bảng quản trị'},
              {'command':'thongke','description':'📊 Thống kê user'},
              {'command':'nguoidung','description':'👥 Danh sách user'},
              {'command':'thongtin','description':'👤 Chi tiết user'},
              {'command':'capquyen','description':'✅ Cấp quyền user'},
              {'command':'thuquyen','description':'⛔ Thu quyền user'},
              {'command':'kiemtraapi','description':'📡 Trạng thái API'},
              {'command':'doapi','description':'🔧 Đổi API bàn'},
              {'command':'linkgame','description':'↗ Đặt link game'}]
            for aid in ADMIN_IDS:
                try:await tg_call(client,'setMyCommands',{'commands':admin_commands,'scope':{'type':'chat','chat_id':int(aid)}})
                except Exception:pass
        except Exception:pass
        try:await tg_call(client,'deleteWebhook',{'drop_pending_updates':False})
        except Exception:pass
        while True:
            try:
                result=await tg_call(client,'getUpdates',{'offset':offset,'timeout':BOT_POLL_TIMEOUT,'limit':100,'allowed_updates':['message','callback_query','my_chat_member']}) or []
                for upd in result:
                    offset=max(offset,int(upd.get('update_id',0))+1)
                    task=asyncio.create_task(_v56_dispatch_update(client,upd));_v56_update_tasks.add(task);task.add_done_callback(_v56_update_tasks.discard)
            except asyncio.CancelledError:raise
            except Exception:await asyncio.sleep(.20)

async def run_telegram_bot():
    global _worker_task, _bot_task
    ensure_db()
    try:
        ensure_hash_tables()
    except Exception:
        pass
    if not BOT_TOKEN:
        raise RuntimeError('Thiếu BOT_TOKEN. Hãy đặt biến môi trường BOT_TOKEN rồi chạy lại.')

    print(f'🍏🥭 Telegram bot starting... | boards={len(available_bot_boards())} | DB={DB_PATH}')
    _worker_task = asyncio.create_task(worker_loop(), name='game-worker')
    _bot_task = asyncio.create_task(telegram_loop(), name='telegram-polling')
    try:
        await asyncio.gather(_worker_task, _bot_task)
    finally:
        for task in (_worker_task, _bot_task):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in (_worker_task, _bot_task) if t], return_exceptions=True)

def main():
    try:
        asyncio.run(run_telegram_bot())
    except KeyboardInterrupt:
        print('\nBot đã dừng.')

if __name__ == '__main__':
    main()
