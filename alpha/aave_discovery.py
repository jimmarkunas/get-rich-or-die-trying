"""Read-only Aave Borrow log discovery and health-factor monitoring.

Recent Borrow events are NOT a complete index of outstanding debt. A historical
backfill and per-asset risk, collateral, liquidation bonus, swap and MEV model are
required before indicating any executable liquidation profit.
"""
from .common import Observation, jsonrpc_call, utc_now, validate_address
from .defi import chain_block, account_data
from .common import D

# Keccak of Borrow(address,address,address,uint256,uint8,uint256,uint16), verified
# against Ethereum Aave V3 Borrow transactions and the published IPool ABI.
BORROW_TOPIC = '0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0'


def borrower_addresses(logs, pool):
    addrs=[]; seen=set()
    for log in logs:
        if log.get('removed') is True or str(log.get('address','')).lower()!=pool.lower():
            continue
        topics=log.get('topics',[])
        if len(topics)!=4 or str(topics[0]).lower()!=BORROW_TOPIC:
            continue
        topic=topics[2]
        if not isinstance(topic,str) or len(topic)!=66 or not topic.startswith('0x') or topic[2:26]!='0'*24:
            continue
        addr='0x'+topic[-40:].lower()
        try:validate_address(addr)
        except ValueError:continue
        if addr not in seen:
            seen.add(addr);addrs.append(addr)
    return addrs


def scan_borrowers(rpc, pool, chain_id, *, from_block=None, lookback=400,
                   max_users=25, max_logs=2000):
    validate_address(pool)
    if not 1<=lookback<=2000 or not 1<=max_users<=100 or not 1<=max_logs<=3000:
        raise ValueError('unbounded borrower discovery')
    block=chain_block(rpc,chain_id)
    upper=int(block,16)
    lower=max(0,upper-lookback+1) if from_block is None else int(from_block)
    if lower>upper or upper-lower+1>lookback:
        raise ValueError('requested block range exceeds configured limit')
    logs=jsonrpc_call(rpc,'eth_getLogs',[{'address':pool,'fromBlock':hex(lower),
        'toBlock':block,'topics':[BORROW_TOPIC]}])
    if not isinstance(logs,list):raise ValueError('invalid eth_getLogs result')
    if len(logs)>max_logs:raise ValueError('log budget exceeded; shorten range')
    users=borrower_addresses(logs,pool)[:max_users]
    records=[];errors={}
    for user in users:
        try:
            state=account_data(rpc,pool,user,block)
            risk=('health_below_one_profit_unknown' if state['debt_base_units']>0 and state['health_factor']<1
                else 'near_liquidation_profit_unknown' if state['debt_base_units']>0 and state['health_factor']<D('1.05')
                else 'health_ok_or_zero_debt')
            records.append(Observation('aave_discovery',str(chain_id)+':'+user,utc_now(),risk,None,
                {'chain_id':chain_id,'block':block,'borrower_discovery':'recent_pool_borrow_events_only',
                 'health_factor':str(state['health_factor']),
                 'debt_base_units':state['debt_base_units'],
                 'collateral_base_units':state['collateral_base_units'],
                 'bonus_unverified':True,'collateral_debt_reserves_not_expanded':True,
                 'liquidation_profit_unavailable':True,'transaction_simulated':False,
                 'not_executable':True},'chain:'+str(chain_id)))
        except Exception as ex:errors[user]=type(ex).__name__+': '+str(ex)
    records.append(Observation('aave_discovery',str(chain_id)+':heartbeat',utc_now(),'aave_heartbeat',None,
        {'chain_id':chain_id,'block':block,'from_block':hex(lower),'logs':len(logs),
         'unique_recent_borrowers':len(borrower_addresses(logs,pool)),
         'users_sampled':len(users),'sampled_only_not_exhaustive':True,
         'errors':len(errors),'no_profit_estimate':True},'chain:'+str(chain_id)))
    return records,errors
