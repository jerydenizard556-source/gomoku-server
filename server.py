import asyncio,json,secrets,string,time,os,hashlib,hmac,re
import websockets, psycopg2

HOST='0.0.0.0'
PORT=10000
BOARD_SIZE=20
START_TIME=600

DATABASE_URL=os.environ.get('DATABASE_URL')
db=None

if DATABASE_URL:
    try:
        db=psycopg2.connect(DATABASE_URL)
        db.autocommit=True
        c=db.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS players (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.close()
        print('PostgreSQL database connected.')
    except Exception as e:
        print('Database connection error:',repr(e))
        db=None


def hash_password(p):
    s=secrets.token_bytes(16)
    h=hashlib.pbkdf2_hmac('sha256',p.encode(),s,200000)
    return f'pbkdf2_sha256$200000${s.hex()}${h.hex()}'


def verify_password(p,x):
    try:
        a,it,s,h=x.split('$')
        if a!='pbkdf2_sha256':
            return False
        z=hashlib.pbkdf2_hmac(
            'sha256',
            p.encode(),
            bytes.fromhex(s),
            int(it)
        )
        return hmac.compare_digest(z,bytes.fromhex(h))
    except:
        return False


def valid_username(x):
    return bool(x) and 3<=len(x)<=50 and re.fullmatch(
        r'[A-Za-z0-9_]+',
        x
    ) is not None


def valid_email(x):
    return bool(x) and len(x)<=255 and re.fullmatch(
        r'[^@\s]+@[^@\s]+\.[^@\s]+',
        x
    ) is not None


connected_accounts={}


def set_account(ws,pid,u,e,t):
    connected_accounts[ws]={
        'player_id':pid,
        'username':u,
        'email':e,
        'account_token':t
    }


def username(ws,fallback):
    return connected_accounts.get(ws,{}).get('username',fallback)


async def send(ws,d):
    try:
        await ws.send(json.dumps(d))
    except:
        pass


async def register(ws,u,e,p,pc):
    if db is None:
        return await send(ws,{
            'type':'register_result',
            'success':False,
            'message':'Database pa disponib.'
        })

    u=str(u or '').strip()
    e=str(e or '').strip().lower()
    p=str(p or '')
    pc=str(pc or '')

    if not valid_username(u):
        return await send(ws,{
            'type':'register_result',
            'success':False,
            'message':'Pseudo a dwe genyen 3-50 karaktè epi sèlman lèt, chif oswa _.'
        })

    if not valid_email(e):
        return await send(ws,{
            'type':'register_result',
            'success':False,
            'message':'Email la pa valid.'
        })

    if len(p)<8:
        return await send(ws,{
            'type':'register_result',
            'success':False,
            'message':'Password la dwe genyen omwen 8 karaktè.'
        })

    if p!=pc:
        return await send(ws,{
            'type':'register_result',
            'success':False,
            'message':'Password yo pa menm.'
        })

    try:
        c=db.cursor()

        c.execute(
            'SELECT id FROM players WHERE LOWER(username)=LOWER(%s)',
            (u,)
        )

        if c.fetchone():
            c.close()
            return await send(ws,{
                'type':'register_result',
                'success':False,
                'message':'Pseudo sa deja itilize.'
            })

        c.execute(
            'SELECT id FROM players WHERE LOWER(email)=LOWER(%s)',
            (e,)
        )

        if c.fetchone():
            c.close()
            return await send(ws,{
                'type':'register_result',
                'success':False,
                'message':'Email sa deja itilize.'
            })

        c.execute(
            'INSERT INTO players(username,email,password_hash) VALUES(%s,%s,%s) RETURNING id',
            (u,e,hash_password(p))
        )

        pid=c.fetchone()[0]
        c.close()

        t=secrets.token_urlsafe(32)

        set_account(ws,pid,u,e,t)

        await send(ws,{
            'type':'register_result',
            'success':True,
            'message':'Kont lan kreye avèk siksè.',
            'player_id':pid,
            'username':u,
            'email':e,
            'account_token':t
        })

    except Exception as ex:
        print('Register error:',repr(ex))

        await send(ws,{
            'type':'register_result',
            'success':False,
            'message':'Erè pandan kreyasyon kont lan.'
        })


async def login(ws,l,p):
    if db is None:
        return await send(ws,{
            'type':'login_result',
            'success':False,
            'message':'Database pa disponib.'
        })

    l=str(l or '').strip()
    p=str(p or '')

    if not l or not p:
        return await send(ws,{
            'type':'login_result',
            'success':False,
            'message':'Tanpri ranpli tout chan yo.'
        })

    try:
        c=db.cursor()

        c.execute(
            '''
            SELECT id,username,email,password_hash
            FROM players
            WHERE LOWER(username)=LOWER(%s)
               OR LOWER(email)=LOWER(%s)
            LIMIT 1
            ''',
            (l,l)
        )

        row=c.fetchone()
        c.close()

        if not row or not verify_password(p,row[3]):
            return await send(ws,{
                'type':'login_result',
                'success':False,
                'message':'Pseudo/email oswa password la pa kòrèk.'
            })

        t=secrets.token_urlsafe(32)

        set_account(ws,row[0],row[1],row[2],t)

        await send(ws,{
            'type':'login_result',
            'success':True,
            'message':'Login reyisi.',
            'player_id':row[0],
            'username':row[1],
            'email':row[2],
            'account_token':t
        })

    except Exception as ex:
        print('Login error:',repr(ex))

        await send(ws,{
            'type':'login_result',
            'success':False,
            'message':'Erè pandan login.'
        })


rooms={}
queue=[]


def code():
    while True:
        x=''.join(
            secrets.choice(string.ascii_uppercase+string.digits)
            for _ in range(6)
        )

        if x not in rooms:
            return x


def board():
    return [[0]*BOARD_SIZE for _ in range(BOARD_SIZE)]


def room_base():
    return {
        'board':board(),
        'players':{},
        'spectators':set(),
        'turn':1,
        'starter':1,
        'black_time':START_TIME,
        'red_time':START_TIME,
        'last_timer_update':time.monotonic(),
        'game_over':False,
        'winner':0,
        'draw':False,
        'abandonment':False,
        'black_score':0,
        'red_score':0,
        'game_number':1,
        'last_move':None,
        'last_move_was_win':False,
        'winning_line':None,
        'rematch_request':None,

        # Nouvo fonksyon:
        # Demande rejwe pandan match la
        'undo_request':None
    }


def new_room():
    c=code()
    rooms[c]=room_base()
    return c


def session():
    return secrets.token_urlsafe(32)


def pstate(r,n):
    p=r['players'].get(n,{})

    return {
        'connected':p.get('connected',False),
        'username':p.get('username',f'Joueur {n}'),
        'name':p.get('username',f'Joueur {n}')
    }


def find(r,ws):
    for n,p in r['players'].items():
        if p.get('socket') is ws:
            return n

    return None


def remove_spec(ws):
    for r in rooms.values():
        r['spectators'].discard(ws)


def winline(b,rr,cc,p):
    for dr,dc in (
        (0,1),
        (1,0),
        (1,1),
        (1,-1)
    ):
        line=[(rr,cc)]

        r,c=rr-dr,cc-dc

        while 0<=r<20 and 0<=c<20 and b[r][c]==p:
            line.insert(0,(r,c))
            r-=dr
            c-=dc

        r,c=rr+dr,cc+dc

        while 0<=r<20 and 0<=c<20 and b[r][c]==p:
            line.append((r,c))
            r+=dr
            c+=dc

        if len(line)>=5:
            return line

    return None


def update_timer(r):
    if r['game_over'] or r['rematch_request'] is not None:
        r['last_timer_update']=time.monotonic()
        return

    now=time.monotonic()
    d=max(0,now-r['last_timer_update'])

    r['last_timer_update']=now

    k='black_time' if r['turn']==1 else 'red_time'

    r[k]=max(0,r[k]-d)

    if r[k]<=0:
        r['game_over']=True
        r['winner']=2 if r['turn']==1 else 1
        r['draw']=False
        r['abandonment']=False

        r['black_score']+=r['winner']==1
        r['red_score']+=r['winner']==2


async def state(r):
    update_timer(r)

    return {
        'type':'state',
        'board':r['board'],
        'turn':r['turn'],
        'starter':r['starter'],
        'black_time':r['black_time'],
        'red_time':r['red_time'],
        'game_over':r['game_over'],
        'winner':r['winner'],
        'draw':r['draw'],
        'abandonment':r['abandonment'],
        'black_score':r['black_score'],
        'red_score':r['red_score'],
        'game_number':r['game_number'],
        'last_move':r['last_move'],
        'last_move_was_win':r['last_move_was_win'],
        'winning_line':r['winning_line'],
        'rematch_request':r['rematch_request'],

        # Nouvo:
        'undo_request':r['undo_request'],

        'players':{
            '1':pstate(r,1),
            '2':pstate(r,2)
        },

        'spectator_count':len(r['spectators']),
        'spectators_count':len(r['spectators']),

        'waiting':not(
            r['players'].get(1,{}).get('connected')
            and
            r['players'].get(2,{}).get('connected')
        )
    }


async def broadcast(r):
    s=await state(r)

    for p in r['players'].values():
        if p.get('socket'):
            await send(p['socket'],s)

    for ws in list(r['spectators']):
        await send(ws,s)


async def create(ws):
    c=new_room()
    r=rooms[c]

    t=session()

    r['players'][1]={
        'socket':ws,
        'connected':True,
        'session_token':t,
        'username':username(ws,'Joueur 1')
    }

    await send(ws,{
        'type':'created',
        'room':c,
        'player':1,
        'session_token':t,
        'username':r['players'][1]['username']
    })

    await broadcast(r)


async def join(ws,c):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return await send(ws,{
            'type':'error',
            'message':'Room introuvable.'
        })

    r=rooms[c]

    if 2 in r['players']:
        return await send(ws,{
            'type':'error',
            'message':'Room sa deja gen 2 jwè. Chwazi Spectateur.'
        })

    t=session()

    r['players'][2]={
        'socket':ws,
        'connected':True,
        'session_token':t,
        'username':username(ws,'Joueur 2')
    }

    await send(ws,{
        'type':'joined',
        'room':c,
        'player':2,
        'session_token':t,
        'username':r['players'][2]['username']
    })

    await broadcast(r)


async def find_match(ws):
    remove_spec(ws)

    queue[:]=[
        x for x in queue
        if x is not ws
    ]

    if queue:
        a=queue.pop(0)

        c=code()
        r=room_base()
        rooms[c]=r

        n1=username(a,'Joueur 1')
        n2=username(ws,'Joueur 2')

        t1=session()
        t2=session()

        r['players']={
            1:{
                'socket':a,
                'connected':True,
                'session_token':t1,
                'username':n1
            },
            2:{
                'socket':ws,
                'connected':True,
                'session_token':t2,
                'username':n2
            }
        }

        await send(a,{
            'type':'match_found',
            'room':c,
            'player':1,
            'session_token':t1,
            'username':n1,
            'message':'🎮 Adversaire trouvé ! Le match va commencer.'
        })

        await send(ws,{
            'type':'match_found',
            'room':c,
            'player':2,
            'session_token':t2,
            'username':n2,
            'message':'🎮 Adversaire trouvé ! Le match va commencer.'
        })

        await broadcast(r)

    else:
        queue.append(ws)

        await send(ws,{
            'type':'searching',
            'message':'Ap chèche yon adversè...'
        })


async def cancel(ws):
    queue[:]=[
        x for x in queue
        if x is not ws
    ]

    await send(ws,{
        'type':'match_cancelled'
    })


async def watch(ws,c):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return await send(ws,{
            'type':'watch_error',
            'success':False,
            'message':'Match sa pa egziste.'
        })

    remove_spec(ws)

    r=rooms[c]

    r['spectators'].add(ws)

    await send(ws,{
        'type':'watching',
        'room':c,
        'spectator':True
    })

    await broadcast(r)


async def live(ws):
    out=[]

    for c,r in rooms.items():

        if (
            len(r['players'])==2
            and
            not r['game_over']
            and
            all(
                p.get('connected')
                for p in r['players'].values()
            )
        ):
            out.append({
                'room':c,
                'player1':pstate(r,1)['username'],
                'player2':pstate(r,2)['username'],
                'spectator_count':len(r['spectators']),
                'game_over':r['game_over']
            })

    await send(ws,{
        'type':'live_matches',
        'matches':out
    })


async def reconnect(ws,c,n,t):
    c=str(c or '').upper().strip()

    try:
        n=int(n)
    except:
        return

    if (
        c not in rooms
        or
        n not in rooms[c]['players']
        or
        rooms[c]['players'][n].get('session_token')!=t
    ):
        return await send(ws,{
            'type':'error',
            'message':'Session token invalid.'
        })

    r=rooms[c]

    remove_spec(ws)

    r['players'][n]['socket']=ws
    r['players'][n]['connected']=True

    await send(ws,{
        'type':'reconnected',
        'room':c,
        'player':n,
        'session_token':t,
        'username':r['players'][n]['username']
    })

    await broadcast(r)


async def move(ws,c,rr,cc):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return

    r=rooms[c]
    n=find(r,ws)

    if n is None:
        return await send(ws,{
            'type':'error',
            'message':'Spectatè yo pa kapab jwe.'
        })

    if (
        r['game_over']
        or
        r['rematch_request'] is not None
        or
        r['undo_request'] is not None
        or
        n!=r['turn']
    ):
        return

    try:
        rr=int(rr)
        cc=int(cc)
    except:
        return

    if not(
        0<=rr<20
        and
        0<=cc<20
    ):
        return

    if r['board'][rr][cc]:
        return

    update_timer(r)

    if r['game_over']:
        return await broadcast(r)

    r['board'][rr][cc]=n

    r['last_move']={
        'row':rr,
        'col':cc,
        'player':n
    }

    r['last_move_was_win']=False
    r['winning_line']=None

    wl=winline(
        r['board'],
        rr,
        cc,
        n
    )

    if wl:
        r['game_over']=True
        r['winner']=n

        r['winning_line']=[
            {
                'row':a,
                'col':b
            }
            for a,b in wl
        ]

        r['last_move_was_win']=True

        r['black_score']+=n==1
        r['red_score']+=n==2

    elif all(
        all(x for x in row)
        for row in r['board']
    ):
        r['game_over']=True
        r['draw']=True
        r['winner']=0

    else:
        r['turn']=2 if n==1 else 1

    await broadcast(r)


# ============================================================
# DEMANDE REJWE PANDAN MATCH LA
# ============================================================

async def undo_request(ws,c):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return

    r=rooms[c]
    n=find(r,ws)

    if n is None:
        return

    # Pa kapab mande rejwe si match la fini
    if r['game_over']:
        return

    # Pa kapab gen 2 demann an menm tan
    if r['undo_request'] is not None:
        return

    # Fòk gen yon dènye pion
    if r['last_move'] is None:
        return

    # Se jwè ki fè dènye pion an sèlman
    # ki kapab mande rejwe
    if r['last_move'].get('player') != n:
        return

    r['undo_request']=n
    r['last_timer_update']=time.monotonic()

    await broadcast(r)


async def undo_response(ws,c,accepted):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return

    r=rooms[c]
    n=find(r,ws)
    q=r['undo_request']

    if n is None or q is None:
        return

    # Moun ki mande a pa kapab reponn pwòp demann li
    if n==q:
        return

    if accepted:
        last=r['last_move']

        if last is not None:
            rr=int(last['row'])
            cc=int(last['col'])

            if (
                0<=rr<BOARD_SIZE
                and
                0<=cc<BOARD_SIZE
            ):
                # Retire dènye pion an
                r['board'][rr][cc]=0

            # Jwè ki te fè dènye pion an
            # reprann tou pa li
            r['turn']=q

            # Netwaye dènye kou a
            r['last_move']=None
            r['last_move_was_win']=False
            r['winning_line']=None

            # Match la kontinye
            r['game_over']=False
            r['winner']=0
            r['draw']=False
            r['abandonment']=False

    # Demann lan fini kit li aksepte,
    # kit li refize
    r['undo_request']=None
    r['last_timer_update']=time.monotonic()

    await broadcast(r)


# ============================================================
# REMATCH APRE MATCH LA
# ============================================================

async def rematch_req(ws,c):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return

    r=rooms[c]
    n=find(r,ws)

    if (
        n is None
        or
        not r['game_over']
        or
        r['rematch_request'] is not None
    ):
        return

    # Se jwè ki pèdi a ki mande rematch,
    # sof si match la fini egalite
    if not r['draw'] and r['winner']==n:
        return

    r['rematch_request']=n
    r['last_timer_update']=time.monotonic()

    await broadcast(r)


async def rematch_resp(ws,c,accepted):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return

    r=rooms[c]
    n=find(r,ws)
    q=r['rematch_request']

    if n is None or q is None or n==q:
        return

    if accepted:

        # Chanje starter la
        r['starter']=2 if r['starter']==1 else 1

        r['turn']=r['starter']

        r['game_number']+=1

        r['board']=board()

        r['black_time']=START_TIME
        r['red_time']=START_TIME

        r['game_over']=False
        r['winner']=0
        r['draw']=False
        r['abandonment']=False

        r['last_move']=None
        r['last_move_was_win']=False
        r['winning_line']=None

        # Nouvo jwèt la pa gen undo request
        r['undo_request']=None

    r['rematch_request']=None
    r['last_timer_update']=time.monotonic()

    await broadcast(r)


async def reset(ws,c):
    c=str(c or '').upper().strip()

    if c not in rooms:
        return

    r=rooms[c]
    n=find(r,ws)

    if n is None or not r['game_over']:
        return

    r['starter']=2 if r['starter']==1 else 1
    r['turn']=r['starter']

    r['game_number']+=1

    r['board']=board()

    r['black_time']=START_TIME
    r['red_time']=START_TIME

    r['game_over']=False
    r['winner']=0
    r['draw']=False
    r['abandonment']=False

    r['last_move']=None
    r['last_move_was_win']=False
    r['winning_line']=None

    r['rematch_request']=None
    r['undo_request']=None

    r['last_timer_update']=time.monotonic()

    await broadcast(r)


async def disconnect(ws):
    queue[:]=[
        x for x in queue
        if x is not ws
    ]

    connected_accounts.pop(ws,None)

    remove_spec(ws)

    for c,r in list(rooms.items()):

        n=find(r,ws)

        if n is not None:

            r['players'][n]['connected']=False
            r['players'][n]['socket']=None

            if (
                not r['game_over']
                and
                len(r['players'])==2
                and
                any(
                    p.get('connected')
                    for p in r['players'].values()
                )
            ):

                other=2 if n==1 else 1

                r['game_over']=True
                r['winner']=other
                r['draw']=False
                r['abandonment']=True
                r['winning_line']=None
                r['rematch_request']=None
                r['undo_request']=None

                r['black_score']+=other==1
                r['red_score']+=other==2

            await broadcast(r)

            return


async def timer_loop():
    while True:

        await asyncio.sleep(1)

        for r in list(rooms.values()):

            if (
                r['game_over']
                or
                r['rematch_request'] is not None
                or
                r['undo_request'] is not None
            ):
                continue

            b=r['black_time']
            red=r['red_time']

            update_timer(r)

            if (
                b!=r['black_time']
                or
                red!=r['red_time']
                or
                r['game_over']
            ):
                await broadcast(r)


async def handler(ws):

    try:

        async for raw in ws:

            try:
                d=json.loads(raw)

            except:
                await send(ws,{
                    'type':'error',
                    'message':'JSON invalid.'
                })
                continue

            t=d.get('type')

            if t=='register':
                await register(
                    ws,
                    d.get('username'),
                    d.get('email'),
                    d.get('password'),
                    d.get('password_confirmation')
                )

            elif t=='login':
                await login(
                    ws,
                    d.get('login'),
                    d.get('password')
                )

            elif t=='create':
                await create(ws)

            elif t=='join':
                await join(
                    ws,
                    d.get(
                        'room',
                        d.get(
                            'room_code',
                            d.get('code')
                        )
                    )
                )

            elif t in ('watch','spectate'):
                await watch(
                    ws,
                    d.get(
                        'room',
                        d.get(
                            'room_code',
                            d.get('code')
                        )
                    )
                )

            elif t in (
                'stop_watching',
                'leave_spectator'
            ):
                remove_spec(ws)

                await send(ws,{
                    'type':'watch_stopped'
                })

            elif t=='live_matches':
                await live(ws)

            elif t=='find_match':
                await find_match(ws)

            elif t=='cancel_match':
                await cancel(ws)

            elif t=='reconnect':
                await reconnect(
                    ws,
                    d.get('room'),
                    d.get('player'),
                    d.get('session_token')
                )

            elif t=='move':
                await move(
                    ws,
                    d.get('room'),
                    d.get('row'),
                    d.get('col')
                )

            # NOUVO: Demande rejwe
            elif t=='undo_request':
                await undo_request(
                    ws,
                    d.get('room')
                )

            # NOUVO: Repons Demande rejwe
            elif t=='undo_response':
                await undo_response(
                    ws,
                    d.get('room'),
                    bool(
                        d.get(
                            'accepted',
                            d.get('accept',False)
                        )
                    )
                )

            elif t=='rematch_request':
                await rematch_req(
                    ws,
                    d.get('room')
                )

            elif t=='rematch_response':
                await rematch_resp(
                    ws,
                    d.get('room'),
                    bool(
                        d.get(
                            'accepted',
                            d.get('accept',False)
                        )
                    )
                )

            elif t=='reset':
                await reset(
                    ws,
                    d.get('room')
                )

            else:
                await send(ws,{
                    'type':'error',
                    'message':'Type de message inconnu.'
                })

    except websockets.exceptions.ConnectionClosed:
        pass

    except Exception as e:
        print('Erreur client:',repr(e))

    finally:
        await disconnect(ws)


async def main():

    print(
        f'Serveur Gomoku lancé sur {HOST}:{PORT}'
    )

    asyncio.create_task(timer_loop())

    async with websockets.serve(
        handler,
        HOST,
        PORT,
        ping_interval=20,
        ping_timeout=20
    ):

        print('WebSocket server prêt.')

        await asyncio.Future()


if __name__=='__main__':
    asyncio.run(main())
