"""Cluster diagnosis figures rendered exclusively from Step9 tables and spatial layers."""
import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from src.figures import setup, save, boundaries, map_base, compass_scale, NAVY, MUTED, ZERO, LIGHT, LINE
from src.cluster_diagnostics import STATUS_ORDER, WALK_BANDS

STATUS_LABELS = {'within_budget':'30분 이내 도달','first_walk_blocked':'첫 보행 불가',
                 'over_budget':'30분 초과~80분 도달','no_route':'80분 내 미도달','unresolved':'자료 미해결'}
STATUS_COLORS = dict(zip(STATUS_ORDER,['#85b5ad','#b44662','#e6af82','#a9b5c3','#e4dfeb']))
WALK_COLORS = dict(zip(WALK_BANDS,['#b8d6d5','#f4deb7','#edc6b3','#dfa0b1','#c3c5ce']))
TIME_COLS = ['walk_s','wait_s','in_vehicle_s','preparation_s']
TIME_LABELS = ['보행 · 구간 합계','대기','차내 이동','환승 준비']
TIME_COLORS = ['#8dadbd','#efb191','#8fb5a9','#ad9bc0']


def number(value):
    return f'{value:,.0f}' if np.isclose(value,round(value)) else f'{value:,.1f}'


def arrival_figure(ctx, cluster, states, means, origin_count, axis_limit):
    f=states.set_index('arrival_status');m=means.set_index('arrival_status')
    fig=plt.figure(figsize=(18,11.7));name=cluster.area_name.replace('동','')
    fig.text(.035,.962,f'{name} 군집의 30분 초과·미도달 진단',fontsize=24,fontweight='bold')
    departures=int(states.departure_count.iloc[0])
    fig.text(.035,.933,f'보행속도 {ctx.config["baseline_speed_mps"]:g}m/s · 연속보행 10분 유지 · 같은 군집 {cluster.population:,.0f}명 · {origin_count}개 출발점 × {departures}개 출발시각',fontsize=12,color=MUTED)
    fig.text(.035,.875,'전체의 의료시설 도달 상태',fontsize=17,fontweight='bold')
    unmet=1-f.loc['within_budget','fraction']-f.loc['unresolved','fraction']
    fig.text(.965,.875,f'30분 내 미도달 {unmet:.1%}',ha='right',fontsize=18,fontweight='bold',color=ZERO)
    if f.loc['unresolved','fraction']>0:
        fig.text(.965,.85,f'별도 자료 미해결 {f.loc["unresolved","fraction"]:.1%}',ha='right',color=MUTED)
    ax=fig.add_axes([.035,.725,.93,.12]);left=0;small_i=0
    for status in STATUS_ORDER:
        value=f.loc[status,'fraction']
        if not value:continue
        ax.barh(0,value,left=left,height=.72,color=STATUS_COLORS[status],edgecolor='white',linewidth=1.5)
        if value>=.075:
            ax.text(left+value/2,0,f'{STATUS_LABELS[status]}\n{value:.1%}',ha='center',va='center',fontsize=13,
                    fontweight='bold',color='white' if status=='first_walk_blocked' else NAVY)
        else:
            ax.annotate(f'{STATUS_LABELS[status]} {value:.1%}',xy=(left+value/2,.37),xytext=(min(.995,left+value/2),.61+small_i*.24),
                ha='right',fontsize=10,color=MUTED,arrowprops={'arrowstyle':'-','color':MUTED,'lw':.7});small_i+=1
        left+=value
    ax.set_xlim(0,1);ax.set_ylim(-.48,.76);ax.set_axis_off()
    fig.text(.035,.687,'첫 보행 불가: 첫 정류장 접근과 의료시설 직접 보행이 모두 연속보행 10분 안에 불가',fontsize=11,color=MUTED)
    fig.text(.035,.658,'80분 내 미도달: 첫 보행은 가능하지만 탐색한 80분 안에는 도달 경로 없음',fontsize=11,color=MUTED)
    fig.text(.035,.594,'도달한 경로의 평균 시간 구성',fontsize=17,fontweight='bold')
    fig.text(.965,.594,'가장 빨리 도달하는 의료시설 기준',ha='right',fontsize=11,color=MUTED)
    ax=fig.add_axes([.20,.285,.71,.265])
    ax.set_xlim(0,axis_limit);ax.set_ylim(-.55,1.55);ax.set_yticks([1,0])
    ax.set_yticklabels([f'{STATUS_LABELS[s]}\n전체의 {m.loc[s,"fraction"]:.1%}' for s in ['within_budget','over_budget']],fontsize=11)
    ax.tick_params(axis='y',length=0,pad=14);ax.spines['left'].set_visible(False)
    ax.grid(axis='x',color='#e5ebf1');ax.set_axisbelow(True)
    for status,y in [('within_budget',1),('over_budget',0)]:
        row=m.loc[status];left=0
        if not np.isfinite(row.total_s):
            ax.text(1,y,'해당 도달 경로 없음',va='center',color=MUTED);continue
        for col,color in zip(TIME_COLS,TIME_COLORS):
            value=row[col]/60;ax.barh(y,value,left=left,color=color,height=.42,edgecolor='white',linewidth=.7)
            if value>=1.8:ax.text(left+value/2,y,f'{value:.1f}',ha='center',va='center',fontsize=13,fontweight='bold')
            left+=value
        ax.text(left+.6,y,f'{left:.1f}분',va='center',fontsize=14,fontweight='bold')
    ax.axvline(30,color=ZERO,ls='--',lw=1.3,zorder=0);ax.text(30,1.44,'30분 기준',ha='center',color=ZERO,fontsize=11)
    ax.set_xlabel('평균 소요시간 (분) · 세 군집 같은 축',fontsize=11,color=MUTED)
    fig.legend(handles=[Patch(facecolor=c,label=l) for c,l in zip(TIME_COLORS,TIME_LABELS)],
        loc='center',bbox_to_anchor=(.57,.229),ncol=4,fontsize=11)
    fig.patches.append(Rectangle((.035,.105),.93,.085,transform=fig.transFigure,facecolor=LIGHT,edgecolor='none',zorder=-1))
    a,b=m.loc['within_budget'],m.loc['over_budget']
    if np.isfinite(a.total_s) and np.isfinite(b.total_s):
        differences=[b[c]-a[c] for c in TIME_COLS];i=int(np.argmax(differences));col=TIME_COLS[i]
        fig.text(.05,.157,f'{TIME_LABELS[i]} 차이가 가장 큼: 평균 {a[col]/60:.1f}분 → {b[col]/60:.1f}분',fontsize=13,fontweight='bold')
        fig.text(.05,.125,f'30분 초과 경로의 대기 {b.wait_s/60:.1f}분 = 첫 탑승 대기 {b.initial_wait_s/60:.1f}분 + 환승 대기 {b.transfer_wait_s/60:.1f}분',fontsize=10.5,color=MUTED)
        fig.text(.955,.125,f'환승 준비 30분 이내 {a.preparation_s/60:.1f}분 / 초과 {b.preparation_s/60:.1f}분',ha='right',fontsize=10,color=MUTED)
    else:fig.text(.05,.146,'두 도달 그룹이 모두 있을 때 평균 시간 차이를 비교한다.',fontsize=12,color=MUTED)
    fig.text(.035,.071,'비율·평균: 고령인구 × 출발시각 가중(08:30–17:00 매분) · 전체 비율은 고유 인원 비율이 아님 · 반올림으로 합계 차이 가능',fontsize=9,color=MUTED)
    fig.text(.035,.047,'아래 막대: 80분 안에 도달한 경로의 조건부 평균 · 보행은 출발·환승·하차 후 구간의 합계이며 각 연속보행은 10분 이하',fontsize=9,color=MUTED)
    save(ctx,fig,ctx.step(9)/f'figures/arrival_diagnosis_{cluster.cluster_id}.png',
         '해석: 기준 대표점·보행망·시간표의 경로 진단 · 두 도달 그룹의 관측 차이이며 대기시간 개선 정책의 인과효과를 추정한 것은 아님',layout=False)


def walking_figure(ctx, cluster, walks, parents, stops, bands):
    fig=plt.figure(figsize=(18,11.7));name=cluster.area_name.replace('동','')
    fig.text(.035,.962,f'{name} 군집의 정류장 보행시간과 고령인구',fontsize=24,fontweight='bold')
    fig.text(.035,.933,f'색: 250m 출발 격자의 정류장까지 보행시간  |  숫자: 500m 격자의 고령인구  |  보행속도 {ctx.config["baseline_speed_mps"]:g}m/s · 보행시간 상한 없음',fontsize=11,color=MUTED)
    x0,y0,x1,y1=parents.total_bounds;pad=max(x1-x0,y1-y0)*.07;bounds=(x0-pad,y0-pad,x1+pad,y1+pad)
    ax=fig.add_axes([.035,.17,.59,.65]);map_base(ax,bounds)
    parents.plot(ax=ax,color='#f7f9fb',edgecolor='none',zorder=2)
    walks.plot(ax=ax,color=walks.band.map(WALK_COLORS),edgecolor='white',linewidth=.5,zorder=3)
    parents.boundary.plot(ax=ax,color=NAVY,linewidth=1,zorder=4)
    if len(stops):stops.plot(ax=ax,color=NAVY,markersize=10,edgecolor='white',linewidth=.4,zorder=5)
    for r in parents.itertuples():
        a,b,c,d=r.geometry.bounds
        ax.text((a+c)/2,b+(d-b)*.16,number(r.population)+'명',ha='center',va='center',fontsize=8.5,fontweight='bold',zorder=6,
            path_effects=[pe.withStroke(linewidth=2,foreground='white')])
    compass_scale(ax)
    # Keep the location inset outside the data map, including wide clusters.
    inset=fig.add_axes([.043,.835,.14,.075]);map_base(inset)
    gpd.GeoSeries([cluster.geometry],crs=parents.crs).plot(ax=inset,color='#b8d6d5',edgecolor=NAVY,linewidth=.6,zorder=3)
    inset.set_title('고양시 내 위치',fontsize=8,color=MUTED,pad=2)
    fig.text(.68,.865,'분석 대상',fontsize=14,fontweight='bold')
    fig.text(.68,.824,f'고령인구 {cluster.population:,.0f}명',fontsize=24,fontweight='bold')
    fig.text(.68,.79,f'500m 인구 격자 {len(parents)}개 · 250m 출발 격자 {len(walks)}개',fontsize=11,color=MUTED)
    fig.text(.68,.745,'보행시간 구간',fontsize=13,fontweight='bold')
    fig.text(.965,.745,'고령인구 · 비율',ha='right',fontsize=10.5,color=MUTED)
    for i,band in enumerate(WALK_BANDS[:4]):
        row=bands[bands.band.eq(band)].iloc[0];y=.64-i*.12
        fig.patches.append(Rectangle((.675,y),.295,.10,transform=fig.transFigure,facecolor='#f5f7fa',edgecolor='none',zorder=-1))
        fig.patches.append(Rectangle((.687,y+.061),.013,.021,transform=fig.transFigure,facecolor=WALK_COLORS[band],edgecolor='none'))
        fig.text(.71,y+.065,band.replace('~',' ~ '),fontsize=12,fontweight='bold')
        fig.text(.71,y+.026,f'{row.origin_count}개 출발 격자',fontsize=10.5,color=MUTED)
        fig.text(.955,y+.026,f'{row.population:,.1f}명 · {row.fraction:.1%}',ha='right',fontsize=12,fontweight='bold')
    over=walks[walks.walk_min.gt(10+1e-8)];missing=walks.walk_min.isna()
    fig.text(.68,.242,f'10분 초과 {over.population.sum():,.1f}명 · {over.population.sum()/cluster.population:.1%}',fontsize=15,color=ZERO,fontweight='bold')
    maximum=walks.walk_min.max();mx=f'{maximum:.1f}분' if np.isfinite(maximum) else '없음'
    fig.text(.68,.208,f'최장 최단보행시간 {mx} · 경로 미연결 {missing.sum()}개',fontsize=10.5,color=MUTED)
    if missing.any():fig.text(.68,.183,f'미연결 고령인구 {walks.loc[missing,"population"].sum():,.1f}명 (별도 분류)',fontsize=10,color=MUTED)
    handles=[Line2D([0],[0],marker='o',color='none',markerfacecolor=NAVY,markersize=5,label='최단보행 도착 정류장'),
        Patch(facecolor='#f7f9fb',edgecolor=LINE,label='색 없는 내부 격자: 분류 대상 출발점 없음'),
        Patch(facecolor='none',edgecolor=NAVY,label='500m 인구 격자 경계')]
    if missing.any():handles.append(Patch(facecolor=WALK_COLORS[WALK_BANDS[-1]],label='보행망 경로 없음'))
    fig.legend(handles=handles,loc='center',bbox_to_anchor=(.50,.128),ncol=3,fontsize=10)
    fig.text(.035,.082,'대상 선정: 총 이동시간 30분 · 연속보행 10분 조건의 하위 30%에서 선정한 군집 고정 · 군집은 행정동 전체가 아님',fontsize=9,color=MUTED)
    fig.text(.035,.055,'보행시간: 주거 대표점에서 평일 승차 운행기록이 있는 가장 가까운 버스정류장까지 · 방향성 보행망·접속선 사용 · 신호·휴식·배차 대기 제외',fontsize=9,color=MUTED)
    save(ctx,fig,ctx.step(9)/f'figures/bus_walk_population_{cluster.cluster_id}.png',
        '인구: 500m 격자값 표시, 추정 인구는 소수 유지 · 우측 인구는 250m 배분값 합산 · 이 지도는 보행 부담 진단이며 본 분석의 연속보행 10분 상한은 유지',layout=False)


def render_diagnostics(ctx, summary):
    setup();folder=ctx.step(9)
    states=pd.read_csv(folder/'tables/arrival_status.csv');means=pd.read_csv(folder/'tables/arrival_time_components.csv')
    bands=pd.read_csv(folder/'tables/bus_walk_population.csv')
    walks=pyogrio.read_dataframe(folder/'diagnosis.gpkg',layer='stop_walk_250m')
    parents=pyogrio.read_dataframe(folder/'diagnosis.gpkg',layer='diagnostic_population_500m')
    stops=pyogrio.read_dataframe(folder/'diagnosis.gpkg',layer='nearest_boarding_stops')
    maximum=means.total_s.max()/60
    axis_limit=max(40.,10*np.ceil((maximum+5)/10)) if np.isfinite(maximum) else 40.
    for r in summary[summary.is_top3].sort_values('rank').itertuples():
        selected=walks[walks.cluster_id.eq(r.cluster_id)]
        arrival_figure(ctx,r,states[states.cluster_id.eq(r.cluster_id)],means[means.cluster_id.eq(r.cluster_id)],len(selected),axis_limit)
        walking_figure(ctx,r,selected,parents[parents.cluster_id.eq(r.cluster_id)],stops[stops.cluster_id.eq(r.cluster_id)],bands[bands.cluster_id.eq(r.cluster_id)])
