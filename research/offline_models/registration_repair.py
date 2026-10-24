"""Offline CAS experiment. No transport, CLI, profile admission or TV DB opener.

The caller supplies a synthetic SQLite connection and a private scratch journal.
Production wiring requires a separate reviewed Engine action and firmware evidence.
"""
from tvsetup.common import Refused, atomic_json, read_json

SERVICE = 'Fixture01.Service'
PACKAGE = 'Fixture01'
SELECT = 'SELECT version,author,component,disabled,onboot,autorestart FROM fixture_service WHERE package=? AND app=?'


def current(db):
    rows=db.execute(SELECT,(PACKAGE,SERVICE)).fetchall()
    if len(rows)!=1: raise Refused('Exactly one synthetic service required')
    row=list(rows[0])
    if row[2:4]!=['svcapp','false'] or any(v not in ('true','false') for v in row[4:]):
        raise Refused('Unknown or intentionally disabled registration')
    return row


def interlock(run, pending, native_transition):
    if native_transition or any(other != run for other in pending):
        raise Refused('Another pending run or native transition')


def begin(db, journal, run, pending=(), native_transition=False):
    interlock(run,pending,native_transition)
    if journal.exists(): raise Refused('Existing intent must be reconciled')
    before=current(db)
    if before[4:]==['true','true']: raise Refused('No repair required')
    intent=dict(schema=1,run=run,phase='prepared',before=before,after=before[:4]+['true','true'])
    atomic_json(journal,intent)
    return intent


def transition(db, journal, *, reverse=False, pending=(), native_transition=False, crash=None):
    intent=read_json(journal)
    if not intent or intent.get('schema')!=1: raise Refused('Missing intent')
    interlock(intent['run'],pending,native_transition)
    old,new=(intent['after'],intent['before']) if reverse else (intent['before'],intent['after'])
    phase='undoing' if reverse else 'applying'
    complete='rolled-back' if reverse else 'applied'
    if intent['phase'] not in (('applied','undoing','rolled-back') if reverse else ('prepared','applying','applied')):
        raise Refused('Invalid transition phase')
    # Reconcile a lost reply before considering any replay. Identity is part of
    # each compare, including recovery. This never clears a native handoff fence.
    db.execute('BEGIN IMMEDIATE')
    try:
        found=current(db)
        if found==new and intent['phase'] in (phase,complete):
            db.rollback()
            intent['phase']=complete;atomic_json(journal,intent);return
        if found!=old or intent['phase']==complete: raise Refused('Concurrent identity or value drift')
        intent['phase']=phase;atomic_json(journal,intent)
        if crash=='before': raise InterruptedError('before SQL')
        cursor=db.execute('UPDATE fixture_service SET onboot=?,autorestart=? WHERE package=? AND app=? AND version=? AND author=? AND component=? AND disabled=? AND onboot=? AND autorestart=?',
            (*new[4:],PACKAGE,SERVICE,*old))
        if cursor.rowcount!=1: raise Refused('CAS did not update exactly one row')
        if crash=='before_commit': raise InterruptedError('before commit')
        db.commit()
    except BaseException:
        db.rollback();raise
    if crash=='after_commit': raise InterruptedError('lost commit reply')
    intent['phase']=complete;atomic_json(journal,intent)
