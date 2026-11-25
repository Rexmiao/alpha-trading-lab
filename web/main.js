(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const english = {
    eyebrow:'AI quantitative research · learn the principles',hero:'Understand how models learn.<br>Then connect scores to decisions.',lead:'From daily bars, past-only features and historical targets to deep learning, generative augmentation, real held-out evaluation and constrained portfolios. Make every step explainable and testable.',seeFlow:'Explore the training flow',tryLab:'Try the risk and allocation lab',scope:'Public teaching demo · all numbers are illustrative · no account or trading connection',flowTag:'From data to decisions',flowTitle:'One animation, the whole research process',download:'Download GIF',gifCaption:'Use the GIF for a quick README overview. Explore the formulas interactively below. The animation contains no actual backtest performance.',step0:'Bars and time',step1:'Past-only features',step2:'Historical targets',step3:'DL and GenAI',step4:'Held-out checks',step5:'Factor to decision',labTag:'Explore the mechanics',labTitle:'Risk estimates change sizing, not necessarily direction forecasts',toy:'Illustrative assumptions',ewmaTitle:'EWMA: how much weight goes to the latest shock?',ewmaIntro:'Assume an old daily volatility of 2%. Change the smoothing coefficient and the latest observed return to inspect the next-day risk estimate.',lambdaLabel:'Smoothing coefficient λ',shockLabel:'Latest observed daily return',newVol:'Estimated next-day volatility',ewmaCaveat:'The bar shows mixing coefficients, not shares of total variance. This example assumes zero mean; a full portfolio also needs cross-asset covariances.',weightsTitle:'From forecast scores to target weights',weightsIntro:'Three hypothetical assets have five-day excess-return forecasts of 1.2%, 0.5%, and 0.05%, and annual volatility of 30%, 20%, and 40%. Apply the cost gate before sizing risk.',costLabel:'One-way trading cost',capLabel:'Maximum weight per asset',riskLabel:'Annual portfolio-volatility budget',asset:'Asset',forecast:'Forecast',gate:'Pass gate',weight:'Target weight',cash:'Residual cash',weightCaveat:'Assume a minimum cash reserve of 20% and pairwise correlation of 0.4. Caps are not redistributed; risk scaling only reduces positions. No executable orders exist here.',mathTag:'The mathematics',mathTitle:'Know where each number comes from',targetTitle:'Prediction targets and execution timing',targetText:'Version one uses h = 5: form a signal after close, measure the five-session return from the t+1 open to the t+6 open, and subtract the same SPY return. Historical training can use outcomes known later; a live forecast cannot use outcomes that have not happened.',lossTitle:'How deep learning updates parameters',lossText:'The network predicts, measures its error, then adjusts parameters using gradients. Fit preprocessing only on training data. This is the basic gradient idea; an implementation may use an optimizer such as Adam.',genTitle:'What generative AI adds',genText:'A conditional diffusion model learns from training-period outcomes and gradually denoises samples paired with historical inputs. Synthetic samples are not new market evidence. Compare against real-data training and resampling on the same real held-out period.',icTitle:'What IC and portfolio equity each measure',icText:'Within the same date, compare forecast rankings with realized-return rankings across stocks. IC measures predictive association. Equity also depends on position sizing, market exposure, costs and timing. Overlapping five-day labels are not independent observations.',decisionTitle:'How factors become decisions',decisionText:'Forecast scores first pass a cost gate. Eligible assets receive inverse-volatility weights, position caps, cash reserves and portfolio-risk limits. A unitless ranking score must be calibrated on separate validation data before comparison with return costs.',levyTitle:'Why start with EWMA',levyText:'Start with a risk scale that can be checked. Heavy tails, jumps and volatility clustering are different questions; a constant-parameter Lévy return process does not automatically model persistent volatility. Add complexity when a research question and held-out evidence justify it.',ewmaSource:'Official EWMA definition',readmeTitle:'Put the research process in your project README',readmeText:'Save the GIF in a repository and embed it using a relative path. The animation gives an overview; this page supports interaction. The full research program runs in a separate environment.',copy:'Copy Markdown',footer:'Illustrative teaching · no real market observations, accounts or orders · not evidence of strategy effectiveness'
  };
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
  let lang = 'zh', stage = 0;
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
  function renderLanguage(){
    document.documentElement.lang=lang==='zh'?'zh-CN':'en';
    document.title=lang==='zh'?'Alpha Training Lab · 从数据到决策':'Alpha Training Lab · From data to decisions';
    document.querySelectorAll('[data-i18n]').forEach(el=>{const key=el.dataset.i18n;el.innerHTML=lang==='en'?english[key]:chinese[key];});
    $('language').textContent=lang==='zh'?'English':'中文';
    $('language').setAttribute('aria-label',lang==='zh'?'Switch to English':'Switch to Chinese');
    $('copyStatus').textContent='';renderStage();renderEwma();renderWeights();renderMotion();
  }
  $('language').addEventListener('click',()=>{lang=lang==='zh'?'en':'zh';try{localStorage.setItem('alpha-guide-language',lang);}catch{}renderLanguage();});
  $('motion').addEventListener('click',()=>{playing=!playing;renderMotion();});
  document.querySelectorAll('[data-stage]').forEach(button=>button.addEventListener('click',()=>{stage=Number(button.dataset.stage);renderStage();}));
  ['lambda','shock'].forEach(id=>$(id).addEventListener('input',renderEwma));
  ['cost','cap','risk'].forEach(id=>$(id).addEventListener('input',renderWeights));
  $('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('readmeSnippet').textContent);$('copyStatus').textContent=lang==='zh'?'已复制':'Copied';}catch{$('copyStatus').textContent=lang==='zh'?'请选中上方文字手动复制':'Select the text above and copy manually';}});
  // Deterministic checks of the educational calculations; no market observations are used.
  if(Math.abs(ewma(.94,-.03)-Math.sqrt(.00043))>1e-12)throw Error('EWMA example mismatch');
  const base=allocation(10,.20,.15);if(Math.abs(base.cash-.6)>1e-12||base.weights.some(w=>w>.2+1e-12))throw Error('Allocation constraints mismatch');
  if(allocation(100,.20,.15).cash!==1)throw Error('Cost gate mismatch');
  window.AlphaTeaching={ewma,allocation};
  renderLanguage();
})();
