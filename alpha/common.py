import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

D = lambda x: Decimal(str(x))
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def validate_address(addr):
    if not isinstance(addr, str) or not ADDRESS.fullmatch(addr):
        raise ValueError(f'invalid Ethereum address: {addr!r}')
    return addr


def request_json(url, *, params=None, timeout=10, retries=2):
    """GET only: no authentication, orders, transactions or cookie/session usage."""
    if not url.startswith('https://'):
        raise ValueError('only https public endpoints allowed')
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'AutomatedAlpha-Research/0.1', 'Accept':'application/json'}, method='GET')
    for attempt in range(retries+1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise ValueError('response exceeds safety cap')
                return json.loads(data)
        except urllib.error.HTTPError as ex:
            if ex.code not in (429,500,502,503,504) or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(0.4 * (2**attempt))


def jsonrpc_call(url, method, params, timeout=10):
    """JSON-RPC allowlist makes onchain scans read-only by construction."""
    if method not in ('eth_call', 'eth_blockNumber', 'eth_chainId'):
        raise ValueError('write or unsupported JSON-RPC method rejected')
    if not url.startswith('https://'):
        raise ValueError('RPC must use https')
    body=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
    req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json','User-Agent':'AutomatedAlpha-Research/0.1'},method='POST')
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        obj=json.loads(resp.read(2_000_000))
    if 'error' in obj:
        raise RuntimeError(f'RPC failure: {obj["error"]}')
    if not isinstance(obj.get('result'),str) or not obj['result'].startswith('0x'):
        raise ValueError('RPC result missing hex')
    return obj['result']


def eth_call(rpc,contract,data,block='latest'):
    validate_address(contract)
    return jsonrpc_call(rpc,'eth_call',[{'to':contract,'data':data},block])


def words(payload,count):
    if not payload.startswith('0x') or len(payload[2:]) < 64*count:
        raise ValueError(f'bad ABI word response (expected {count} words)')
    return [int(payload[2+i*64:2+(i+1)*64],16) for i in range(count)]


@dataclass(frozen=True)
class Observation:
    engine: str
    key: str
    timestamp: str
    classification: str
    estimated_net_usd: str | None
    details: dict
    source: str


def write_observations(path, observations):
    """Append-only; no external writes, trading or API submissions."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:
        for observation in observations:
            f.write(json.dumps(asdict(observation),sort_keys=True,default=str)+'\n')
    return len(observations)
