"""Disposable PG: twenty callers share the real API pool under bounded contention."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from app.main import app,lifespan
from app.database import make_engine
from app.identity.service import query

assert os.environ['DB_HOST']=='db' and os.environ.get('COMMUNICATIONS_MODE')=='disabled'
with make_engine().connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'

async def proof():
    async with lifespan(app):
        engine=app.state.engine
        def exercise(engine, expected_success):
            held=threading.Barrier(3);lock=threading.Lock();peak=0
            def use(seconds,*,holder=False):
                nonlocal peak
                with engine.begin() as db:
                    with lock:peak=max(peak,engine.pool.checkedout())
                    if holder:held.wait(timeout=5)
                    db.execute(text('SELECT pg_sleep(:delay)'),dict(delay=seconds))
                return True
            errors=[];done=[]
            with ThreadPoolExecutor(max_workers=22) as workers:
                holders=[workers.submit(use,1.2,holder=True) for _ in range(2)]
                held.wait(timeout=5)
                started=time.monotonic()
                requests=[workers.submit(use,0.3) for _ in range(20)]
                for future in requests:
                    try:done.append(future.result(timeout=10))
                    except PoolTimeout as error:errors.append(type(error).__name__)
                for future in holders:future.result(timeout=10)
            print(json.dumps(dict(completed=len(done),errors=errors,pool_size=engine.pool.size(),
                peak_connections=peak,elapsed_seconds=round(time.monotonic()-started,3),external_calls=0)),flush=True)
            if expected_success:
                assert not errors and len(done)==20,'Concurrent API database work exhausted its pool'
            else:
                assert errors,'Old pool must reproduce checkout exhaustion under the same workload'
            assert peak<=5 and engine.pool.checkedout()==0
        old=make_engine(pool_size=2)
        try:await asyncio.to_thread(exercise,old,False)
        finally:old.dispose()
        await asyncio.to_thread(exercise,engine,True)
asyncio.run(proof())
