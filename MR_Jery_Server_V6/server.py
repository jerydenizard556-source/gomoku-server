import asyncio,json,secrets,string,time,os,hashlib,hmac,re
import websockets, psycopg2
from websockets.http11 import Headers, Response
HOST='0.0.0.0'; PORT=int(os.environ.get('PORT','10000')); BOARD_SIZE=20; START_TIME=600; RECONNECT_GRACE_SECONDS=45; INVITATION_TTL_SECONDS=90
DATABASE_URL=os.environ.get('DATABASE_URL'); db=None
if DATABASE_URL:
    try:
        db=psycopg2.connect(DATABASE_URL); db.autocommit=True
        c=db.cursor(); c.execute('''CREATE TABLE IF NOT EXISTS players (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, email VARCHAR(255) UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''); c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS points INTEGER NOT NULL DEFAULT 0"); c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS wins INTEGER NOT NULL DEFAULT 0"); c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS losses INTEGER NOT NULL DEFAULT 0"); c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS draws INTEGER NOT NULL DEFAULT 0"); c.execute('''CREATE TABLE IF NOT EXISTS account_sessions (token_hash VARCHAR(64) PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''); c.close(); print('PostgreSQL database connected.')
    except Exception as e: print('Database connection error:',repr(e)); db=None

def hash_password(p):
    s=secrets.token_bytes(16); h=hashlib.pbkdf2_hmac('sha256',p.encode(),s,200000); return f'pbkdf2_sha256$200000${s.hex()}${h.hex()}'
def verify_password(p,x):
    try:
        a,it,s,h=x.split('$');
        if a!='pbkdf2_sha256': return False
        z=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),int(it)); return hmac.compare_digest(z,bytes.fromhex(h))
    except: return False
def valid_username(x): return bool(x) and 3<=len(x)<=50 and re.fullmatch(r'[A-Za-z0-9_]+',x) is not None
def valid_email(x): return bool(x) and len(x)<=255 and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',x) is not None
connected_accounts={}
account_tokens={}
def token_hash(t): return hashlib.sha256(str(t).encode()).hexdigest()
def set_account(ws,pid,u,e,t):
    connected_accounts[ws]={'player_id':pid,'username':u,'email':e,'account_token':t}
    account_tokens[t]={'player_id':pid,'username':u,'email':e}
    if db is not None:
        try:
            c=db.cursor(); c.execute('INSERT INTO account_sessions(token_hash,player_id) VALUES(%s,%s) ON CONFLICT(token_hash) DO UPDATE SET player_id=EXCLUDED.player_id,created_at=CURRENT_TIMESTAMP',(token_hash(t),pid)); c.close()
        except Exception as ex: print('Session save error:',repr(ex))
def username(ws,fallback): return connected_accounts.get(ws,{}).get('username',fallback)
async def send(ws,d):
    try: await ws.send(json.dumps(d))
    except: pass
async def register(ws,u,e,p,pc):
    if db is None: return await send(ws,{'type':'register_result','success':False,'message':'Database pa disponib.'})
    u=str(u or '').strip(); e=str(e or '').strip().lower(); p=str(p or ''); pc=str(pc or '')
    if not valid_username(u): return await send(ws,{'type':'register_result','success':False,'message':'Pseudo a dwe genyen 3-50 karaktè epi sèlman lèt, chif oswa _.'})
    if not valid_email(e): return await send(ws,{'type':'register_result','success':False,'message':'Email la pa valid.'})
    if len(p)<8: return await send(ws,{'type':'register_result','success':False,'message':'Password la dwe genyen omwen 8 karaktè.'})
    if p!=pc: return await send(ws,{'type':'register_result','success':False,'message':'Password yo pa menm.'})
    try:
        c=db.cursor(); c.execute('SELECT id FROM players WHERE LOWER(username)=LOWER(%s)',(u,));
        if c.fetchone(): c.close(); return await send(ws,{'type':'register_result','success':False,'message':'Pseudo sa deja itilize.'})
        c.execute('SELECT id FROM players WHERE LOWER(email)=LOWER(%s)',(e,));
        if c.fetchone(): c.close(); return await send(ws,{'type':'register_result','success':False,'message':'Email sa deja itilize.'})
        c.execute('INSERT INTO players(username,email,password_hash) VALUES(%s,%s,%s) RETURNING id',(u,e,hash_password(p))); pid=c.fetchone()[0]; c.close(); t=secrets.token_urlsafe(32); set_account(ws,pid,u,e,t)
        await send(ws,{'type':'register_result','success':True,'message':'Kont lan kreye avèk siksè.','player_id':pid,'username':u,'email':e,'account_token':t,'points':0,'wins':0,'losses':0,'draws':0,'level':1})
    except Exception as ex: print('Register error:',repr(ex)); await send(ws,{'type':'register_result','success':False,'message':'Erè pandan kreyasyon kont lan.'})
async def login(ws,l,p):
    if db is None: return await send(ws,{'type':'login_result','success':False,'message':'Database pa disponib.'})
    l=str(l or '').strip(); p=str(p or '')
    if not l or not p: return await send(ws,{'type':'login_result','success':False,'message':'Tanpri ranpli tout chan yo.'})
    try:
        c=db.cursor(); c.execute('SELECT id,username,email,password_hash,points,wins,losses,draws FROM players WHERE LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s) LIMIT 1',(l,l)); row=c.fetchone(); c.close()
        if not row or not verify_password(p,row[3]): return await send(ws,{'type':'login_result','success':False,'message':'Pseudo/email oswa password la pa kòrèk.'})
        t=secrets.token_urlsafe(32); set_account(ws,row[0],row[1],row[2],t); await send(ws,{'type':'login_result','success':True,'message':'Login reyisi.','player_id':row[0],'username':row[1],'email':row[2],'account_token':t,'points':row[4] or 0,'wins':row[5] or 0,'losses':row[6] or 0,'draws':row[7] or 0,'level':1+int((row[4] or 0)//30)})
    except Exception as ex: print('Login error:',repr(ex)); await send(ws,{'type':'login_result','success':False,'message':'Erè pandan login.'})
rooms={}; queue=[]
def code():
    while True:
        x=''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
        if x not in rooms:return x
def board(): return [[0]*BOARD_SIZE for _ in range(BOARD_SIZE)]
def room_base(size=BOARD_SIZE,duration=START_TIME): return {'board':[[0]*size for _ in range(size)],'board_size':size,'duration':duration,'players':{},'spectators':set(),'turn':1,'starter':1,'black_time':duration,'red_time':duration,'last_timer_update':time.monotonic(),'game_over':False,'winner':0,'draw':False,'abandonment':False,'black_score':0,'red_score':0,'game_number':1,'last_move':None,'last_move_was_win':False,'winning_line':None,'rematch_request':None,'undo_request':None,'move_history':[],'chat':[],'stats_recorded':False}
def new_room():
    c=code(); rooms[c]=room_base(); return c
def session(): return secrets.token_urlsafe(32)
def pstate(r,n):
    p=r['players'].get(n,{})
    return {'connected':p.get('connected',False),'username':p.get('username',f'Joueur {n}'),'name':p.get('username',f'Joueur {n}'),'player_id':p.get('player_id')}
def find(r,ws):
    for n,p in r['players'].items():
        if p.get('socket') is ws:return n
    return None

def active_room_for(ws):
    for room_code, room in rooms.items():
        if find(room, ws) is not None and not room.get('game_over'):
            return room_code
    return None

def remove_spec(ws):
    for r in rooms.values(): r['spectators'].discard(ws)
def level_for_points(points): return 1 + max(0,int(points or 0)//30)
def get_stats(pid):
    if db is None or not pid: return {'points':0,'wins':0,'losses':0,'draws':0,'level':1}
    try:
        c=db.cursor(); c.execute('SELECT points,wins,losses,draws FROM players WHERE id=%s',(pid,)); row=c.fetchone(); c.close()
        if not row: return {'points':0,'wins':0,'losses':0,'draws':0,'level':1}
        return {'points':row[0] or 0,'wins':row[1] or 0,'losses':row[2] or 0,'draws':row[3] or 0,'level':level_for_points(row[0] or 0)}
    except Exception as e: print('Stats read error:',repr(e)); return {'points':0,'wins':0,'losses':0,'draws':0,'level':1}
async def record_result(r):
    if r.get('stats_recorded') or not r.get('game_over'): return
    r['stats_recorded']=True
    for n,p in r.get('players',{}).items():
        pid=p.get('player_id')
        if not pid or db is None: continue
        try:
            c=db.cursor()
            if r.get('draw'):
                c.execute('UPDATE players SET points=points+1, draws=draws+1 WHERE id=%s',(pid,))
            elif int(n)==int(r.get('winner',0)):
                c.execute('UPDATE players SET points=points+3, wins=wins+1 WHERE id=%s',(pid,))
            else:
                c.execute('UPDATE players SET losses=losses+1 WHERE id=%s',(pid,))
            c.close()
        except Exception as e: print('Stats update error:',repr(e))
def winline(b,rr,cc,p):
    size=len(b)
    for dr,dc in ((0,1),(1,0),(1,1),(1,-1)):
        line=[(rr,cc)]; r,c=rr-dr,cc-dc
        while 0<=r<size and 0<=c<size and b[r][c]==p: line.insert(0,(r,c)); r-=dr;c-=dc
        r,c=rr+dr,cc+dc
        while 0<=r<size and 0<=c<size and b[r][c]==p: line.append((r,c));r+=dr;c+=dc
        if len(line)==5:return line
    return None
def update_timer(r):
    if r['game_over'] or r['rematch_request'] is not None: r['last_timer_update']=time.monotonic(); return
    now=time.monotonic(); d=max(0,now-r['last_timer_update']);r['last_timer_update']=now
    k='black_time' if r['turn']==1 else 'red_time';r[k]=max(0,r[k]-d)
    if r[k]<=0:
        r['game_over']=True;r['winner']=2 if r['turn']==1 else 1;r['draw']=False;r['abandonment']=False
        r['black_score']+=r['winner']==1;r['red_score']+=r['winner']==2
        asyncio.create_task(record_result(r))
async def state(r):
    update_timer(r); return {'type':'state','board':r['board'],'board_size':r.get('board_size',BOARD_SIZE),'turn':r['turn'],'starter':r['starter'],'black_time':r['black_time'],'red_time':r['red_time'],'game_over':r['game_over'],'winner':r['winner'],'draw':r['draw'],'abandonment':r['abandonment'],'black_score':r['black_score'],'red_score':r['red_score'],'game_number':r['game_number'],'last_move':r['last_move'],'last_move_was_win':r['last_move_was_win'],'winning_line':r['winning_line'],'rematch_request':r['rematch_request'],'undo_request':r.get('undo_request'),'players':{'1':pstate(r,1),'2':pstate(r,2)},'spectator_count':len(r['spectators']),'spectators_count':len(r['spectators']),'waiting':not (r['players'].get(1,{}).get('connected') and r['players'].get(2,{}).get('connected')),'stats':{'1':get_stats(r['players'].get(1,{}).get('player_id')),'2':get_stats(r['players'].get(2,{}).get('player_id'))},'chat':r.get('chat',[]) }
async def broadcast(r):
    s=await state(r)
    for p in r['players'].values():
        if p.get('socket'): await send(p['socket'],s)
    for ws in list(r['spectators']): await send(ws,s)
async def create(ws, size=BOARD_SIZE, duration=START_TIME):
    existing=active_room_for(ws)
    if existing: return await send(ws,{'type':'error','message':'Ou deja nan yon match. Kite oswa fini match sa anvan.'})
    remove_spec(ws)
    c=code();rooms[c]=room_base(max(13,min(20,int(size or BOARD_SIZE))),max(60,min(1800,int(duration or START_TIME))));r=rooms[c];t=session();r['players'][1]={'socket':ws,'connected':True,'session_token':t,'username':username(ws,'Joueur 1'),'player_id':connected_accounts.get(ws,{}).get('player_id')};await send(ws,{'type':'created','room':c,'player':1,'session_token':t,'username':r['players'][1]['username']});await broadcast(r)
async def join(ws,c):
    existing=active_room_for(ws)
    if existing: return await send(ws,{'type':'error','message':'Ou deja nan yon match. Kite oswa fini match sa anvan.'})
    remove_spec(ws)
    c=str(c or '').upper().strip();
    if c not in rooms:return await send(ws,{'type':'error','message':'Room introuvable.'})
    r=rooms[c]
    if 2 in r['players']:
        return await send(ws,{'type':'error','message':'Room sa deja gen 2 jwè. Chwazi Spectateur.'})
    t=session();r['players'][2]={'socket':ws,'connected':True,'session_token':t,'username':username(ws,'Joueur 2'),'player_id':connected_accounts.get(ws,{}).get('player_id')};await send(ws,{'type':'joined','room':c,'player':2,'session_token':t,'username':r['players'][2]['username']});await broadcast(r)
async def find_match(ws):
    existing=active_room_for(ws)
    if existing: return await send(ws,{'type':'error','message':'Ou deja nan yon match.'})
    remove_spec(ws);queue[:]=[x for x in queue if x is not ws]
    if queue:
        a=queue.pop(0);c=code();r=room_base();rooms[c]=r
        n1=username(a,'Joueur 1');n2=username(ws,'Joueur 2');t1=session();t2=session();r['players']={1:{'socket':a,'connected':True,'session_token':t1,'username':n1,'player_id':connected_accounts.get(a,{}).get('player_id')},2:{'socket':ws,'connected':True,'session_token':t2,'username':n2,'player_id':connected_accounts.get(ws,{}).get('player_id')}}
        await send(a,{'type':'match_found','room':c,'player':1,'session_token':t1,'username':n1,'message':'🎮 Adversaire trouvé ! Le match va commencer.'});await send(ws,{'type':'match_found','room':c,'player':2,'session_token':t2,'username':n2,'message':'🎮 Adversaire trouvé ! Le match va commencer.'});await broadcast(r)
    else: queue.append(ws);await send(ws,{'type':'searching','message':'Ap chèche yon adversè...'})
async def cancel(ws):
    queue[:]=[x for x in queue if x is not ws];await send(ws,{'type':'match_cancelled'})
async def watch(ws,c):
    if active_room_for(ws): return await send(ws,{'type':'watch_error','success':False,'message':'Ou deja ap jwe yon match.'})
    c=str(c or '').upper().strip()
    if c not in rooms:return await send(ws,{'type':'watch_error','success':False,'message':'Match sa pa egziste.'})
    remove_spec(ws);r=rooms[c];r['spectators'].add(ws);await send(ws,{'type':'watching','room':c,'spectator':True});await broadcast(r)
async def live(ws):
    out=[]
    for c,r in rooms.items():
        if len(r['players'])==2 and not r['game_over'] and all(p.get('connected') for p in r['players'].values()):
            out.append({'room':c,'player1':pstate(r,1)['username'],'player2':pstate(r,2)['username'],'spectator_count':len(r['spectators']),'game_over':r['game_over']})
    await send(ws,{'type':'live_matches','matches':out})
async def reconnect(ws,c,n,t):
    c=str(c or '').upper().strip()
    try:n=int(n)
    except:return
    if c not in rooms or n not in rooms[c]['players'] or rooms[c]['players'][n].get('session_token')!=t:return await send(ws,{'type':'error','message':'Session token invalid.'})
    r=rooms[c];remove_spec(ws)
    # If the same player reconnects from a new socket, invalidate the old socket's room membership.
    old_socket=r['players'][n].get('socket')
    if old_socket is not None and old_socket is not ws:
        try: await send(old_socket,{'type':'session_replaced','message':'Kont sa a konekte sou yon lòt koneksyon.'})
        except Exception: pass
    r['players'][n]['socket']=ws;r['players'][n]['connected']=True;r['players'][n].pop('disconnected_at',None);r['players'][n].pop('disconnect_marker',None)
    await send(ws,{'type':'reconnected','room':c,'player':n,'session_token':t,'username':r['players'][n]['username']});await broadcast(r)
async def move(ws,c,rr,cc):
    c=str(c or '').upper().strip()
    if c not in rooms:return
    r=rooms[c];n=find(r,ws)
    if n is None:return await send(ws,{'type':'error','message':'Spectatè yo pa kapab jwe.'})
    if r['game_over'] or r['rematch_request'] is not None or r.get('undo_request') is not None or n!=r['turn']:return
    try:rr=int(rr);cc=int(cc)
    except:return
    size=len(r['board'])
    if not(0<=rr<size and 0<=cc<size) or r['board'][rr][cc]:return
    update_timer(r)
    if r['game_over']:return await broadcast(r)
    r['move_history'].append({'board':[row[:] for row in r['board']],'turn':r['turn'],'last_move':r['last_move'],'last_move_was_win':r['last_move_was_win'],'winning_line':r['winning_line'],'game_over':r['game_over'],'winner':r['winner'],'draw':r['draw']})
    r['board'][rr][cc]=n;r['last_move']={'row':rr,'col':cc,'player':n};r['last_move_was_win']=False;r['winning_line']=None
    wl=winline(r['board'],rr,cc,n)
    if wl:r['game_over']=True;r['winner']=n;r['winning_line']=[{'row':a,'col':b} for a,b in wl];r['last_move_was_win']=True;r['black_score']+=n==1;r['red_score']+=n==2
    elif all(all(x for x in row) for row in r['board']):r['game_over']=True;r['draw']=True;r['winner']=0
    else:r['turn']=2 if n==1 else 1
    if r['game_over']: await record_result(r)
    await broadcast(r)
async def rematch_req(ws,c):
    c=str(c or '').upper().strip();
    if c not in rooms:return
    r=rooms[c];n=find(r,ws)
    if n is None or not r['game_over'] or r['rematch_request'] is not None:return
    # requester must be the loser, unless draw (either player may request)
    if not r['draw'] and r['winner']==n:return
    r['rematch_request']=n;r['last_timer_update']=time.monotonic();await broadcast(r)
async def rematch_resp(ws,c,accepted):
    c=str(c or '').upper().strip();
    if c not in rooms:return
    r=rooms[c];n=find(r,ws);q=r['rematch_request']
    if n is None or q is None or n==q:return
    if accepted:
        r['starter']=2 if r['starter']==1 else 1;r['turn']=r['starter'];r['game_number']+=1;r['board']=[[0]*r.get('board_size',BOARD_SIZE) for _ in range(r.get('board_size',BOARD_SIZE))];r['black_time']=r.get('duration',START_TIME);r['red_time']=r.get('duration',START_TIME);r['move_history']=[];r['undo_request']=None;r['game_over']=False;r['winner']=0;r['draw']=False;r['abandonment']=False;r['last_move']=None;r['last_move_was_win']=False;r['winning_line']=None
    r['rematch_request']=None;r['undo_request']=None;r['stats_recorded']=False;r['chat']=[];r['last_timer_update']=time.monotonic();await broadcast(r)
async def chat(ws,c,message):
    c=str(c or '').upper().strip()
    if c not in rooms: return
    r=rooms[c]; n=find(r,ws)
    is_spec=ws in r['spectators']
    if n is None and not is_spec: return
    msg=str(message or '').strip()[:300]
    if not msg: return
    sender=username(ws,'Spectateur' if is_spec else f'Joueur {n}')
    item={'sender':sender,'role':'spectator' if is_spec else 'player','text':msg,'time':int(time.time())}
    r.setdefault('chat',[]).append(item); r['chat']=r['chat'][-80:]
    await broadcast(r)
async def voice_join(ws, c):
    c=str(c or '').upper().strip()
    if c not in rooms: return
    r=rooms[c]; n=find(r,ws); is_spec=ws in r['spectators']
    if n is None and not is_spec: return
    peers=[]
    for pn, player in r['players'].items():
        other=player.get('socket')
        if other is not None and other is not ws:
            peers.append({'peer_id':str(id(other))})
    for other in list(r['spectators']):
        if other is not ws:
            peers.append({'peer_id':str(id(other))})
    await send(ws,{'type':'voice_peer_list','room':c,'peers':peers})
    for peer in list(r['players'].values()):
        other=peer.get('socket')
        if other is not None and other is not ws:
            await send(other,{'type':'voice_peer_join','room':c,'peer_id':str(id(ws))})
    for other in list(r['spectators']):
        if other is not ws:
            await send(other,{'type':'voice_peer_join','room':c,'peer_id':str(id(ws))})

async def voice_signal(ws, c, to, signal_type, payload):
    c=str(c or '').upper().strip()
    if c not in rooms: return
    r=rooms[c]; n=find(r,ws); is_spec=ws in r['spectators']
    if n is None and not is_spec: return
    signal_type=str(signal_type or '')
    if signal_type not in ('description','ice'): return
    try: target_id=int(to)
    except (TypeError,ValueError): return
    targets=[]
    for player in r['players'].values():
        other=player.get('socket')
        if other is not None and other is not ws and id(other)==target_id: targets.append(other)
    for other in list(r['spectators']):
        if other is not ws and id(other)==target_id: targets.append(other)
    if not targets: return
    safe_payload=payload if isinstance(payload,dict) else {}
    # Payload size cap prevents signaling messages from becoming a general data channel.
    if len(json.dumps(safe_payload))>12000: return
    await send(targets[0],{'type':'voice_signal','room':c,'from_id':str(id(ws)),'signal_type':signal_type,'payload':safe_payload})

async def rooms_list(ws):
    out=[]
    for c,r in rooms.items():
        p1=pstate(r,1); p2=pstate(r,2)
        connected=sum(1 for p in r['players'].values() if p.get('connected'))
        if connected>0:
            out.append({'room':c,'player1':p1['username'],'player2':p2['username'] if 2 in r['players'] else None,'players':connected,'spectator_count':len(r['spectators']),'game_over':r['game_over']})
    await send(ws,{'type':'rooms_list','rooms':out})
async def reset(ws,c):
    c=str(c or '').upper().strip();
    if c not in rooms:return
    r=rooms[c];n=find(r,ws)
    if n is None or not r['game_over']:return
    r['starter']=2 if r['starter']==1 else 1;r['turn']=r['starter'];r['game_number']+=1;r['board']=[[0]*r.get('board_size',BOARD_SIZE) for _ in range(r.get('board_size',BOARD_SIZE))];r['black_time']=r.get('duration',START_TIME);r['red_time']=r.get('duration',START_TIME);r['move_history']=[];r['undo_request']=None;r['game_over']=False;r['winner']=0;r['draw']=False;r['abandonment']=False;r['last_move']=None;r['last_move_was_win']=False;r['winning_line']=None;r['rematch_request']=None;r['undo_request']=None;r['stats_recorded']=False;r['chat']=[];await broadcast(r)
async def abandon_if_disconnected(room_code, player_number, marker):
    """Only forfeit after a reconnect grace period, not on a brief network drop."""
    await asyncio.sleep(RECONNECT_GRACE_SECONDS)
    r=rooms.get(room_code)
    if not r or r.get('game_over'):
        return
    p=r.get('players',{}).get(player_number,{})
    if p.get('connected') or p.get('disconnect_marker') != marker or p.get('socket') is not None:
        return
    if len(r.get('players',{})) < 2:
        return
    other=2 if player_number==1 else 1
    if not r.get('players',{}).get(other,{}).get('connected'):
        return
    r['game_over']=True; r['winner']=other; r['draw']=False; r['abandonment']=True
    r['winning_line']=None; r['rematch_request']=None; r['undo_request']=None
    r['black_score']+=int(other==1); r['red_score']+=int(other==2)
    await record_result(r)
    await broadcast(r)

async def disconnect(ws):
    queue[:]=[x for x in queue if x is not ws]
    for iid,inv in list(invitations.items()):
        if inv.get('from_ws') is ws or inv.get('to_ws') is ws:
            invitations.pop(iid,None)
    connected_accounts.pop(ws,None)
    remove_spec(ws)
    for room_code,r in list(rooms.items()):
        n=find(r,ws)
        if n is None:
            continue
        p=r['players'][n]
        # A replaced socket must not mark the newer connection as disconnected.
        if p.get('socket') is not ws:
            continue
        p['connected']=False; p['socket']=None
        marker=secrets.token_urlsafe(12)
        p['disconnected_at']=time.monotonic(); p['disconnect_marker']=marker
        await broadcast(r)
        if not r.get('game_over') and len(r.get('players',{}))==2:
            asyncio.create_task(abandon_if_disconnected(room_code,n,marker))

async def timer_loop():
    while True:
        await asyncio.sleep(1)
        for r in list(rooms.values()):
            if r['game_over'] or r['rematch_request'] is not None:continue
            b,red=r['black_time'],r['red_time'];update_timer(r)
            if b!=r['black_time'] or red!=r['red_time'] or r['game_over']:await broadcast(r)
async def restore_session(ws, token):
    token=str(token or '')
    info=account_tokens.get(token)
    if info is None and db is not None and token:
        try:
            c=db.cursor(); c.execute('SELECT p.id,p.username,p.email FROM account_sessions s JOIN players p ON p.id=s.player_id WHERE s.token_hash=%s',(token_hash(token),)); row=c.fetchone(); c.close()
            if row:
                info={'player_id':row[0],'username':row[1],'email':row[2]}; account_tokens[token]=info
        except Exception as ex: print('Session restore error:',repr(ex))
    if not info:
        return await send(ws,{'type':'restore_session_result','success':False,'message':'Session invalide.'})
    set_account(ws,info['player_id'],info['username'],info['email'],token)
    stats=get_stats(info['player_id'])
    await send(ws,{'type':'restore_session_result','success':True,'player_id':info['player_id'],'username':info['username'],'email':info['email'],'account_token':token,**stats})

async def logout_session(ws, token):
    token=str(token or connected_accounts.get(ws,{}).get('account_token') or '')
    if token:
        account_tokens.pop(token,None)
        if db is not None:
            try:
                c=db.cursor(); c.execute('DELETE FROM account_sessions WHERE token_hash=%s',(token_hash(token),)); c.close()
            except Exception as ex: print('Session logout error:',repr(ex))
    connected_accounts.pop(ws,None)
    await send(ws,{'type':'logout_result','success':True})

async def online_players(ws):
    me=connected_accounts.get(ws,{}).get('player_id')
    players={}
    for client,acct in list(connected_accounts.items()):
        pid=acct.get('player_id')
        if not pid or pid==me: continue
        in_game=False
        for r in rooms.values():
            if any(p.get('player_id')==pid and not r.get('game_over') for p in r['players'].values()): in_game=True; break
        players[pid]={'player_id':pid,'username':acct.get('username','Joueur'),'in_game':in_game}
    await send(ws,{'type':'online_players','players':list(players.values())})

invitations={}
async def invite_player(ws, target_id, duration, size):
    acct=connected_accounts.get(ws)
    if active_room_for(ws): return await send(ws,{'type':'invite_result','success':False,'message':'Fini oswa kite match ou ye a anvan ou envite yon lòt jwè.'})
    if not acct: return await send(ws,{'type':'invite_result','success':False,'message':'Connecte-toi pour inviter un joueur.'})
    try: target_id=int(target_id); duration=max(1,min(30,int(duration))); size=max(13,min(20,int(size)))
    except: return await send(ws,{'type':'invite_result','success':False,'message':'Paramètres de défi invalides.'})
    now=time.monotonic()
    for old_id,old_inv in list(invitations.items()):
        if now-old_inv.get('created',0)>INVITATION_TTL_SECONDS: invitations.pop(old_id,None)
    # Si menm kont lan gen plizyè koneksyon (plizyè onglet/navigatè),
    # voye envitasyon an bay dènye WebSocket ki konekte a, pa premye ansyen an.
    target_ws=None
    for client,a in list(connected_accounts.items()):
        if a.get('player_id')==target_id and client is not ws:
            target_ws=client
    if not target_ws: return await send(ws,{'type':'invite_result','success':False,'message':'Ce joueur n’est plus connecté.'})
    for r in rooms.values():
        if any(p.get('player_id')==target_id and not r.get('game_over') for p in r['players'].values()):
            return await send(ws,{'type':'invite_result','success':False,'message':'Ce joueur est déjà en partie.'})
    iid=secrets.token_urlsafe(12)
    invitations[iid]={'from_ws':ws,'to_ws':target_ws,'from':acct,'to_id':target_id,'duration':duration*60,'size':size,'created':time.monotonic()}
    await send(target_ws,{'type':'game_invite','invitation_id':iid,'from_username':acct.get('username'),'duration_minutes':duration,'board_size':size})
    await send(ws,{'type':'invite_result','success':True,'message':'Invitation envoyée.'})

async def invite_response(ws, invitation_id, accepted):
    inv=invitations.pop(str(invitation_id or ''),None)
    if not inv or inv.get('to_ws') is not ws:
        return await send(ws,{'type':'invite_result','success':False,'message':'Invitation expirée ou invalide.'})
    if time.monotonic()-inv.get('created',0)>INVITATION_TTL_SECONDS:
        await send(inv.get('from_ws'),{'type':'invite_result','success':False,'message':'Envitasyon an ekspire.'})
        return await send(ws,{'type':'invite_result','success':False,'message':'Envitasyon an ekspire.'})
    inviter=inv['from_ws']; invitee=ws
    if not accepted:
        await send(inviter,{'type':'invite_result','success':True,'message':username(ws,'Adversaire')+' a refusé le match.'})
        return await send(ws,{'type':'invite_result','success':True,'message':'Invitation refusée.'})
    if inviter not in connected_accounts or invitee not in connected_accounts:
        return await send(ws,{'type':'invite_result','success':False,'message':'Un joueur s’est déconnecté.'})
    if active_room_for(inviter) or active_room_for(invitee):
        await send(inviter,{'type':'invite_result','success':False,'message':'Youn nan jwè yo deja nan yon match.'})
        return await send(invitee,{'type':'invite_result','success':False,'message':'Youn nan jwè yo deja nan yon match.'})
    c=code(); r=room_base(inv['size'],inv['duration']); rooms[c]=r
    p1=connected_accounts[inviter]; p2=connected_accounts[invitee]; t1=session(); t2=session()
    r['players']={1:{'socket':inviter,'connected':True,'session_token':t1,'username':p1['username'],'player_id':p1['player_id']},2:{'socket':invitee,'connected':True,'session_token':t2,'username':p2['username'],'player_id':p2['player_id']}}
    await send(inviter,{'type':'direct_match','room':c,'player':1,'session_token':t1,'message':'🎮 Invitation acceptée !'}); await send(invitee,{'type':'direct_match','room':c,'player':2,'session_token':t2,'message':'🎮 Invitation acceptée !'})
    await broadcast(r)

async def leave_match(ws, c):
    c=str(c or '').upper().strip()
    if c not in rooms: return await send(ws,{'type':'leave_match_result','success':True})
    r=rooms[c]; n=find(r,ws)
    if n is None: return await send(ws,{'type':'leave_match_result','success':True})
    if not r.get('game_over') and len(r.get('players',{}))==2:
        other=2 if n==1 else 1
        r['game_over']=True; r['winner']=other; r['draw']=False; r['abandonment']=True
        r['winning_line']=None; r['rematch_request']=None; r['undo_request']=None
        r['black_score']+=int(other==1); r['red_score']+=int(other==2)
        await record_result(r)
        await broadcast(r)
    await send(ws,{'type':'leave_match_result','success':True,'room':c})

async def undo_request(ws, c):
    c=str(c or '').upper().strip()
    if c not in rooms: return
    r=rooms[c]; n=find(r,ws)
    if n is None or r['game_over'] or r.get('undo_request') is not None or not r.get('last_move') or int(r['last_move'].get('player',0))!=n:
        return await send(ws,{'type':'error','message':'Ou pa ka mande rejwe kounye a.'})
    r['undo_request']=n; await broadcast(r)

async def undo_response(ws, c, accepted):
    c=str(c or '').upper().strip()
    if c not in rooms: return
    r=rooms[c]; n=find(r,ws); requester=r.get('undo_request')
    if n is None or requester is None or n==requester: return
    if accepted and r.get('move_history'):
        old=r['move_history'].pop(); r['board']=old['board']; r['turn']=old['turn']; r['last_move']=old['last_move']; r['last_move_was_win']=old['last_move_was_win']; r['winning_line']=old['winning_line']; r['game_over']=old['game_over']; r['winner']=old['winner']; r['draw']=old['draw']; r['stats_recorded']=False
    r['undo_request']=None; r['last_timer_update']=time.monotonic(); await broadcast(r)

async def handler(ws):
    try:
        async for raw in ws:
            try:d=json.loads(raw)
            except: await send(ws,{'type':'error','message':'JSON invalid.'});continue
            try:
                t=d.get('type')
                if t=='restore_session':await restore_session(ws,d.get('account_token'))
                elif t=='logout_session':await logout_session(ws,d.get('account_token'))
                elif t=='online_players':await online_players(ws)
                elif t=='invite_player':await invite_player(ws,d.get('target_player_id'),d.get('duration_minutes',5),d.get('board_size',15))
                elif t=='invite_response':await invite_response(ws,d.get('invitation_id'),bool(d.get('accepted',False)))
                elif t=='leave_match':await leave_match(ws,d.get('room'))
                elif t=='undo_request':await undo_request(ws,d.get('room'))
                elif t=='undo_response':await undo_response(ws,d.get('room'),bool(d.get('accepted',False)))
                elif t=='register':await register(ws,d.get('username'),d.get('email'),d.get('password'),d.get('password_confirmation'))
                elif t=='login':await login(ws,d.get('login'),d.get('password'))
                elif t=='create':
                    try: duration_seconds=max(60,min(1800,int(d.get('duration_minutes',10) or 10)*60))
                    except (TypeError,ValueError): duration_seconds=START_TIME
                    try: requested_size=max(13,min(20,int(d.get('board_size',BOARD_SIZE) or BOARD_SIZE)))
                    except (TypeError,ValueError): requested_size=BOARD_SIZE
                    await create(ws,requested_size,duration_seconds)
                elif t=='join':await join(ws,d.get('room',d.get('room_code',d.get('code'))))
                elif t in ('watch','spectate'):await watch(ws,d.get('room',d.get('room_code',d.get('code'))))
                elif t in ('stop_watching','leave_spectator'):remove_spec(ws);await send(ws,{'type':'watch_stopped'})
                elif t=='live_matches':await live(ws)
                elif t=='rooms_list':await rooms_list(ws)
                elif t=='chat':await chat(ws,d.get('room'),d.get('message',d.get('text')))
                elif t=='voice_join':await voice_join(ws,d.get('room'))
                elif t=='voice_signal':await voice_signal(ws,d.get('room'),d.get('to'),d.get('signal_type'),d.get('payload'))
                elif t=='find_match':await find_match(ws)
                elif t=='cancel_match':await cancel(ws)
                elif t=='reconnect':await reconnect(ws,d.get('room'),d.get('player'),d.get('session_token'))
                elif t=='move':await move(ws,d.get('room'),d.get('row'),d.get('col'))
                elif t=='rematch_request':await rematch_req(ws,d.get('room'))
                elif t=='rematch_response':await rematch_resp(ws,d.get('room'),bool(d.get('accepted',d.get('accept',False))))
                elif t=='reset':await reset(ws,d.get('room'))
                else:await send(ws,{'type':'error','message':'Type de message inconnu.'})
            except Exception as ex:
                print('Mesaj kliyan pa valab:',repr(ex))
                await send(ws,{'type':'error','message':'Mesaj la pa valab. Verifye done yo epi eseye ankò.'})
    except websockets.exceptions.ConnectionClosed:pass
    except Exception as e:print('Erreur client:',repr(e))
    finally:await disconnect(ws)
def health_response(connection, request):
    # Render's health checker may send HEAD/GET to the service URL.
    # A pure WebSocket listener normally expects GET + Upgrade and logs
    # HEAD as a failed WebSocket handshake. Intercept normal HTTP probes here.
    path = request.path.split('?', 1)[0]
    if path in ('/', '/health', '/healthz') and request.headers.get('Upgrade', '').lower() != 'websocket':
        body = b'{\"ok\":true,\"service\":\"MR_Jery_Morpion_Game_Server\",\"websocket\":true}'
        if request.method == 'HEAD':
            body = b''
        return Response(200, 'OK', Headers([('Content-Type','application/json; charset=utf-8'), ('Content-Length', str(len(body))), ('Cache-Control','no-store')]), body)
    return None

async def main():
    print(f'Serveur Gomoku lance sou {HOST}:{PORT}')
    asyncio.create_task(timer_loop())
    async with websockets.serve(
        handler, HOST, PORT,
        process_request=health_response,
        ping_interval=20, ping_timeout=20,
        max_size=1_000_000,
    ):
        print('WebSocket server prêt + HTTP health endpoint /health.')
        await asyncio.Future()
if __name__=='__main__':asyncio.run(main())
