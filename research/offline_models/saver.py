"""Synthetic saver-backend transition through the existing Engine journal.

No firmware bytes, mounts, service, package or supported profile are introduced.
"""
import copy
import json
from xml.etree import ElementTree as ET
from tvsetup.common import Refused, sha
from tvsetup.planner import Action, Plan

KEY='/fixture/backend'


def patch_cache(cache, first_unit, expected_hash):
    if sha(cache)!=expected_hash or len(cache)<209 or len(first_unit)!=209:
        raise Refused('Exact synthetic cache admission required')
    return first_unit+cache[209:]


def selector_app(selector):
    if len(selector)>4096 or b'<!' in selector:raise Refused('Invalid synthetic selector')
    try:root=ET.fromstring(selector)
    except ET.ParseError:raise Refused('Malformed selector') from None
    if root.tag!='ContentList' or len(root)!=1 or root[0].tag!='App' or root[0].attrib!={'id':'FixtureSaver.App'}:
        raise Refused('Unexpected synthetic app contract')
    return root[0].get('id')


def fingerprint(state):return sha(json.dumps(state,sort_keys=True).encode())

class BackendDriver:
    def __init__(self,state,selector):
        self.state=copy.deepcopy(state);self.selector=selector;self.failure=None;self.before=None

    def plan(self, backend, *, experimental=False):
        if not experimental or backend not in ('native','web','stock'):raise Refused('Offline experiment must be explicit')
        s=self.state
        if s['namespace']!='fixture-init' or not s['diagnostic_ok']:raise Refused('Namespace/diagnostic admission failed')
        if len(s['mounts'])>1 or any(m['owner']!='fixture-couchroot' or m['backend']!=s['backend'] or m['readonly'] is not True for m in s['mounts']):
            raise Refused('Unknown, multiple or partial overlays')
        if (s['backend']=='stock') != (not s['mounts']):raise Refused('Inconsistent backend')
        selector_app(self.selector)
        if backend=='web' and s['app']!='fixture-signed-and-present':raise Refused('App contract missing')
        desired=copy.deepcopy(s);desired['backend']=backend
        desired['mounts']=[] if backend=='stock' else [dict(owner='fixture-couchroot',backend=backend,readonly=True)]
        return Plan('s90d',actions=[Action('backend','screensaver','file',fingerprint(s),fingerprint(desired),dict(path=KEY,desired=desired))])

    def snapshot(self):return dict(files={KEY:fingerprint(self.state)},model=copy.deepcopy(self.state))
    def prepare(self,action):return {}
    def backup(self,action,info,before):return dict(original=copy.deepcopy(before['model']))
    def verify(self,action,before,after):
        if after['files'][KEY]!=action.after:raise Refused('Backend readback failed')
        for key in ('cache_suffix','splash','telemetry'):
            if before['model'][key]!=after['model'][key]:raise Refused('Shared helper preservation failed')

    def execute(self,action,info,before):
        self.before=copy.deepcopy(info['original'])
        if self.state!=self.before:raise Refused('Concurrent state drift')
        # No unknown overlay is ever removed. Model a serialized switch.
        if self.failure=='unmount':raise Refused('Owned unmount failed')
        self.state['mounts']=[];self.state['backend']='stock'
        if self.failure=='after_unmount':raise InterruptedError('interrupted switch')
        wanted=action.options['desired']
        if wanted['backend']=='stock':return
        self.state['mounts']=[dict(owner='fixture-couchroot',backend=wanted['backend'],readonly=False)]
        if self.failure=='after_mount':raise InterruptedError('interrupted remount')
        if self.failure in ('remount','remount_and_unwind'):
            if self.failure=='remount':self.state=copy.deepcopy(self.before)
            raise Refused('Recovery required' if self.failure=='remount_and_unwind' else 'Remount failed; prior state restored')
        self.state=copy.deepcopy(wanted)
        if self.failure=='after_commit':raise InterruptedError('lost verification reply')

    def rollback(self,action,info,state):
        if self.state!=state['model']:raise Refused('Concurrent rollback drift')
        original=info['original'];wanted=action.options['desired']
        # Guard every possible owned intermediate state, not merely its name.
        allowed=[original,wanted]
        stock=copy.deepcopy(original);stock.update(backend='stock',mounts=[]);allowed.append(stock)
        partial=copy.deepcopy(stock);partial['mounts']=[dict(owner='fixture-couchroot',backend=wanted['backend'],readonly=False)];allowed.append(partial)
        if self.state not in allowed:raise Refused('Foreign/drifted overlay; retain recovery checkpoint')
        if self.failure=='rollback_unmount':raise Refused('Recovery required: owned unmount failed')
        self.state=copy.deepcopy(original)
