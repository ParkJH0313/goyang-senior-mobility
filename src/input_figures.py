"""Whole-step input/network maps; no per-candidate review-image proliferation."""
import numpy as np,pyogrio
from src.analysis_io import inside
from src.figures import setup,save,NAVY,MUTED,LOW,PALETTE,LinearSegmentedColormap
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def decorate(ax):
    ax.set_aspect('equal');ax.set_axis_off()
    ax.annotate('N',xy=(.95,.94),xytext=(.95,.85),xycoords='axes fraction',ha='center',arrowprops={'arrowstyle':'->','color':'#333'})
    x0,x1=ax.get_xlim();y0,y1=ax.get_ylim();x=x0+(x1-x0)*.06;y=y0+(y1-y0)*.05
    length=5000 if x1-x0>20000 else 1000
    ax.plot([x,x+length],[y,y],color='#333',lw=2);ax.text(x+length/2,y+(y1-y0)*.012,f'{length/1000:g} km',ha='center',fontsize=8)


def render(ctx):
    setup();plt.rcParams.update({'axes.titlesize':16,'axes.titleweight':'bold'});boundary=pyogrio.read_dataframe(inside('data/processed/boundaries.gpkg'),layer='goyang_boundary')
    large=pyogrio.read_dataframe(ctx.step(1)/'population.gpkg',layer='population_500m')
    fig,ax=plt.subplots(figsize=(10,9));boundary.plot(ax=ax,color='#f2f5f8',edgecolor='#c2cdd7',linewidth=.7)
    large[large.population>0].plot(ax=ax,column='population',cmap=LinearSegmentedColormap.from_list('population',['#f3eee7','#efb18f','#d68a67']),legend=True,legend_kwds={'label':'500m 고령인구 (명)','shrink':.6},edgecolor='white',linewidth=.15)
    ax.set_title('고양시 고령인구 분포 · 500m 격자');decorate(ax)
    save(ctx,fig,ctx.step(1)/'figures/population_500m.png','공동 추정 고령인구 · 원래 500m 격자 · EPSG:5179')
    origins=pyogrio.read_dataframe(ctx.step(2)/'origins.gpkg',layer='origins_250m')
    fig,ax=plt.subplots(figsize=(10,9));boundary.plot(ax=ax,color='#f2f5f8',edgecolor='#c2cdd7',linewidth=.7)
    for method,color,label in [('residential_area_centroid','#659b9d','주거 면적 중심'),('provisional_grid_centroid','#d69473','주거 없음: 잠정 격자 중심')]:
        f=origins[origins.origin_method.eq(method)];f.plot(ax=ax,color=color,markersize=7 if method.startswith('residential') else 16,label=f'{label} ({len(f):,}점)')
    ax.legend(loc='upper left');ax.set_title('250m 대표점의 산정 방식과 분포');decorate(ax)
    save(ctx,fig,ctx.step(2)/'figures/origins_overview.png','출발점 하나에 해당 격자 고령인구 전체 적용 · 주거 건물 수/면적으로 인구 재배분하지 않음')
    facilities=pyogrio.read_dataframe(ctx.step(3)/'facilities.gpkg',layer='facilities')
    surrounding=pyogrio.read_dataframe(inside('data/processed/boundaries.gpkg'),layer='surrounding_sigungu')
    fig,ax=plt.subplots(figsize=(10,10));surrounding.plot(ax=ax,color='#f2f5f8',edgecolor='white');boundary.plot(ax=ax,color='#e4eef0',edgecolor='#659b9d')
    for flag,color,label in [(1,'#659b9d','고양시'),(0,'#d69473','주변 지정 지역')]:
        f=facilities[facilities.is_goyang.eq(flag)];f.plot(ax=ax,color=color,markersize=11,label=f'{label} {len(f):,}기관')
    ax.legend(loc='upper left');ax.set_title('분석 대상 의료기관과 도착 위치');decorate(ax)
    save(ctx,fig,ctx.step(3)/'figures/facilities_overview.png','기관 ID별 1곳 · 내과 또는 정형외과 전문의 자격 · 주소 기반 도착 대리점 포함')
    bbox=tuple(boundary.geometry.buffer(3000).total_bounds)
    edges=pyogrio.read_dataframe(inside('data/processed/osm_walk_network.gpkg'),layer='edges',columns=['segment_id'],bbox=bbox).drop_duplicates('segment_id')
    stops=pyogrio.read_dataframe(ctx.step(4)/'network.gpkg',layer='stops',bbox=bbox)
    joins=pyogrio.read_dataframe(ctx.step(4)/'network.gpkg',layer='network_corrections')
    fig,ax=plt.subplots(figsize=(11,9));edges.plot(ax=ax,color='#c2cbd0',linewidth=.25)
    s=stops[stops.connection_status.eq('connected')&~stops.is_rail.astype(bool)];s.plot(ax=ax,color='#72aaa7',markersize=2)
    r=stops[stops.connection_status.eq('connected')&stops.is_rail.astype(bool)];r.plot(ax=ax,color='#d69473',markersize=22,marker='s')
    j=joins[joins.geometry.geom_type.eq('LineString')];j.plot(ax=ax,color='#d69473',linewidth=1.2)
    boundary.boundary.plot(ax=ax,color='#213c53',linewidth=.8);ax.set_xlim(bbox[0],bbox[2]);ax.set_ylim(bbox[1],bbox[3])
    ax.legend(handles=[Line2D([],[],color='#c2cbd0',label='거리 기반 보행망'),Line2D([],[],marker='o',ls='',color='#72aaa7',label='접속된 버스정류장'),Line2D([],[],marker='s',ls='',color='#d69473',label='접속된 철도역'),Line2D([],[],color='#d69473',label='공용 보행 연결')],loc='upper left')
    ax.set_title('고양시와 주변 접속망 통합 결과');decorate(ax)
    save(ctx,fig,ctx.step(4)/'figures/network_overview.png','지도: 고양시 경계+3km 주변 · 실제 시간표 경유 범위를 이 지도 경계로 제한하지 않음')
