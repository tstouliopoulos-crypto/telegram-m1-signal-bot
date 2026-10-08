import os,time,threading,requests
from flask import Flask,jsonify
app=Flask(__name__)
BOT_TOKEN=os.getenv('BOT_TOKEN',''); CHAT_ID=os.getenv('CHAT_ID',''); SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT']; seen={}
def send(text):
    if not BOT_TOKEN or not CHAT_ID: print('Telegram credentials not configured'); return
    requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',data={'chat_id':CHAT_ID,'text':text},timeout=10)
def ema(v,n):
    if len(v)<n:return None
    k=2/(n+1);e=v[0]
    for x in v[1:]:e=x*k+e*(1-k)
    return e
def analyse(cs):
    c=cs[:-1]
    if len(c)<30:return 'WAIT','Λίγα candles',0
    closes=[x['close'] for x in c]; f,s=ema(closes[-30:],9),ema(closes[-30:],21); last,prev=c[-1],c[-2]
    body=lambda x:abs(x['close']-x['open']); avg=sum(body(x) for x in c[-11:-1])/10; up=down=0
    if f>s:up+=2
    if f<s:down+=2
    if last['close']>f:up+=1
    if last['close']<f:down+=1
    if f>s and prev['close']<prev['open'] and last['close']>last['open']:up+=2
    if f<s and prev['close']>prev['open'] and last['close']<last['open']:down+=2
    if last['close']>last['open'] and body(last)>=avg*.8:up+=1
    if last['close']<last['open'] and body(last)>=avg*.8:down+=1
    if body(last)>avg*2.5:return 'WAIT','Μεγάλο candle — αποφυγή',0
    if up>=5 and up>down:return 'UP','Τάση + pullback + bullish επιβεβαίωση',min(95,70+up*4)
    if down>=5 and down>up:return 'DOWN','Τάση + pullback + bearish επιβεβαίωση',min(95,70+down*4)
    return 'WAIT','Δεν υπάρχει αρκετή επιβεβαίωση',0
def get_candles(symbol):
    r=requests.get('https://api.binance.com/api/v3/klines',params={'symbol':symbol,'interval':'1m','limit':80},timeout=10);r.raise_for_status()
    return [{'time':int(x[0]),'open':float(x[1]),'close':float(x[4])} for x in r.json()]
def loop():
    while True:
        for symbol in SYMBOLS:
            try:
                cs=get_candles(symbol); closed=cs[-2]['time']
                if seen.get(symbol)==closed:continue
                seen[symbol]=closed; sig,reason,conf=analyse(cs)
                if sig in ('UP','DOWN'):
                    icon='🟢' if sig=='UP' else '🔴';send(f'{icon} {sig}\n{symbol}\n⏱️ M1\nFilter: {conf}%\n{reason}\n⚠️ DEMO / SIGNAL ONLY');print(symbol,sig,conf)
            except Exception as e:print('ERROR',symbol,e)
        time.sleep(5)
@app.get('/')
def home():return jsonify({'status':'online','service':'Telegram M1 Signal Bot','mode':'signal-only'})
@app.get('/health')
def health():return 'OK',200
threading.Thread(target=loop,daemon=True).start()
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
