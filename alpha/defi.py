"""Read-only Aave risk monitoring and constant-product AMM opportunity estimates.

Real profitable execution requires transaction simulation, pool-specific fees,
real-time state and competitive MEV inclusion. No transaction sender exists here.
"""
from decimal import Decimal
from .common import D, Observation, eth_call, jsonrpc_call, utc_now, validate_address, words

ETH_POOL='0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2'
SELECTORS={'getUserAccountData':'0xbf92857c','getReserves':'0x0902f1ac',
           'token0':'0x0dfe1681','token1':'0xd21220a7'}


def chain_block(rpc,chain_id=1):
    chain=int(jsonrpc_call(rpc,'eth_chainId',[]),16)
    if chain!=int(chain_id):raise ValueError(f'RPC chain mismatch {chain} != {chain_id}')
    block=jsonrpc_call(rpc,'eth_blockNumber',[])
    return block


def account_data(rpc,pool,user,block):
    validate_address(user)
    data=eth_call(rpc,pool,SELECTORS['getUserAccountData']+user[2:].lower().rjust(64,'0'),block)
    collateral,debt,available,threshold,ltv,hf=words(data,6)
    return {'user':user,'health_factor':D(hf)/D(10**18),
            'collateral_base_units':collateral,'debt_base_units':debt,
            'ltv_bps':ltv,'liquidation_threshold_bps':threshold}


def scan_aave(rpc,users,pool=ETH_POOL,chain_id=1):
    block=chain_block(rpc,chain_id)
    observations=[]
    for user in users:
        x=account_data(rpc,pool,user,block)
        status=('potential_liquidation_health_only' if x['debt_base_units']>0 and x['health_factor']<1
                else 'watch_below_1_05' if x['debt_base_units']>0 and x['health_factor']<D('1.05')
                else 'healthy_or_no_debt')
        observations.append(Observation('aave_liquidations',user,utc_now(),status,None,
          {**{k:str(v) for k,v in x.items()},'chain_id':chain_id,'block':block,
           'profit_estimate_unavailable':True,'reserve_debt_collateral_and_bonus_not_queried':True,
           'not_executable':True},rpc.split('?')[0]))
    return observations


def pool_state(rpc,address,block):
    validate_address(address)
    t0=int(eth_call(rpc,address,SELECTORS['token0'],block),16)
    t1=int(eth_call(rpc,address,SELECTORS['token1'],block),16)
    r0,r1,_=words(eth_call(rpc,address,SELECTORS['getReserves'],block),3)
    a0='0x'+format(t0,'040x');a1='0x'+format(t1,'040x')
    if not r0 or not r1 or a0==a1:raise ValueError('empty pool / bad token pair')
    return {'address':address,'token0':a0,'token1':a1,'reserve0':r0,'reserve1':r1,'block':block}


def amm_out(amount,reserve_in,reserve_out,fee_bps):
    if not (0<=fee_bps<10000) or min(amount,reserve_in,reserve_out)<=0:
        raise ValueError('invalid reserves/amount/fee')
    trade=amount*(10000-fee_bps)
    return (trade*reserve_out)//(reserve_in*10000+trade)


def roundtrip(start_amount,first,second,fee_a_bps,fee_b_bps):
    """Start in token0, sell to token1 in first, then back to token0 in second."""
    mid=amm_out(start_amount,first['reserve0'],first['reserve1'],fee_a_bps)
    if not mid:return 0
    return amm_out(mid,second['reserve1'],second['reserve0'],fee_b_bps)


def scan_flash_amm(rpc,pairs,chain_id=1):
    """Pairs are two known V2-compatible pools with same actual token0/token1.

    fee_bps and gas_cost_token0_wei are config assumptions; observations are
    INDICATIVE and explicitly not executable profit, even when positive.
    """
    block=chain_block(rpc,chain_id)
    results=[]
    for pair in pairs:
        p=pool_state(rpc,pair['pool_a'],block)
        q=pool_state(rpc,pair['pool_b'],block)
        if (p['token0'],p['token1'])!=(q['token0'],q['token1']):
            raise ValueError(f'mismatched onchain assets for {pair.get("name","unnamed")}')
        amount=int(pair['amount_token0_base_units'])
        premium_bps=int(pair['flash_loan_premium_bps_assumption'])
        cost=int(pair['gas_cost_token0_base_units_assumption'])
        fees=(int(pair['pool_a_fee_bps']),int(pair['pool_b_fee_bps']))
        # round UP premium to avoid optimistic math
        flash_cost=(amount*premium_bps+9999)//10000
        ab=roundtrip(amount,p,q,*fees)-amount-flash_cost-cost
        ba=roundtrip(amount,q,p,fees[1],fees[0])-amount-flash_cost-cost
        best=max(ab,ba); direction='A_to_B' if ab>=ba else 'B_to_A'
        results.append(Observation('flash_amm',pair.get('name','pair'),utc_now(),
              'indicative_positive_not_executable' if best>0 else 'negative_or_zero_margin',None,
              {'chain_id':chain_id,'block':block,'pool_a':p['address'],'pool_b':q['address'],
               'token0':p['token0'],'token1':p['token1'],'start_token0_base_units':amount,
               'best_direction':direction,'indicative_net_token0_base_units':best,
               'a_to_b_net_token0_base_units':ab,'b_to_a_net_token0_base_units':ba,
               'flash_fee_bps_assumed':premium_bps,'gas_token0_base_units_assumed':cost,
               'is_transaction_simulated':False,'pool_fee_config_verified':False,
               'is_executable_quote':False,'MEV_cost_unmodeled':True},rpc.split('?')[0]))
    return results
