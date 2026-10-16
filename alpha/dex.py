"""Bounded, read-only Uniswap V2-compatible factory discovery across public EVM RPCs.

Factory lookup + pool states use the SAME chain block; reserves include trade impact.
This is NOT an executable flash loan or transaction simulation. No private keys.
"""
from decimal import Decimal
from .common import D, Observation, eth_call, jsonrpc_call, utc_now, validate_address, words
from .defi import chain_block, pool_state, roundtrip

GET_PAIR = '0xe6a43905'  # getPair(address,address)
DECIMALS = '0x313ce567' # ERC20 decimals()
ZERO = '0x' + '0'*40


def encode_address(address):
    return validate_address(address)[2:].lower().rjust(64, '0')


def factory_pool(rpc, factory, token_a, token_b, block):
    validate_address(factory)
    if token_a.lower() == token_b.lower():
        raise ValueError('must compare distinct tokens')
    payload = eth_call(rpc, factory, GET_PAIR+encode_address(token_a)+encode_address(token_b), block)
    addresses = words(payload, 1)
    addr = '0x'+f'{addresses[0]:040x}'
    return None if addr.lower() == ZERO else addr


def token_decimals(rpc, token, block):
    decimals = words(eth_call(rpc, token, DECIMALS, block), 1)[0]
    if decimals > 36:
        raise ValueError('unsupported token decimals')
    return decimals


def scan_factories(rpc, chain_id, factories, tokens, sizes, *,
                   gas_cost_token0_base_units=0, flash_premium_bps=5,
                   fee_bps=30, max_pairs=5):
    """Discover pools from authorized factories for manually named token pairs.

    Output denominated in token0 base units, with no unsupported USD conversion.
    Fees and gas values are explicit research ASSUMPTIONS, not verified execution.
    """
    if not (2 <= len(factories) <= 4) or not (1 <= len(tokens) <= max_pairs <= 8):
        raise ValueError('invalid bounded discovery configuration')
    if len({f.lower() for f in factories}) != len(factories):
        raise ValueError('duplicate factories')
    if not 1 <= len(sizes) <= 5 or any(not isinstance(x, int) or x<=0 for x in sizes):
        raise ValueError('invalid trade sizes')
    if not 0 <= flash_premium_bps < 1000 or not 0 <= fee_bps < 1000 or gas_cost_token0_base_units < 0:
        raise ValueError('invalid fee assumptions')
    for f in factories: validate_address(f)
    block = chain_block(rpc, chain_id)
    records=[]; errors={}; pool_cache={}; decimals_cache={}
    for pair in tokens:
        token_a,token_b = pair['token_a'], pair['token_b']
        name=pair.get('name', token_a[:8]+'-'+token_b[:8])
        try:
            validate_address(token_a);validate_address(token_b)
            if token_a.lower()==token_b.lower(): raise ValueError('same asset')
            pool_addresses=[]
            for factory in factories:
                pool=factory_pool(rpc,factory,token_a,token_b,block)
                if pool and pool.lower() not in {p.lower() for p in pool_addresses}:
                    pool_addresses.append(pool)
            if len(pool_addresses)<2:
                records.append(Observation('dex_discovery',str(chain_id)+':'+name,utc_now(),
                    'fewer_than_two_pools',None,{'chain_id':chain_id,'block':block,
                    'pools_found':len(pool_addresses),'no_executable_opportunity':True},'chain:'+str(chain_id)))
                continue
            states=[]
            for pool in pool_addresses:
                if pool.lower() not in pool_cache:
                    pool_cache[pool.lower()]=pool_state(rpc,pool,block)
                states.append(pool_cache[pool.lower()])
            if states[0]['token0'] not in decimals_cache:
                decimals_cache[states[0]['token0']]=token_decimals(rpc,states[0]['token0'],block)
            decimals0=decimals_cache[states[0]['token0']]
            token_set={token_a.lower(),token_b.lower()}
            for state in states:
                if {state['token0'].lower(),state['token1'].lower()}!=token_set:
                    raise ValueError('factory pair did not return requested onchain tokens')
                if (state['token0'],state['token1']) != (states[0]['token0'],states[0]['token1']):
                    raise ValueError('pool token ordering inconsistent')
            best = None
            from itertools import combinations
            for p,q in combinations(states,2):
                for amount in sizes:
                    cost = (amount*flash_premium_bps+9999)//10000 + gas_cost_token0_base_units
                    x=roundtrip(amount,p,q,fee_bps,fee_bps)-amount-cost
                    y=roundtrip(amount,q,p,fee_bps,fee_bps)-amount-cost
                    for label,net in (('A_to_B',x),('B_to_A',y)):
                        if best is None or net>best['net_base_units']:
                            best={'net_base_units':net,'size_base_units':amount,
                                  'direction':label,'pools':[p['address'],q['address']]}
            assert best is not None
            records.append(Observation('dex_discovery',str(chain_id)+':'+name,utc_now(),
                'indicative_positive_unverified' if best['net_base_units']>0 else 'no_positive_margin',None,
                {'chain_id':chain_id,'block':block,'token0':states[0]['token0'],
                 'token0_decimals':decimals0,'token1':states[0]['token1'],
                 'pool_count':len(states),'best':best,'fee_bps_per_swap_assumed':fee_bps,
                 'flash_premium_bps_assumed':flash_premium_bps,
                 'gas_cost_token0_base_units_assumed':gas_cost_token0_base_units,
                 'reserve_price_impact_modeled':True,'transaction_simulated':False,
                 'pool_fees_verified':False,'net_usd_unavailable':True,
                 'MEV_and_inclusion_unmodeled':True,'not_executable':True},'chain:'+str(chain_id)))
        except Exception as ex:
            errors[name]=type(ex).__name__+': '+str(ex)
    records.append(Observation('dex_discovery',str(chain_id)+':heartbeat',utc_now(),
        'dex_heartbeat',None,{'chain_id':chain_id,'block':block,'configured_pairs':len(tokens),
        'errors':len(errors),'pool_calls_bounded':True,'not_executable':True},'chain:'+str(chain_id)))
    return records,errors
