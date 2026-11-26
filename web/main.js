(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const english = {
    eyebrow:'AI quantitative research · learn the principles',hero:'Understand how models learn.<br>Then connect scores to decisions.',lead:'From daily bars, past-only features and historical targets to deep learning, generative augmentation, real held-out evaluation and constrained portfolios. Make every step explainable and testable.',seeFlow:'Explore the training flow',tryLab:'Try the risk and allocation lab',scope:'Public teaching demo · all numbers are illustrative · no account or trading connection',flowTag:'From data to decisions',flowTitle:'One animation, the whole research process',download:'Download GIF',gifCaption:'Use the GIF for a quick README overview. Explore the formulas interactively below. The animation contains no actual backtest performance.',step0:'Bars and time',step1:'Past-only features',step2:'Historical targets',step3:'DL and GenAI',step4:'Held-out checks',step5:'Factor to decision',labTag:'Explore the mechanics',labTitle:'Risk estimates change sizing, not necessarily direction forecasts',toy:'Illustrative assumptions',ewmaTitle:'EWMA: how much weight goes to the latest shock?',ewmaIntro:'Assume an old daily volatility of 2%. Change the smoothing coefficient and the latest observed return to inspect the next-day risk estimate.',lambdaLabel:'Smoothing coefficient λ',shockLabel:'Latest observed daily return',newVol:'Estimated next-day volatility',ewmaCaveat:'The bar shows mixing coefficients, not shares of total variance. This example assumes zero mean; a full portfolio also needs cross-asset covariances.',weightsTitle:'From forecast scores to target weights',weightsIntro:'Three hypothetical assets have five-day excess-return forecasts of 1.2%, 0.5%, and 0.05%, and annual volatility of 30%, 20%, and 40%. Apply the cost gate before sizing risk.',costLabel:'One-way trading cost',capLabel:'Maximum weight per asset',riskLabel:'Annual portfolio-volatility budget',asset:'Asset',forecast:'Forecast',gate:'Pass gate',weight:'Target weight',cash:'Residual cash',weightCaveat:'Assume a minimum cash reserve of 20% and pairwise correlation of 0.4. Caps are not redistributed; risk scaling only reduces positions. No executable orders exist here.',mathTag:'The mathematics',mathTitle:'Know where each number comes from',targetTitle:'Prediction targets and execution timing',targetText:'Version one uses h = 5: form a signal after close, measure the five-session return from the t+1 open to the t+6 open, and subtract the same SPY return. Historical training can use outcomes known later; a live forecast cannot use outcomes that have not happened.',lossTitle:'How deep learning updates parameters',lossText:'The network predicts, measures its error, then adjusts parameters using gradients. Fit preprocessing only on training data. This is the basic gradient idea; an implementation may use an optimizer such as Adam.',genTitle:'What generative AI adds',genText:'A conditional diffusion model learns from training-period outcomes and gradually denoises samples paired with historical inputs. Synthetic samples are not new market evidence. Compare against real-data training and resampling on the same real held-out period.',icTitle:'What IC and portfolio equity each measure',icText:'Within the same date, compare forecast rankings with realized-return rankings across stocks. IC measures predictive association. Equity also depends on position sizing, market exposure, costs and timing. Overlapping five-day labels are not independent observations.',decisionTitle:'How factors become decisions',decisionText:'Forecast scores first pass a cost gate. Eligible assets receive inverse-volatility weights, position caps, cash reserves and portfolio-risk limits. A unitless ranking score must be calibrated on separate validation data before comparison with return costs.',levyTitle:'Why start with EWMA',levyText:'Start with a risk scale that can be checked. Heavy tails, jumps and volatility clustering are different questions; a constant-parameter Lévy return process does not automatically model persistent volatility. Add complexity when a research question and held-out evidence justify it.',ewmaSource:'Official EWMA definition',readmeTitle:'Put the research process in your project README',readmeText:'Save the GIF in a repository and embed it using a relative path. The animation gives an overview; this page supports interaction. The full research program runs in a separate environment.',copy:'Copy Markdown',footer:'Illustrative teaching · no real market observations, accounts or orders · not evidence of strategy effectiveness'
  };
  Object.assign(english, {
    navFlow:'Training flow',navMomentum:'Momentum & trend',navRisk:'Risk & sizing',navMath:'Mathematics',tryMomentum:'Explore momentum & trend',
    trendTag:'Four daily rules',trendTitle:'Momentum & trend: make simple rules explainable',
    trendIntro:'Cross-sectional momentum compares assets with one another. Trend rules decide whether an asset itself is eligible to hold. Choose a rule and change an illustrative price to inspect its signal. All parameters are research examples.',
    csTitle:'Cross-sectional momentum',csBrief:'Rank multiple stocks by their past 60-session return on the same date.',
    tsTitle:'Time-series momentum',tsBrief:'Check whether the asset’s own past 60-session return is positive: hold or stay in cash.',
    maTitle:'Moving-average trend filter',maBrief:'Close above the 200-session SMA, with the 50-session SMA above the 200-session SMA.',
    breakoutTitle:'Channel breakout',breakoutBrief:'Enter above the previous 55-session high; exit below the previous 20-session low. Exclude today.',
    trendPriceLabel:'Asset A’s current close (illustrative)',trendMaLabel:'Mean close over the previous 49 sessions',trendHeldLabel:'Assume asset A is already held',
    trendReturn:'Past 60-session return',trendScore:'Rank percentile',
    trendTiming:'<strong>Determine the signal after close; simulate execution at the next session’s open.</strong> The 60, 50/200 and 55/20-session windows are examples, not validated optimal parameters. Daily rules can be backtested; minute-level research requires separate intraday data, costs and execution checks.',
    trendUnits:'Rankings, binary states and channel rules are trading signals, not calibrated future-return forecasts. Do not compare them directly with a cost threshold measured in bps. Position sizing, fees and cash still need a common backtest.',
    trendRunTitle:'Run actual experiments in the research app',trendRunText:'Choose your moomoo CSV, an online historical snapshot or an explicitly labeled synthetic example. This page only explains rules: it fetches no market observations and shows no actual strategy returns.',
    openHf:'Open Hugging Face app',openStreamlit:'Open Streamlit Cloud app'
  });
  const chinese = {};
  document.querySelectorAll('[data-i18n]').forEach(el => { chinese[el.dataset.i18n] = el.innerHTML; });
  const stageContent = {
    zh:[
      ['先确定信息在什么时候可见','每根日 K 只代表已完成的交易日。记录来源、复权口径和市场时间，避免把稍后更新的数据提前放进输入。','已完成日 K → 可用历史'],
      ['从历史计算输入 X','第一版从动量、收益变化、波动和价量关系构造 41 个历史特征，只使用信号日及以前的数据。预处理参数只拟合训练集，不能从测试期学习均值和标准差。','Xₜ = features(observations up to t)'],
      ['历史答案可训练，未来答案不可偷看','第一版预测五日相对收益：t+1 开盘到 t+6 开盘，减去 SPY 同期收益。研究过去时可以用后来已知的答案训练；模拟当时预测时，只能看到当时信息。跨越数据划分边界的答案要剔除。','过去输入 Xₜ + 后来已知的答案 yₜ → 历史训练'],
      ['预测器和生成器承担不同任务','DL 预测收益或排名；条件 GenAI 为训练输入生成配套样本。对照模型需要匹配训练预算，生成器不能使用验证或测试答案。','真实训练 vs 重采样 vs 条件生成增强'],
      ['在真实未见时期检查预测','按时间划分：训练期拟合参数，验证期选择设置并校准预测，最后冻结所有设置，才进入测试期。先看排序关系，再看统一仓位规则下的净值与回撤；训练误差下降不代表未来有效。','同一真实留出期 → Rank IC、成本、风险'],
      ['分数经过约束才能形成仓位','检查收益单位和成本门槛，再做逆波动分配、单股封顶、相关性风险缩放与现金预算。订单草稿仍需要新报价和独立执行验证。','预测 → 成本门槛 → 风险/仓位 → 模拟草稿']
    ],
    en:[
      ['Start with information availability','Each daily bar represents a completed market session. Keep source, adjustments and market time. Do not move later revisions backward into earlier inputs.','Completed daily bars → available history'],
      ['Compute inputs X from the past','Version one constructs 41 historical features from momentum, returns, volatility and price/volume relationships, using observations available by the signal date. Fit preprocessing only on training data, never test-period means or scales.','Xₜ = features(observations up to t)'],
      ['Historical answers can teach; unseen answers cannot leak','Version one predicts five-session excess return: the t+1 open to the t+6 open, minus the same SPY return. Later-known historical outcomes supervise learning, while each simulated forecast sees only information then available. Purge targets crossing split boundaries.','Past input Xₜ + later-known target yₜ → historical training'],
      ['Predictors and generators have different jobs','DL predicts returns or rankings. Conditional GenAI produces paired training examples. Match predictor budgets across controls, and never fit the generator on validation or test targets.','Real-data training vs resampling vs conditional augmentation'],
      ['Evaluate on a real unseen period','Split chronologically: train to fit parameters; validate to choose settings and calibrate forecasts; freeze everything before the final test. Inspect ranking association, then equity and drawdown under common rules. Lower training loss does not establish future predictive ability.','Same real holdout → Rank IC, costs and risk'],
      ['A score becomes a weight through constraints','Check return units and costs, then apply inverse volatility, asset caps, correlated-risk scaling and cash budgets. Draft orders still require new quotes and independent execution validation.','Forecast → cost gate → risk/weights → simulated draft']
    ]
  };
  const trendContent = {
    zh:{
      cs:{title:'横截面动量：相对谁更强？',text:'在同一个信号日，把股票池中的过去收益放在一起比较。排名靠前只表示相对较强，即使整组股票都在下跌，也会有第一名。',formula:'R<sub>i,60,t</sub> = C<sub>i,t</sub> / C<sub>i,t−60</sub> − 1<br>s<sub>i,t</sub> = rank_pct(R<sub>i,60,t</sub>)',assumptions:'假设A在60个交易日前收盘为100；B、C、D的同期收益固定为+8%、−4%、−10%。百分位越大，相对排名越高。',note:'百分位分数没有收益率单位；不能把0.75理解为未来会涨75%。本例只做横截面比较，不生成实际仓位。'},
      ts:{title:'时间序列动量：自己是否在上涨？',text:'不需要和其他股票比较。自身过去60个交易日收益为正时进入持有候选，否则保持现金。这里仅演示做多或现金，不做空。',formula:'R<sub>60,t</sub> = C<sub>t</sub> / C<sub>t−60</sub> − 1<br>q<sub>t</sub> = 𝟙[R<sub>60,t</sub> &gt; 0]',assumptions:'假设60个交易日前收盘为100。滑块移到100时收益恰为0，不满足严格大于0的条件。',note:'q是0/1持有资格，不是收益预测，也不是实际资金权重。风险预算和现金约束另外决定仓位。'},
      ma:{title:'双均线：同时检查价格与趋势',text:'两个条件同时成立才进入持有候选：收盘高于200日简单均线，且50日简单均线高于200日均线。改变前49日均价，可以单独观察第二个条件。',formula:'SMA<sub>n,t</sub> = (1/n) · Σ<sub>k=0…n−1</sub> C<sub>t−k</sub><br>q<sub>t</sub> = 𝟙[C<sub>t</sub> &gt; SMA<sub>200,t</sub> 且 SMA<sub>50,t</sub> &gt; SMA<sub>200,t</sub>]',assumptions:'教学假设：前199日均价固定为100；前49日均价可调。当前收盘同时进入50日和200日均线，滑块变化后均线会随之重算。',note:'这是价格与趋势过滤，不是对未来收益的回归预测。长窗口需要足够真实历史，不补上市前数据。'},
      breakout:{title:'通道突破：进入、退出与保持',text:'收盘突破前55日最高high时进入；跌破前20日最低low时退出。两者之间维持原状态，因此相同价格可能对应持仓或现金。',formula:'H<sub>55,t</sub> = max(H<sub>t−1</sub>, …, H<sub>t−55</sub>)<br>L<sub>20,t</sub> = min(L<sub>t−1</sub>, …, L<sub>t−20</sub>)<br>C<sub>t</sub> &gt; H<sub>55,t</sub> → 进入；C<sub>t</sub> &lt; L<sub>20,t</sub> → 退出',assumptions:'假设前55日最高high为112，前20日最低low为96。两个窗口都排除当天；等于边界不触发。勾选持仓状态来比较通道内的不同结果。',note:'勾选框是固定的教学初始状态，不会因拖动滑块自动累积持仓历史；每次都从该状态判断。这不是价格路径回测。'}
    },
    en:{
      cs:{title:'Cross-sectional momentum: stronger than what?',text:'Compare past returns across the universe on the same signal date. A high rank means relative strength. There is still a first-place asset even when the entire group is falling.',formula:'R<sub>i,60,t</sub> = C<sub>i,t</sub> / C<sub>i,t−60</sub> − 1<br>s<sub>i,t</sub> = rank_pct(R<sub>i,60,t</sub>)',assumptions:'Assume A closed at 100 sixty sessions ago. B, C and D have fixed same-period returns of +8%, −4% and −10%. A larger percentile means a higher relative rank.',note:'A percentile has no return units: 0.75 does not forecast a 75% gain. This example compares assets without creating actual portfolio weights.'},
      ts:{title:'Time-series momentum: is this asset rising?',text:'No comparison with other stocks is required. A positive past 60-session return makes the asset eligible to hold; otherwise remain in cash. This example is long-or-cash, without short selling.',formula:'R<sub>60,t</sub> = C<sub>t</sub> / C<sub>t−60</sub> − 1<br>q<sub>t</sub> = 𝟙[R<sub>60,t</sub> &gt; 0]',assumptions:'Assume the close sixty sessions ago was 100. At a current close of 100 the return is exactly zero, so it fails the strictly-positive test.',note:'q is binary holding eligibility, not a return forecast or an actual capital weight. Cash reserves and risk constraints determine sizing separately.'},
      ma:{title:'Two moving averages: check price and trend',text:'Both tests must pass: close above the 200-session simple moving average, and the 50-session SMA above the 200-session SMA. Change the previous 49-session mean to inspect the second condition separately.',formula:'SMA<sub>n,t</sub> = (1/n) · Σ<sub>k=0…n−1</sub> C<sub>t−k</sub><br>q<sub>t</sub> = 𝟙[C<sub>t</sub> &gt; SMA<sub>200,t</sub> AND SMA<sub>50,t</sub> &gt; SMA<sub>200,t</sub>]',assumptions:'Illustrative assumptions: the previous 199-session mean is fixed at 100; the previous 49-session mean is adjustable. Today’s close enters both SMAs, which are recomputed as the sliders move.',note:'This is a price-and-trend filter, not a regression forecast of future returns. Long windows require sufficient real history; pre-IPO prices are not filled.'},
      breakout:{title:'Channel breakout: enter, exit or keep the state',text:'Enter when close exceeds the previous 55-session highest high. Exit when it falls below the previous 20-session lowest low. Keep the existing state between them, so the same price can imply holdings or cash.',formula:'H<sub>55,t</sub> = max(H<sub>t−1</sub>, …, H<sub>t−55</sub>)<br>L<sub>20,t</sub> = min(L<sub>t−1</sub>, …, L<sub>t−20</sub>)<br>C<sub>t</sub> &gt; H<sub>55,t</sub> → enter; C<sub>t</sub> &lt; L<sub>20,t</sub> → exit',assumptions:'Assume the previous 55-session high is 112 and the previous 20-session low is 96. Both windows exclude today; equality does not trigger a transition. Toggle the existing holding to compare outcomes inside the channel.',note:'The checkbox sets a fixed illustrative starting state. Moving the slider does not accumulate trading history: each evaluation starts from that checkbox. This is not a price-path backtest.'}
    }
  };
  let lang = 'zh', stage = 0, strategy = 'cs';
  let playing = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try { if(localStorage.getItem('alpha-guide-language')==='en')lang='en'; } catch {}
  const pct = (x,d=1) => `${(x*100).toFixed(d)}%`;
  function renderStage(){
    const values = stageContent[lang][stage];
    $('stageNumber').textContent=String(stage+1).padStart(2,'0');
    $('stageTitle').textContent=values[0];$('stageText').textContent=values[1];$('stageFormula').textContent=values[2];
    document.querySelectorAll('[data-stage]').forEach(button=>{const selected=Number(button.dataset.stage)===stage;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));});
  }
  function renderMotion(){
    const suffix=lang==='en'?'-en':'';
    $('flowImage').src=playing?`assets/training-flow${suffix}.gif`:`assets/poster${suffix}.png`;
    $('flowImage').alt=lang==='zh'?'AI alpha训练流程的中英双语教学示意':'Illustrative AI alpha research workflow in English';
    $('downloadGif').href=`assets/training-flow${suffix}.gif`;
    $('downloadGif').download=lang==='en'?'alpha-training-flow-en.gif':'alpha-training-flow.gif';
    $('readmeSnippet').textContent=lang==='en'?'![AI alpha training flow](docs/media/en/alpha-training-flow.gif)':'![AI Alpha训练流程](docs/media/alpha-training-flow.gif)';
    $('motion').textContent=lang==='zh'?(playing?'暂停动图':'播放动图'):(playing?'Pause animation':'Play animation');
    $('motion').setAttribute('aria-pressed',String(playing));
  }
  function ewma(lambda,shock,oldVol=.02){return Math.sqrt(lambda*oldVol*oldVol+(1-lambda)*shock*shock);}
  function renderEwma(){
    const lambda=Number($('lambda').value), shock=Number($('shock').value)/100;
    $('lambdaOut').textContent=lambda.toFixed(2);$('shockOut').textContent=pct(shock,1);$('volOut').textContent=pct(ewma(lambda,shock),3);
    $('oldMix').style.width=pct(lambda,3);$('newMix').style.width=pct(1-lambda,3);
    $('oldWeight').textContent=(lang==='zh'?'旧方差系数 ':'Old variance coefficient ')+pct(lambda,0);
    $('newWeight').textContent=(lang==='zh'?'最新冲击系数 ':'Latest-shock coefficient ')+pct(1-lambda,0);
    $('ewmaDetail').textContent=lang==='zh'?'收益先平方再参与风险更新，所以同样幅度的正负冲击给出同样结果。它估计幅度，不预测涨跌方向。':'Returns enter as squared shocks, so equal positive and negative moves produce the same estimate. This measures magnitude, not price direction.';
  }
  const assets=[{id:'A',forecast:.012,vol:.30,color:'#126a78'},{id:'B',forecast:.005,vol:.20,color:'#bd7b20'},{id:'C',forecast:.0005,vol:.40,color:'#6077a0'}];
  function allocation(cost,cap,risk){
    const gate=2*cost/10000, selected=assets.filter(a=>a.forecast>gate);
    const total=selected.reduce((sum,a)=>sum+1/a.vol,0);
    const weights=assets.map(a=>selected.includes(a)?Math.min(.8*(1/a.vol)/total,cap):0);
    let variance=0;
    for(let i=0;i<assets.length;i++)for(let j=0;j<assets.length;j++)variance+=weights[i]*weights[j]*assets[i].vol*assets[j].vol*(i===j?1:.4);
    const before=Math.sqrt(Math.max(variance,0)),scale=before>0?Math.min(1,risk/before):1;
    const final=weights.map(w=>w*scale);
    return {gate,weights:final,cash:1-final.reduce((sum,w)=>sum+w,0),scale,vol:before*scale};
  }
  function renderWeights(){
    const cost=Number($('cost').value),cap=Number($('cap').value)/100,risk=Number($('risk').value)/100;
    const result=allocation(cost,cap,risk);
    $('costOut').textContent=`${cost} bps`;$('capOut').textContent=pct(cap,0);$('riskOut').textContent=pct(risk,0);
    $('weightRows').replaceChildren();$('allocationTrack').replaceChildren();
    assets.forEach((asset,index)=>{
      const row=document.createElement('tr');
      const pass=asset.forecast>result.gate;
      [asset.id,pct(asset.forecast,2),lang==='zh'?(pass?'是':'否'):(pass?'Yes':'No'),pct(result.weights[index],1)].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;row.appendChild(cell);});
      $('weightRows').appendChild(row);
      if(result.weights[index]>0){const mark=document.createElement('span');mark.style.width=pct(result.weights[index],4);mark.style.background=asset.color;$('allocationTrack').appendChild(mark);}
    });
    const cashMark=document.createElement('span');cashMark.style.width=pct(result.cash,4);cashMark.style.background='#9badbd';$('allocationTrack').appendChild(cashMark);
    $('cashOut').textContent=pct(result.cash,1);
    $('weightDetail').textContent=lang==='zh'?`往返成本门槛 ${pct(result.gate,2)}；风险缩放系数 ${result.scale.toFixed(3)}；缩放后估计年化波动 ${pct(result.vol,2)}。`:`Round-trip cost gate ${pct(result.gate,2)}; risk scale ${result.scale.toFixed(3)}; estimated annual volatility after scaling ${pct(result.vol,2)}.`;
  }
  function trendExample(close,maPast=105,held=false){
    const returns=[{id:'A',value:close/100-1},{id:'B',value:.08},{id:'C',value:-.04},{id:'D',value:-.10}];
    const ranks=returns.map(asset=>{
      const below=returns.filter(other=>other.value<asset.value-1e-12).length;
      const tied=returns.filter(other=>Math.abs(other.value-asset.value)<1e-12).length;
      return {...asset,score:(below+(tied+1)/2)/returns.length};
    });
    const ma50=(49*maPast+close)/50,ma200=(199*100+close)/200;
    const entry=close>112,exit=close<96;
    return {returns:ranks,momentum:returns[0].value,rank:ranks[0].score,
      ts:close>100,ma50,ma200,ma:close>ma200&&ma50>ma200,
      entry,exit,held:entry?true:exit?false:held};
  }
  function renderTrend(){
    const content=trendContent[lang][strategy],close=Number($('trendPrice').value),maPast=Number($('trendMaPast').value);
    const initialHeld=$('trendHeld').checked,result=trendExample(close,maPast,initialHeld);
    $('trendRuleTitle').textContent=content.title;$('trendRuleText').textContent=content.text;
    $('trendFormula').innerHTML=content.formula;$('trendAssumptions').textContent=content.assumptions;$('trendScoreNote').textContent=content.note;
    $('trendPriceOut').textContent=close.toFixed(0);$('trendMaOut').textContent=maPast.toFixed(0);
    $('trendMaControl').hidden=strategy!=='ma';$('trendHeldControl').hidden=strategy!=='breakout';$('trendComparison').hidden=strategy!=='cs';
    $('trendRows').replaceChildren();
    result.returns.forEach(asset=>{
      const row=document.createElement('tr');if(asset.id==='A')row.classList.add('highlight-row');
      [asset.id,`${asset.value>0?'+':''}${pct(asset.value,1)}`,asset.score.toFixed(3)].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;row.appendChild(cell);});
      $('trendRows').appendChild(row);
    });
    if(strategy==='cs'){
      $('trendResultLabel').textContent=lang==='zh'?'A的排名百分位':'A’s rank percentile';$('trendResult').textContent=result.rank.toFixed(3);
      $('trendOutcome').textContent=lang==='zh'?`A的过去60日收益为${pct(result.momentum,1)}。比较的是同一日期的四个假设资产；相同收益采用平均名次。`:`A’s past 60-session return is ${pct(result.momentum,1)}. Compare four hypothetical assets on the same date; equal returns receive their average rank.`;
    }else if(strategy==='ts'||strategy==='ma'){
      const eligible=strategy==='ts'?result.ts:result.ma;
      $('trendResultLabel').textContent=lang==='zh'?'下一开盘的持有资格':'Eligibility at the next open';$('trendResult').textContent=lang==='zh'?(eligible?'1 · 持有候选':'0 · 现金'):(eligible?'1 · Eligible':'0 · Cash');
      $('trendOutcome').textContent=strategy==='ts'?(lang==='zh'?`过去60日收益${pct(result.momentum,1)}${eligible?' > 0，满足条件。':' ≤ 0，不满足条件。'}`:`Past 60-session return ${pct(result.momentum,1)} ${eligible?'> 0: the test passes.':'≤ 0: the test fails.'}`):(lang==='zh'?`50日SMA=${result.ma50.toFixed(3)}；200日SMA=${result.ma200.toFixed(3)}。两个条件${eligible?'同时成立。':'没有同时成立。'}`:`50-session SMA=${result.ma50.toFixed(3)}; 200-session SMA=${result.ma200.toFixed(3)}. ${eligible?'Both tests pass.':'Both tests do not pass together.'}`);
    }else{
      $('trendResultLabel').textContent=lang==='zh'?'下一开盘的目标状态':'Target state at the next open';$('trendResult').textContent=lang==='zh'?(result.held?'持有':'现金'):(result.held?'Long':'Cash');
      $('trendOutcome').textContent=lang==='zh'?(result.entry?'收盘 > 112：突破入场边界；若已持有则继续持有。':result.exit?'收盘 < 96：触发退出边界；若空仓则继续保留现金。':`收盘在[96,112]内：维持示例初始状态（${initialHeld?'持有':'现金'}），不生成新的突破转换。`):(result.entry?'Close > 112: entry boundary crossed; an existing holding stays long.':result.exit?'Close < 96: exit boundary crossed; an empty position stays in cash.':`Close inside [96,112]: preserve the illustrative initial state (${initialHeld?'long':'cash'}); no new breakout transition.`);
    }
    document.querySelectorAll('[data-strategy]').forEach(button=>{const selected=button.dataset.strategy===strategy;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));});
  }
  function renderLanguage(){
    document.documentElement.lang=lang==='zh'?'zh-CN':'en';
    document.title=lang==='zh'?'Alpha Training Lab · 从数据到决策':'Alpha Training Lab · From data to decisions';
    document.querySelectorAll('[data-i18n]').forEach(el=>{const key=el.dataset.i18n;el.innerHTML=lang==='en'?english[key]:chinese[key];});
    $('language').textContent=lang==='zh'?'English':'中文';
    $('language').setAttribute('aria-label',lang==='zh'?'Switch to English':'Switch to Chinese');
    $('topnav').setAttribute('aria-label',lang==='zh'?'页面导航':'Page navigation');
    $('strategyChoices').setAttribute('aria-label',lang==='zh'?'选择策略示例':'Choose a strategy example');
    document.querySelector('.steps').setAttribute('aria-label',lang==='zh'?'训练阶段':'Training stages');
    document.querySelector('meta[name="description"]').content=lang==='zh'?'从日K到可检验的AI alpha：双语训练原理、动量与趋势、风险与仓位交互教学。':'From daily bars to testable AI alpha: bilingual training principles, momentum and trend, risk and sizing examples.';
    $('copyStatus').textContent='';renderStage();renderEwma();renderWeights();renderMotion();renderTrend();
  }
  $('language').addEventListener('click',()=>{lang=lang==='zh'?'en':'zh';try{localStorage.setItem('alpha-guide-language',lang);}catch{}renderLanguage();});
  $('motion').addEventListener('click',()=>{playing=!playing;renderMotion();});
  document.querySelectorAll('[data-stage]').forEach(button=>button.addEventListener('click',()=>{stage=Number(button.dataset.stage);renderStage();}));
  ['lambda','shock'].forEach(id=>$(id).addEventListener('input',renderEwma));
  ['cost','cap','risk'].forEach(id=>$(id).addEventListener('input',renderWeights));
  document.querySelectorAll('[data-strategy]').forEach(button=>button.addEventListener('click',()=>{strategy=button.dataset.strategy;renderTrend();}));
  ['trendPrice','trendMaPast','trendHeld'].forEach(id=>$(id).addEventListener('input',renderTrend));
  $('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('readmeSnippet').textContent);$('copyStatus').textContent=lang==='zh'?'已复制':'Copied';}catch{$('copyStatus').textContent=lang==='zh'?'请选中上方文字手动复制':'Select the text above and copy manually';}});
  // Deterministic checks of the educational calculations; no market observations are used.
  if(Math.abs(ewma(.94,-.03)-Math.sqrt(.00043))>1e-12)throw Error('EWMA example mismatch');
  const base=allocation(10,.20,.15);if(Math.abs(base.cash-.6)>1e-12||base.weights.some(w=>w>.2+1e-12))throw Error('Allocation constraints mismatch');
  if(allocation(100,.20,.15).cash!==1)throw Error('Cost gate mismatch');
  window.AlphaTeaching={ewma,allocation,trendExample};
  renderLanguage();
})();
