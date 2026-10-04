"""Offline ATR/Bollinger limit-order barrier study and frozen Kelly research.

Every calibration return belongs to this exact execution policy. No broker,
fundamental certification, future probability, or production approval is added.
"""
from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import fmean

if __package__:
    from .atr_trade_plan import build_trade_plan, validate_ohlcv
    from .kelly_position import fractional_kelly, two_point_kelly
else:
    import importlib.util
    from pathlib import Path
    def _sibling(name):
        spec = importlib.util.spec_from_file_location('marketflow_offline_'+name,
                                                     Path(__file__).with_name(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    _plan, _kelly = _sibling('atr_trade_plan'), _sibling('kelly_position')
    build_trade_plan, validate_ohlcv = _plan.build_trade_plan, _plan.validate_ohlcv
    fractional_kelly, two_point_kelly = _kelly.fractional_kelly, _kelly.two_point_kelly


def _number(value, label, *, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int,float)):
        raise ValueError(label+' must be a finite number')
    try:
        result=float(value)
    except (OverflowError,ValueError) as error:
        raise ValueError(label+' must be a finite number') from error
    if not math.isfinite(result) or positive and result<=0 or minimum is not None and result<minimum:
        raise ValueError(label+' is outside the finite allowed range')
    return result


def _day(value,label):
    if not isinstance(value,str):
        raise ValueError(label+' requires YYYY-MM-DD')
    try:
        parsed=date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(label+' requires YYYY-MM-DD') from error
    if parsed.isoformat()!=value:
        raise ValueError(label+' requires canonical YYYY-MM-DD')
    return value


@dataclass(frozen=True)
class ATRKellyConfig:
    train_end: str
    validation_end: str
    atr_period: int=14
    band_period: int=20
    sigma: float=2.
    atr_multiplier: float=2.
    max_stop_fraction: float=.08
    reward_risk: float=2.
    order_expiry_sessions: int=3
    max_holding_sessions: int=20
    fee_bps: float=5.
    slippage_bps: float=5.
    tax_bps: float=20.
    min_train_trades: int=10
    min_validation_trades: int=10
    min_win_rate: float=.60
    min_payoff_ratio: float=1.
    kelly_fraction: float=.5
    cap_limit: float=.20
    vix_index: float | None=None

    def __post_init__(self):
        train, validation=_day(self.train_end,'train_end'),_day(self.validation_end,'validation_end')
        if train>=validation:
            raise ValueError('train_end must precede validation_end')
        for key in ('atr_period','band_period','order_expiry_sessions','max_holding_sessions',
                    'min_train_trades','min_validation_trades'):
            value=getattr(self,key)
            if isinstance(value,bool) or not isinstance(value,int) or value<(2 if key=='band_period' else 1):
                raise ValueError(key+' must be a positive integer')
        for key in ('sigma','atr_multiplier','max_stop_fraction','reward_risk'):
            _number(getattr(self,key),key,positive=True)
        if self.max_stop_fraction>=1:
            raise ValueError('max_stop_fraction must remain below one')
        for key in ('fee_bps','slippage_bps','tax_bps','min_payoff_ratio'):
            _number(getattr(self,key),key,minimum=0.)
        if self.fee_bps+self.slippage_bps+self.tax_bps>=10000:
            raise ValueError('combined exit costs must remain below 10000 bps')
        probability=_number(self.min_win_rate,'min_win_rate',minimum=0.)
        if probability>1:
            raise ValueError('min_win_rate cannot exceed one')
        fractional_kelly(0.,kelly_fraction=self.kelly_fraction,vix_index=self.vix_index,cap_limit=self.cap_limit)


def _phase(signal_date,config):
    return 'train' if signal_date<=config.train_end else 'validation' if signal_date<=config.validation_end else 'test'


def _observations(prices,config):
    if not isinstance(prices,list) or not prices:
        raise ValueError('nonempty OHLCV prices list is required')
    grouped={}
    for source in validate_ohlcv(prices):
        code=source.get('code',source.get('symbol'))
        if not isinstance(code,str) or not code.strip():
            raise ValueError('stock code is required as a nonempty string')
        code=code.strip()
        if source.get('symbol') is not None and source['symbol'].strip()!=code:
            raise ValueError('code and symbol identify different stocks')
        name=source.get('name',code)
        if not isinstance(name,str) or not name.strip():
            raise ValueError('stock name must be a nonempty string')
        name=name.strip()
        group=grouped.setdefault(code,{'name':name,'rows':[],'seen':set()})
        if group['name']!=name:
            raise ValueError('stock name changes inside the same supplied code')
        if source['date'] in group['seen']:
            raise ValueError('duplicate stock date after identity normalization')
        group['seen'].add(source['date'])
        group['rows'].append(dict(code=code,name=name,**{key:source[key] for key in ('date','open','high','low','close','volume')}))
    prepared=[]
    for code,group in sorted(grouped.items()):
        rows=group['rows']
        plans,bars=[],[]
        width=max(config.band_period,config.atr_period+1)
        for index,row in enumerate(rows):
            plan=build_trade_plan(rows[max(0,index-width+1):index+1],atr_period=config.atr_period,
                band_period=config.band_period,sigma=config.sigma,atr_multiplier=config.atr_multiplier,
                max_stop_fraction=config.max_stop_fraction,reward_risk=config.reward_risk)
            plans.append(plan)
            bars.append(dict(row,atr=plan['atr'],lower_band=plan['lower_band'],
                             band_mean=plan['band_mean'],band_std=plan['band_std'],
                             signal=plan['signal'],plan_status=plan['status']))
        prepared.append((code,group['name'],bars,plans))
    return prepared


def _simulate(code,name,bars,plans,config,*,start_index=0):
    signals,trades=[],[]
    order,position=None,None
    entry_cost=(config.fee_bps+config.slippage_bps)/10000
    exit_cost=entry_cost+config.tax_bps/10000

    def finish(index,price,reason,*,ambiguous=False):
        nonlocal position
        trade=position['trade']
        trade.update(status='closed',exit_date=bars[index]['date'],exit_price=price,exit_reason=reason,
                     holding_sessions=index-position['entry_index']+1,ambiguous_bar=ambiguous,
                     gross_return=_number(price/trade['entry_price']-1,'gross trade return'),
                     net_return=_number(price*(1-exit_cost)/(trade['entry_price']*(1+entry_cost))-1,
                                        'net trade return'))
        cutoff=config.train_end if trade['phase']=='train' else config.validation_end if trade['phase']=='validation' else bars[-1]['date']
        trade['calibration_included']=trade['exit_date']<=cutoff
        position=None

    def exits(index,*,intraday_entry=False):
        if position is None or bars[index]['volume']<=0:
            return
        bar,trade=bars[index],position['trade']
        stop,target=trade['stop_price'],trade['target_price']
        # Intraday entry occurred after the open; neither opening gap was a
        # post-entry exit. A falling path can cross entry then stop, conservatively.
        if not intraday_entry and bar['open']<=stop:
            finish(index,bar['open'],'stop_gap')
        elif not intraday_entry and bar['open']>=target:
            finish(index,bar['open'],'target_gap')
        elif bar['low']<=stop:
            finish(index,stop,'stop',ambiguous=bar['high']>=target)
        elif intraday_entry and bar['high']>=target:
            trade['intraday_entry_target_deferred']=True
            if index-position['entry_index']+1>=config.max_holding_sessions:
                finish(index,bar['close'],'time_exit')
        elif bar['high']>=target:
            finish(index,target,'target')
        elif index-position['entry_index']+1>=config.max_holding_sessions:
            finish(index,bar['close'],'time_exit')

    for index in range(start_index,len(bars)):
        bar=bars[index]
        if position is not None:
            exits(index)
        if order is not None:
            # Orders are created only after their signal session closes.
            if index>order['signal_index'] and index<=order['last_index'] and bar['volume']>0:
                price=bar['open'] if bar['open']<=order['signal']['entry_price'] else order['signal']['entry_price'] if bar['low']<=order['signal']['entry_price'] else None
                if price is not None:
                    signal=order['signal']
                    kind='open' if bar['open']<=signal['entry_price'] else 'limit'
                    signal.update(status='filled',entry_date=bar['date'],fill_price=price)
                    trade={'trade_id':code+':'+signal['signal_date']+':'+bar['date'],
                           'code':code,'name':name,'signal_date':signal['signal_date'],
                           'phase':signal['phase'],'entry_date':bar['date'],'entry_price':price,'entry_kind':kind,
                           'stop_price':signal['stop_price'],'target_price':signal['target_price'],
                           'status':'open','exit_date':None,'exit_price':None,'exit_reason':None,
                           'gross_return':None,'net_return':None,'holding_sessions':1,
                           'calibration_included':False,'ambiguous_bar':False,
                           'intraday_entry_target_deferred':False}
                    trades.append(trade)
                    position={'trade':trade,'entry_index':index}
                    order=None
                    exits(index,intraday_entry=kind=='limit')
            if order is not None and index>=order['last_index']:
                order['signal']['status']='expired'
                order=None
        plan=plans[index]
        if plan['signal']:
            expiry_index=index+config.order_expiry_sessions
            signal={key:plan[key] for key in ('signal_date','current_close','entry_price','stop_price','target_price',
                                              'atr','lower_band','loss_fraction','gain_fraction','reward_risk')}
            signal.update(code=code,name=name,phase=_phase(bar['date'],config),entry_date=None,fill_price=None,
                          expiry_date=bars[expiry_index]['date'] if expiry_index<len(bars) else None,
                          expires_after_sessions=config.order_expiry_sessions)
            signal['status']='skipped_open_position' if position is not None else 'skipped_open_order' if order is not None else 'pending'
            signals.append(signal)
            if signal['status']=='pending':
                order={'signal':signal,'signal_index':index,'last_index':expiry_index}
    if position is not None:
        position['trade']['holding_sessions']=len(bars)-position['entry_index']
    return signals,trades


def _metrics(trades,phase,cutoff):
    own=[trade for trade in trades if trade['phase']==phase]
    completed=[trade for trade in own if trade['exit_date'] is not None and trade['exit_date']<=cutoff]
    unresolved=[trade for trade in own if trade['entry_date']<=cutoff
                and (trade['exit_date'] is None or trade['exit_date']>cutoff)]
    values=[trade['net_return'] for trade in completed]
    summary=two_point_kelly(values)
    gain,loss=summary['gain_fraction'],summary['loss_fraction']
    metric={'completed_count':len(completed),'closed_count':len(completed),
            'excluded_crossing_count':len(unresolved),'unresolved_count':len(unresolved),
            'wins':summary['wins'],'losses':summary['losses'],'zeros':summary['zeros'],
            'p':summary['p'],'gain_fraction':gain,'loss_fraction':loss,
            'payoff_ratio':_number(gain/loss,'net payoff ratio') if gain is not None and loss is not None else None,
            'mean_net_return':_number(fmean(values),'mean net return') if values else None,
            'period_start':min(trade['entry_date'] for trade in completed) if completed else None,
            'period_end':max(trade['exit_date'] for trade in completed) if completed else None}
    return metric,values


def _qualification(train,validation,returns,config):
    reasons=[]
    for phase,metrics,minimum in (('train',train,config.min_train_trades),
                                   ('validation',validation,config.min_validation_trades)):
        if metrics['completed_count']<minimum:
            reasons.append(phase+'_insufficient_trades')
        if metrics['p'] is None or metrics['p']<config.min_win_rate:
            reasons.append(phase+'_low_win_rate')
        if metrics['payoff_ratio'] is None:
            reasons.append(phase+'_insufficient_payoff_evidence')
        elif metrics['payoff_ratio']<config.min_payoff_ratio:
            reasons.append(phase+'_low_payoff_ratio')
        if metrics['mean_net_return'] is None or metrics['mean_net_return']<=0:
            reasons.append(phase+'_nonpositive_net_edge')
    diagnostic=two_point_kelly(returns)
    raw=diagnostic['raw_fraction']
    calculation=fractional_kelly(raw if raw is not None else 0.,kelly_fraction=config.kelly_fraction,
                                 cap_limit=config.cap_limit,vix_index=config.vix_index)
    if raw is None:
        for key in ('raw_fraction','fractional_fraction','capped_fraction'):
            calculation[key]=None
        reasons.append('insufficient_two_point_evidence')
    elif raw<=0:
        reasons.append('nonpositive_generalized_kelly')
    qualified=not reasons
    weight=calculation['capped_fraction'] if qualified else 0.
    calculation.update(two_point=diagnostic,held_reasons=reasons,applied=qualified,
                       model='two_point_net_return_approximation',qualified_at=config.validation_end,
                       input_basis='completed_validation_same_atr_barrier_policy_net_returns',
                       vix_basis='unknown' if config.vix_index is None else 'static_scenario',
                       approval_status='held',research_weight=weight,approved_weight=None)
    return qualified,weight,calculation


def _equity(bars,trades,config,weight):
    """Replay execution ledgers from unit capital; never borrow previous equity."""
    by_entry={trade['entry_date']:trade for trade in trades}
    cash,quantity,holding=1.,0.,None
    allocated,curve=[],[]
    entry_cost=(config.fee_bps+config.slippage_bps)/10000
    exit_cost=entry_cost+config.tax_bps/10000

    def sell():
        nonlocal cash,quantity,holding
        gross=quantity*holding['exit_price']
        cost=gross*exit_cost
        cash=_number(cash+gross-cost,'realized study cash',minimum=0.)
        holding['allocated_exit_cost']=cost
        holding['allocated_net_profit']=gross-cost-holding['allocated_entry_notional']-holding['allocated_entry_cost']
        quantity,holding=0.,None

    for bar in bars:
        if holding is not None and holding['exit_date']==bar['date']:
            sell()
        trade=by_entry.get(bar['date'])
        if trade is not None and weight>0:
            if holding is not None:
                raise ValueError('equity replay encountered overlapping positions')
            before=cash
            # Exact entry-weight cap after the entry fee reduces account equity.
            gross=weight*before/(1+weight*entry_cost)
            quantity=_number(gross/trade['entry_price'],'allocated quantity',positive=True)
            cost=gross*entry_cost
            cash=max(0.,_number(cash-gross-cost,'study cash'))
            holding=dict(trade,allocated_quantity=quantity,allocated_entry_notional=gross,
                         allocated_entry_cost=cost,allocated_exit_cost=None,allocated_net_profit=None,
                         entry_weight=gross/(cash+gross))
            allocated.append(holding)
            if holding['exit_date']==bar['date']:
                sell()
        held=_number(quantity*bar['close'],'marked holding value',minimum=0.)
        equity=_number(cash+held,'study equity',positive=True)
        curve.append({'date':bar['date'],'close':bar['close'],'equity':equity,'cash':cash,
                      'holding_quantity':quantity,'exposure':held/equity})
    return curve,allocated


def _finite_report(value):
    if isinstance(value,float) and not math.isfinite(value):
        raise ValueError('ATR research report cannot contain nonfinite values')
    if isinstance(value,dict):
        for item in value.values(): _finite_report(item)
    elif isinstance(value,list):
        for item in value: _finite_report(item)


def run_atr_kelly_backtest(prices:list[dict],*,config:ATRKellyConfig)->dict:
    if not isinstance(config,ATRKellyConfig):
        raise ValueError('config must be an ATRKellyConfig')
    prepared=_observations(prices,config)
    symbols,all_trades=[],[]
    for code,name,bars,plans in prepared:
        signals,trades=_simulate(code,name,bars,plans,config)
        phase_metrics={}
        validation_returns=[]
        for phase,cutoff in (('train',config.train_end),('validation',config.validation_end),('test',bars[-1]['date'])):
            phase_metrics[phase],returns=_metrics(trades,phase,cutoff)
            if phase=='validation': validation_returns=returns
        qualified,weight,calculation=_qualification(phase_metrics['train'],phase_metrics['validation'],validation_returns,config)
        study,_=_equity(bars,trades,config,1.)
        first_test=next((i for i,bar in enumerate(bars) if bar['date']>config.validation_end),len(bars))
        _,test_trades=_simulate(code,name,bars,plans,config,start_index=first_test)
        kelly_curve,kelly_trades=_equity(bars[first_test:],test_trades,config,weight)
        symbols.append({'code':code,'name':name,'bars':bars,'signals':signals,'trades':trades,
                        'phase_metrics':phase_metrics,'kelly_calculation':calculation,
                        'evidence_qualified':qualified,'research_weight':weight,'production_eligible':False,
                        'price_study_equity':study,'kelly_test_equity':kelly_curve,'kelly_test_trades':kelly_trades,
                        'curve_basis':{'price_study_equity':'full_single_symbol_notional_not_kelly_or_portfolio',
                                       'kelly_test_equity':'flat_start_test_only_frozen_hypothetical_research_weight'}})
        all_trades.extend(trades)
    dates=sorted({bar['date'] for stock in symbols for bar in stock['bars']})
    report={'schema_version':1,'mode':'price_only_research','settings':asdict(config),
            'periods':{'first_session':dates[0],'train_end':config.train_end,'validation_end':config.validation_end,
                       'test_start':next((day for day in dates if day>config.validation_end),None),'test_end':dates[-1]},
            'symbols':symbols,'trades':sorted(all_trades,key=lambda trade:(trade['entry_date'],trade['code'])),
            'approval':{'status':'held','production_eligible':False,
                        'reasons':['historical_point_in_time_fundamentals_unverified','price_only_research']},
            'assumptions':[
                'ATR is the simple rolling mean of true ranges; Bollinger bands include the signal close and use sample deviation.',
                'Plans freeze after the signal close. Limit orders can fill only in the following observed sessions; zero volume never fills.',
                'Signal-session entry is prohibited. Improved entries keep the original stop and target; stop gaps use the worse executable open.',
                'If a bar touches stop and target, stop is first. An intraday entry cannot claim a target that may have occurred before entry.',
                'Holding sessions include the entry session. Zero-volume exits defer to a later executable session; data-end positions are not force-liquidated.',
                'Train and validation calibration includes only trades signalled in that phase and completed by its cutoff; crossing and open labels are excluded.',
                'Win probability conditions on nonzero realized net outcomes; zero outcomes and completed trade counts remain explicit.',
                'Kelly uses means of the same strategy validation net gains and losses, a two-outcome approximation rather than a calibrated future probability.',
                'Optional VIX is a static research scenario, not an observed historical series; missing VIX stays null.',
                'The full-notional per-symbol price study is not a portfolio. Kelly test equity resets to unit cash with test-origin orders only; it may differ from a continuously held study.',
                'Fees, slippage, and taxes are user assumptions. Price-only evidence does not certify point-in-time fundamentals, survivorship or production eligibility.',
            ]}
    _finite_report(report)
    return report
