"""Read-only supplied-evidence projections; no bus calls or source setters."""
import re
from xml.etree import ElementTree as ET
from tvsetup.common import Refused


def display_methods(xml, firmware):
    if not isinstance(xml,str) or len(xml)>65536 or '<!' in xml:
        raise Refused('Bounded introspection XML without declarations required')
    if not isinstance(firmware,str) or not re.fullmatch(r'T-[A-Z0-9]+-(?:[0-9]{4}-)?[0-9]+\.[0-9]+',firmware):
        raise Refused('Exact firmware label required')
    try:root=ET.fromstring(xml)
    except ET.ParseError:raise Refused('Malformed introspection') from None
    if root.tag!='node':raise Refused('Expected introspection node')
    rows=[];seen=set()
    for interface in root.findall('interface'):
        name=interface.get('name','')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+',name):raise Refused('Invalid interface')
        for method in interface.findall('method'):
            method_name=method.get('name','')
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',method_name) or (name,method_name) in seen:raise Refused('Ambiguous method')
            seen.add((name,method_name));args={'in':[],'out':[]}
            for arg in method.findall('arg'):
                direction=arg.get('direction','in');signature=arg.get('type','')
                if direction not in args or not signature or len(signature)>255 or not re.fullmatch(r'[ybnqiuxthdsogva(){}]+',signature):raise Refused('Unrecognized signature capture')
                args[direction].append(signature)
            rows.append(dict(firmware=firmware,interface=name,method=method_name,
                input_signature=''.join(args['in']),output_signature=''.join(args['out']),
                evidence='supplied_introspection',semantic_validation='not_established',write_admitted=False))
            if len(rows)>256:raise Refused('Too many methods')
    return dict(schema=1,methods=rows,live_probe=False,control_admission=False)


def sources(entries):
    """Normalize synthetic public VIDEOSOURCE-shaped records, not native ABI IDs."""
    if not isinstance(entries,list) or len(entries)>64:raise Refused('Bounded source list required')
    result=[];seen=set()
    for row in entries:
        if not isinstance(row,dict):raise Refused('Malformed source')
        kind=row.get('type');number=row.get('number');connected=row.get('connected')
        if kind not in ('TV','HDMI','AV','COMPONENT') or type(number) is not int or not 0<=number<=32 or type(connected) is not bool:
            raise Refused('Unrecognized source evidence')
        if (kind,number) in seen:raise Refused('Duplicate connector')
        seen.add((kind,number))
        result.append(dict(type=kind,number=number,connected=connected,signal='not_observed',handoff='not_verified'))
    return result
