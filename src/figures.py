"""Submission figures from saved model results; no route search or manual raster edits."""
from functools import lru_cache
from src.cluster_labels import area_title
import numpy as np,pandas as pd,geopandas as gpd,pyogrio
from src.analysis_io import inside,csv,gpkg,read_json,sha,digest,atomic_json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
from matplotlib.colors import LinearSegmentedColormap

NAVY='#213c53';MUTED='#73869a';ZERO='#b02b4c';LOW='#efb18f';ABOVE='#d5e2e3'
PALETTE=['#d69473','#72aaa7','#8ba4c8'];LIGHT='#f2f5f8';LINE='#c2cdd7'
SCORE_COLORS={0:ZERO,1:LOW,2:ABOVE,3:'#eeeef1'}

def setup():
    p=inside('assets/fonts/NotoSansKR.ttf');font_manager.fontManager.addfont(p)
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=p).get_name(),
        'axes.unicode_minus':False,'font.size':10,'text.color':NAVY,'axes.labelcolor':NAVY,
        'xtick.color':MUTED,'ytick.color':MUTED,'axes.titlecolor':NAVY,
        'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':LINE,
        'figure.facecolor':'white','axes.facecolor':'white','legend.frameon':False})

def save(ctx,fig,path,caption,layout=True):
    from io import BytesIO
    path=inside(path);path.parent.mkdir(parents=True,exist_ok=True)
    fig.text(.035,.012,caption,fontsize=8,color=MUTED,va='bottom')
    if layout:fig.tight_layout(rect=[.015,.075,.985,.97])
    buffer=BytesIO()
    fig.savefig(buffer,format='png',dpi=ctx.config['dpi'],facecolor='white',bbox_inches='tight',pad_inches=.16)
    plt.close(fig)
    content=buffer.getvalue()
    # Report-only updates need not overwrite unchanged figures open in a viewer.
    if path.exists() and path.read_bytes()==content:return
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_bytes(content);temporary.replace(path)

@lru_cache(maxsize=1)
def boundaries():
    file=inside('data/processed/boundaries.gpkg')
    return (pyogrio.read_dataframe(file,layer='goyang_boundary'),pyogrio.read_dataframe(file,layer='goyang_dong'))

def map_base(ax,bounds=None):
    city,dong=boundaries()
    city.plot(ax=ax,color=LIGHT,edgecolor=LINE,linewidth=.7,zorder=0)
    dong.boundary.plot(ax=ax,color=LINE,linewidth=.45,zorder=1)
    if bounds is None:
        x0,y0,x1,y1=city.total_bounds;pad=(x1-x0)*.035;bounds=(x0-pad,y0-pad,x1+pad,y1+pad)
    ax.set_xlim(bounds[0],bounds[2]);ax.set_ylim(bounds[1],bounds[3]);ax.set_aspect('equal');ax.set_axis_off()
    return bounds

def compass_scale(ax):
    ax.annotate('N',xy=(.95,.94),xytext=(.95,.84),xycoords='axes fraction',ha='center',fontsize=7,
                arrowprops={'arrowstyle':'-|>','color':NAVY,'lw':.8})
    x0,x1=ax.get_xlim();y0,y1=ax.get_ylim();span=x1-x0
    length=5000 if span>24000 else 1000 if span>4500 else 500
    x=x0+span*.06;y=y0+(y1-y0)*.055
    ax.plot([x,x+length],[y,y],color=NAVY,lw=1.4,zorder=10)
    ax.text(x,y+(y1-y0)*.014,f'{length/1000:g} km' if length>=1000 else '500 m',fontsize=7,color=MUTED,zorder=10)

def classes(score,threshold):
    a=np.asarray(score,dtype=float)
    return np.select([~np.isfinite(a),a<=1e-10,a<=threshold+1e-10],[3,0,1],default=2)

def score_map(ax,frame,threshold,outline=None):
    frame.plot(ax=ax,color=[SCORE_COLORS[x] for x in classes(frame.score,threshold)],edgecolor='white',linewidth=.35,zorder=3)
    if outline is not None:outline.boundary.plot(ax=ax,color=NAVY,linewidth=1.05,zorder=4)

def score_legend(fig,threshold,y=.045):
    fig.legend(handles=[Patch(facecolor=ZERO,label='평균 0곳'),Patch(facecolor=LOW,label=f'0곳 초과 ~ {threshold:.2f}곳 이하'),
        Patch(facecolor=ABOVE,label='기준 초과'),Patch(facecolor=LIGHT,edgecolor=LINE,label='배경 지역')],
        loc='lower center',bbox_to_anchor=(.5,y),ncol=4,fontsize=9,handlelength=1.4)

def accessibility_distribution(ctx,grid):
    """Show the full Step 6 score range, independently of low-access clustering."""
    setup()
    valid=grid[grid.score_status.eq('valid')&grid.population.gt(0)&np.isfinite(grid.score)].copy()
    if valid.empty:raise ValueError('No valid 500m accessibility scores to map.')
    assert valid.score.ge(0).all()
    # Fixed score intervals, not quantiles; zero and unavailable scores stay distinct.
    breaks=np.array([0.,5.,15.,30.,60.])
    colors=['#df9fae','#f0c5aa','#f3dfb6','#c4ded9','#8dbbb6','#568f94']
    labels=['0곳','0곳 초과 ~ 5곳 이하','5곳 초과 ~ 15곳 이하',
            '15곳 초과 ~ 30곳 이하','30곳 초과 ~ 60곳 이하','60곳 초과']
    bins=np.searchsorted(breaks,valid.score.to_numpy(),side='left')
    unavailable=grid[grid.population.gt(0)&~grid.index.isin(valid.index)]
    fig=plt.figure(figsize=(13,11.5))
    fig.text(.04,.965,'고양시 전체 의료접근성 점수 분포',fontsize=22,fontweight='bold',va='top')
    fig.text(.04,.924,f'{ctx.config["baseline_budget_min"]}분 이내 도달 가능한 의료기관 수의 평균  |  고령인구 가중 500m 격자',fontsize=11,color=MUTED)
    stats=[('유효 500m 격자',f'{len(valid):,}개'),('점수 0인 격자',f'{valid.score.eq(0).sum():,}개'),
           ('격자 점수 중앙값',f'{valid.score.median():.2f}곳'),('최대 점수',f'{valid.score.max():.2f}곳')]
    for x,(label,value) in zip([.04,.28,.52,.76],stats):
        fig.text(x,.88,label,fontsize=10,color=MUTED)
        fig.text(x,.85,value,fontsize=16,fontweight='bold')
    ax=fig.add_axes([.035,.205,.93,.62]);map_base(ax)
    valid.plot(ax=ax,color=[colors[i] for i in bins],edgecolor='white',linewidth=.3,zorder=3)
    if len(unavailable):
        unavailable.plot(ax=ax,facecolor='white',edgecolor=MUTED,hatch='////',linewidth=.5,zorder=4)
    compass_scale(ax)
    fig.text(.5,.179,'의료접근성 점수 · 평균 도달 의료기관 수 (곳)',ha='center',fontsize=11,fontweight='bold')
    handles=[Patch(facecolor=c,label=label) for c,label in zip(colors,labels)]
    # Matplotlib fills columns first; reorder so the two rows read low to high.
    fig.legend(handles=[handles[i] for i in [0,3,1,4,2,5]],loc='lower center',
               bbox_to_anchor=(.5,.108),ncol=3,fontsize=10,handlelength=1.8,columnspacing=2.8,labelspacing=.85)
    fig.legend(handles=[Patch(facecolor='white',edgecolor=MUTED,hatch='////',label='점수 산정 제외'),
                        Patch(facecolor=LIGHT,edgecolor=LINE,label='배경 지역')],
               loc='lower center',bbox_to_anchor=(.5,.074),ncol=2,fontsize=9,columnspacing=2.8)
    fig.text(.04,.055,'고정된 점수 구간으로 전체 분포를 표현 · 군집 선정용 하위 30% 분류와는 별개',fontsize=9,color=MUTED)
    fig.text(.04,.036,'0곳은 모든 출발시각에서 도달 기관이 없는 경우 · 빗금은 점수를 산정하지 않은 격자이며 0곳과 구분',fontsize=9,color=MUTED)
    save(ctx,fig,ctx.step(6)/'figures/accessibility_distribution.png',
         f'08:30–17:00 매분 511시각 평균 · 보행속도 {ctx.config["baseline_speed_mps"]:g}m/s · 연속보행 10분 · 기관 수는 진료용량이 아님 · EPSG:5179',layout=False)


def overview(ctx,grid,clusters):
    setup();threshold=read_json(ctx.step(7)/'cluster_qa.json')['threshold'];top=clusters[clusters.is_top3].sort_values('rank')
    fig,axes=plt.subplots(1,2,figsize=(15,8));fig.suptitle('의료접근성이 낮고 고령인구가 집중된 지역',x=.035,ha='left',fontsize=19,fontweight='bold')
    for ax in axes:map_base(ax)
    valid=grid[grid.score.notna()&grid.population.gt(0)];score_map(axes[0],valid,threshold,top)
    axes[0].set_title('30분 접근성 · 같은 기준으로 구분',loc='left',fontsize=12,pad=16)
    grid[grid.population.gt(0)].plot(ax=axes[1],color='#e5eaef',edgecolor='white',linewidth=.25,zorder=2)
    member=pd.read_csv(ctx.step(7)/'tables/baseline_top3_membership.csv')
    for r,color in zip(top.itertuples(),PALETTE):
        f=grid[grid.gid.isin(member.loc[member.cluster_id.eq(r.cluster_id),'gid'])]
        f.plot(ax=axes[1],color=color,edgecolor='white',linewidth=.35,zorder=3)
        gpd.GeoSeries([r.geometry],crs=grid.crs).boundary.plot(ax=axes[1],color=NAVY,linewidth=1,zorder=4)
        p=r.geometry.representative_point()
        axes[1].annotate(f'{r.area_name}\n{r.population:,.0f}명 · 평균 {r.score:.2f}곳',(p.x,p.y),xytext=(0,18 if r.rank==2 else -20),
            textcoords='offset points',ha='center',fontsize=9,zorder=6,
            arrowprops={'arrowstyle':'-','color':NAVY,'lw':.7},bbox={'facecolor':'white','alpha':.95,'edgecolor':LINE,'pad':4})
    axes[1].set_title('하위 30% 중 고령인구 상위 3개 군집',loc='left',fontsize=12,pad=16)
    for ax in axes:compass_scale(ax)
    score_legend(fig,threshold,.045)
    save(ctx,fig,ctx.step(7)/'figures/accessibility_clusters.png',f'보행속도 {ctx.config["baseline_speed_mps"]:g}m/s · 500m 고령인구 가중평균 · 경계 동점 포함 · Queen 인접 · 윤곽은 군집 범위이며 행정동 전체가 아님')

def grid_scenarios(ctx):
    """Aggregate saved baseline-speed OD arrays to time-budget map grids; never reroute."""
    baseline_speed=ctx.config['baseline_speed_mps'];baseline_budget=ctx.config['baseline_budget_min']
    budgets=sorted(set(ctx.config['sensitivity_budgets_min']+[baseline_budget]))
    sources=[(ctx.step(8)/'extended_checkpoint.parquet',budgets,'budget')]
    key=digest({'version':4,'baseline_speed':baseline_speed,'baseline_budget':baseline_budget,'budgets':budgets,
                'checkpoints':{p.name:sha(p) for p,_,_ in sources},'grid':sha(ctx.step(6)/'accessibility.gpkg'),
                'membership':sha(ctx.step(7)/'tables/baseline_top3_membership.csv')})
    marker=ctx.cache/'figure_grid_data.json';table=ctx.step(8)/'tables/sensitivity_grid_scores.csv'
    if marker.exists() and read_json(marker).get('signature')==key and table.exists():
        names={name for name,_ in pyogrio.list_layers(ctx.step(8)/'sensitivity.gpkg')}
        expected={f'budget_{b}_grids' for b in budgets}
        if expected<=names:return pd.read_csv(table)
    small=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_250m').set_index('gid')
    large=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_500m').set_index('gid')
    membership=pd.read_csv(ctx.step(7)/'tables/baseline_top3_membership.csv').set_index('gid')
    rows=[]
    for cp,source_budgets,kind in sources:
        for r in pd.read_parquet(cp).itertuples():
            source=small.loc[r.gid]
            with np.load(inside(r.path)) as z:
                od=z['od'];upper=z['upper_counts'];saved_budgets=z['budgets']
                for b in source_budgets:
                    count=(od<=b*60+1e-8).sum(axis=1);j=int(np.flatnonzero(saved_budgets==b)[0])
                    rows.append({'scenario':f'budget_{b}','kind':'budget','value':b,'gid':source.parent_gid,'population':source.population,
                                 'weighted_score':float(count.mean())*source.population,'valid':not np.any(upper[:,j]>count)})
    raw=pd.DataFrame(rows);result=[]
    for (scenario,kind,value,gid),part in raw.groupby(['scenario','kind','value','gid']):
        parent=large.loc[gid];ok=bool(part.valid.all() and abs(part.population.sum()-parent.population)<1e-6)
        result.append(dict(scenario=scenario,kind=kind,value=value,gid=gid,cluster_id=membership.loc[gid,'cluster_id'],population=parent.population,
                           score=part.weighted_score.sum()/parent.population if ok else np.nan))
    f=pd.DataFrame(result);base=f[f.scenario.eq(f'budget_{baseline_budget}')].copy();assert np.allclose(base.score,base.gid.map(large.score),equal_nan=True)
    csv(f,table)
    file=ctx.step(8)/'sensitivity.gpkg'
    spatial={name:pyogrio.read_dataframe(file,layer=name) for name,_ in pyogrio.list_layers(file) if name.startswith('cutoff_')}
    for name,part in f.groupby('scenario'):spatial[name.replace('.','_')+'_grids']=large[['geometry']].reset_index().merge(part,on='gid')
    gpkg(file,spatial);atomic_json(marker,{'signature':key});return f

def budget_atlas(ctx,values,data,summary,filename,title,subtitle):
    setup();top=summary[summary.is_top3].sort_values('rank');large=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_500m')
    membership=pd.read_csv(ctx.step(7)/'tables/baseline_top3_membership.csv');threshold=read_json(ctx.step(7)/'cluster_qa.json')['threshold']
    n=len(values);fig=plt.figure(figsize=(5*n,14));fig.text(.035,.975,title,fontsize=21,fontweight='bold',va='top');fig.text(.035,.944,subtitle,fontsize=10,color=MUTED)
    for row,r in enumerate(top.itertuples()):
        top_y=.90-row*.272;fig.text(.035,top_y,area_title(r.area_name),fontsize=15,fontweight='bold')
        fig.text(.96,top_y,f'고령인구 {r.population:,.0f}명 · 기준 격자 {r.grid_count}개',ha='right',fontsize=10,color=MUTED)
        local=large[large.gid.isin(membership.loc[membership.cluster_id.eq(r.cluster_id),'gid'])]
        x0,y0,x1,y1=local.total_bounds;pad=max(x1-x0,y1-y0)*.09;bounds=(x0-pad,y0-pad,x1+pad,y1+pad)
        for col,value in enumerate(values):
            left=.035+col*.93/n;width=.86/n;bottom=top_y-.205
            ax=fig.add_axes([left,bottom,width,.18]);map_base(ax,bounds)
            scenario=f'budget_{int(value)}'
            part=data[data.scenario.eq(scenario)&data.cluster_id.eq(r.cluster_id)]
            f=local[['gid','geometry']].merge(part,on='gid',validate='one_to_one')
            assert len(f)==len(local)
            score_map(ax,f,threshold,gpd.GeoSeries([r.geometry],crs=local.crs));compass_scale(ax)
            panel_title=f'{value:g}분'
            ax.set_title(panel_title,fontweight='bold',fontsize=13,pad=8)
            low=f.score.le(threshold+1e-10)&f.score.notna();pop=float(f.loc[low,'population'].sum());ratio=pop/r.population
            mean=float((f.score*f.population).sum()/r.population) if f.score.notna().all() else np.nan
            bar=fig.add_axes([left+width*.12,bottom-.029,width*.76,.006]);bar.barh(0,1,color=ABOVE);bar.barh(0,ratio,color=ZERO);bar.set_xlim(0,1);bar.set_axis_off()
            fig.text(left+width/2,bottom-.017,f'{pop:,.0f}명 · {ratio:.1%}',ha='center',fontsize=11,color=ZERO,fontweight='bold')
            fig.text(left+width/2,bottom-.043,f'저접근 {low.sum()}/{len(f)}격자 · 평균 {mean:.2f}곳',ha='center',fontsize=8.5,color=MUTED)
    score_legend(fig,threshold,.061)
    fig.text(.035,.052,f'저접근 기준: 기본 30분 점수의 하위 30% 경계 {threshold:.4f}곳을 모든 패널에 고정',fontsize=9,color=MUTED)
    fig.text(.035,.034,'색 = 격자 접근성  |  막대 = 해당 군집 고령인구 중 저접근 격자 거주 비율  |  기준 초과는 의료접근이 충분하다는 판정이 아님',fontsize=9,color=MUTED)
    save(ctx,fig,ctx.step(8)/'figures'/filename,'08:30–17:00 매분 511시각 평균 · 기준 군집의 격자·인구 고정 · 지역별 확대율은 다름 · EPSG:5179',layout=False)

def cutoff_maps(ctx,summary):
    setup();file=ctx.step(8)/'sensitivity.gpkg';fig,axes=plt.subplots(1,3,figsize=(16,6.2))
    fig.suptitle('저접근 기준을 바꾸면 군집은 어떻게 달라지는가',x=.035,ha='left',fontsize=20,fontweight='bold')
    for ax,q in zip(axes,ctx.config['cutoffs']):
        map_base(ax);low=pyogrio.read_dataframe(file,layer=f'cutoff_{int(q*100)}_grids');cs=pyogrio.read_dataframe(file,layer=f'cutoff_{int(q*100)}_clusters').sort_values('rank')
        low.plot(ax=ax,color='#e1e7ec',edgecolor='white',linewidth=.25,zorder=2)
        for r,color in zip(cs[cs.is_top3].itertuples(),PALETTE):
            f=low[low.cluster_id.eq(r.cluster_id)];f.plot(ax=ax,color=color,edgecolor='white',linewidth=.3,zorder=3)
            gpd.GeoSeries([r.geometry],crs=cs.crs).boundary.plot(ax=ax,color=NAVY,linewidth=.9,zorder=4)
            p=r.geometry.representative_point();ax.annotate(r.area_name,(p.x,p.y),xytext=(0,23 if r.rank==2 else -22),textcoords='offset points',ha='center',fontsize=7.5,
                arrowprops={'arrowstyle':'-','color':NAVY,'lw':.6},bbox={'facecolor':'white','alpha':.95,'edgecolor':'none','pad':2},zorder=6)
        ax.set_title(f'하위 {q:.0%}',fontsize=15,fontweight='bold');compass_scale(ax)
        ax.text(.5,-.06,f'상위 3개 군집 고령인구 {cs.loc[cs.is_top3,"population"].sum():,.0f}명',transform=ax.transAxes,ha='center',fontsize=10,color=MUTED)
    fig.legend(handles=[Patch(facecolor=c,edgecolor=NAVY,label=f'고령인구 {i}순위') for i,c in enumerate(PALETTE,1)]+[Patch(facecolor='#e1e7ec',label='그 외 저접근 격자')],loc='lower center',bbox_to_anchor=(.5,.052),ncol=4)
    save(ctx,fig,ctx.step(8)/'figures/04_cutoff_cluster_maps.png',f'보행속도 {ctx.config["baseline_speed_mps"]:g}m/s · 전체 유효 500m 격자에서 재군집 · 경계 동점 포함 · 같은 지도 범위 · 색은 순위이며 서로 같은 군집을 뜻하지 않음')

def charts(ctx,summary):
    setup();profiles=pd.read_parquet(ctx.step(8)/'sensitivity_minute_profiles.parquet');top=summary[summary.is_top3].sort_values('rank')
    budgets=ctx.config['sensitivity_budgets_min'];colors=[ZERO,'#d6906a','#6c989a']
    displayed=profiles[profiles.cluster_id.isin(top.cluster_id)&profiles.scenario.isin([f'budget_{b}' for b in budgets])]
    profile_upper=max(1.,float(displayed['count'].max())*1.08)
    fig,axes=plt.subplots(3,1,figsize=(13,10),sharex=True,sharey=True)
    fig.suptitle('출발시각에 따른 의료접근성',x=.035,ha='left',fontsize=20,fontweight='bold')
    for ax,r in zip(axes,top.itertuples()):
        for b,color in zip(budgets,colors):
            f=profiles[profiles.cluster_id.eq(r.cluster_id)&profiles.scenario.eq(f'budget_{b}')];ax.plot(f.departure_s/3600,f['count'],color=color,lw=1.2,label=f'{b}분')
        ax.set_title(r.area_name,loc='left',fontweight='bold');ax.grid(axis='y',color='#e5eaf0');ax.set_axisbelow(True);ax.legend(ncol=3);ax.set_ylabel('평균 기관 수 (곳)');ax.set_ylim(0,profile_upper)
    axes[-1].set_xlim(8.5,17);axes[-1].set_xlabel('출발시각 (시)')
    save(ctx,fig,ctx.step(8)/'figures/02_time_budget_profiles.png',f'같은 기준 군집의 고령인구로 가중 · 보행속도 {ctx.config["baseline_speed_mps"]:g}m/s · 시간예산만 변경')
    ov=pd.read_csv(ctx.step(8)/'tables/top3_overlap.csv');cw=pd.read_csv(ctx.step(8)/'tables/cluster_crosswalk.csv');fig,axes=plt.subplots(1,2,figsize=(15,6.5));x=np.arange(len(ov))
    axes[0].bar(x-.17,ov.grid_jaccard,.34,color='#89a8bc',label='격자 중첩');axes[0].bar(x+.17,ov.population_jaccard,.34,color=LOW,label='인구가중 중첩')
    for j,r in enumerate(ov.itertuples()):
        axes[0].text(j-.17,r.grid_jaccard+.025,f'{r.grid_jaccard:.1%}',ha='center',fontsize=9);axes[0].text(j+.17,r.population_jaccard+.025,f'{r.population_jaccard:.1%}',ha='center',fontsize=9)
    axes[0].set_xticks(x,[f'하위 {r.cutoff:.0%}' for r in ov.itertuples()]);axes[0].set_ylim(0,1.16);axes[0].set_ylabel('기준 상위 3개 군집과의 Jaccard');axes[0].legend(loc='upper left');axes[0].set_title('선정 범위의 중첩',loc='left',fontweight='bold')
    for j,r in enumerate(top.itertuples()):
        vals=[]
        for q in ov.cutoff:
            f=cw[cw.baseline_cluster.eq(r.cluster_id)&cw.cutoff.eq(q)&cw.scenario_rank.le(3)];vals.append(f.shared_population.sum()/r.population)
        axes[1].plot(ov.cutoff*100,vals,marker=['o','s','^'][j],linestyle=['-','--',':'][j],label=r.area_name,color=PALETTE[j],lw=2,alpha=.85)
    axes[1].set_ylim(0,1.1);axes[1].set_xticks([25,30,35],['하위 25%','하위 30%','하위 35%']);axes[1].set_ylabel('기준 군집 인구의 상위 3개 포함 비율');axes[1].set_title('기준 군집별 유지 비율',loc='left',fontweight='bold');axes[1].legend(loc='lower right',fontsize=8);axes[1].grid(axis='y',alpha=.15)
    save(ctx,fig,ctx.step(8)/'figures/05_cutoff_top3_overlap.png','군집 번호가 아닌 실제 구성 격자로 비교 · Jaccard = 교집합 / 합집합')

def render_all(ctx):
    from src.input_figures import render
    render(ctx)
    large=pyogrio.read_dataframe(ctx.step(6)/'accessibility.gpkg',layer='accessibility_500m');summary=pyogrio.read_dataframe(ctx.step(7)/'clusters.gpkg',layer='cluster_summary')
    accessibility_distribution(ctx,large);overview(ctx,large,summary);data=grid_scenarios(ctx)
    speed=ctx.config['baseline_speed_mps']
    budget_values=ctx.config['sensitivity_budgets_min']
    budget_atlas(ctx,budget_values,data,summary,'01_time_budget_top3.png','시간예산에 따른 저접근 지역의 변화',f'시간예산 {"·".join(map(str,budget_values))}분  |  보행속도 {speed:g}m/s  |  같은 군집·인구·저접근 경계 유지')
    cutoff_maps(ctx,summary);charts(ctx,summary)
    from src.diagnostic_figures import render_diagnostics
    render_diagnostics(ctx,summary)
