"""Research-facing report and stage documentation; independent of route computation."""
from html import escape
from src.cluster_labels import FEATURED_REGION,cluster_title
import numpy as np,pandas as pd,pyogrio
from src.analysis_io import inside,read_json,atomic_json,sha
TITLES=['인구와 가중치','주거 대표점과 보행 접속','의료기관과 도착점','정류장·철도·환승망','511개 출발시각 경로','접근성 집계','저접근 군집','민감도 비교','취약 원인 진단']
STEMS=['population','origins','facilities','network','routing','accessibility','clusters','sensitivity','diagnosis']
METHODS=[
'원래 250m·500m 격자와 공개·마스킹·빈값 상태를 유지하고 고령인구 및 부모·자식 가중치를 구성한다.',
'격자 내부 주거 합집합의 면적 중심을 출발점으로 산정한다. 주거 도형이 없으면 잠정 격자 중심을 사용하고 접속거리 전체를 보행비용에 포함한다.',
'대상 전문의 자격을 갖춘 의료기관을 기관 ID별로 구성하고 도착점과 보행망 사이의 접속선을 생성한다.',
'정류장·철도 출입구·지상 보행망을 연결한다. 접속거리와 역 내부 이동시간을 합산하고 방향 및 연속보행 한도를 적용한다.',
'08:30~17:00의 511개 출발시각에서 지정된 보행·탑승 조건에 따른 가장 빠른 의료기관 도착시간을 계산한다.',
'시각별 도달 의료기관 수를 평균하고 원래 고령인구를 가중치로 사용해 250m에서 500m로 집계한다.',
'유효 500m 점수의 하위 30%에 경계 동점을 포함한다. Queen 인접 군집을 구성하고 고령인구 합계로 상위 3개를 선정한다.',
'기준 보행속도와 상위 3개 군집의 격자·인구를 고정해 시간예산을 비교한다. 하위 비율 변경은 전체 유효 격자에서 다시 군집화한다.',
'군집별 보행·대기·차내·추가 탑승 준비시간을 집계한다. 도달 경로의 조건부 평균과 전체 인구·시각의 미도달 비중을 함께 제시한다.']
LAYERS={
'population_250m':'원래 250m 격자와 추정 고령인구·자료 상태.','population_500m':'250m 자식 인구를 합친 원래 500m 격자.',
'origins_250m':'주거 면적 중심 또는 잠정 격자 중심점.','origin_connectors':'출발점 전용 접속선. 전체 길이를 시간으로 환산한다.',
'network_corrections':'원본 노드·구간 사이의 공용 보행 연결.','facilities':'대상 전문의 자격을 충족하는 기관 ID별 위치.',
'destination_connectors':'보행망에서 의료기관 도착점까지의 전용 접속선.','stop_access':'정류장·출입구의 접속선과 고정 내부 이동시간.',
'stops':'시간표 정류장과 접속 상태.','accessibility_250m':'511시각 평균 도달 기관 수와 점수 유효성.',
'accessibility_500m':'고령인구 가중 500m 접근성 점수.','low_access_500m':'하위 30% 격자와 군집 소속.',
'cluster_summary':'군집 합집합 도형, 인구·점수·순위.','cluster_diagnosis':'군집별 시간 성분과 미도달 비율.',
'stop_walk_250m':'기준 상위 군집의 250m 출발 격자. 평일 승차 가능한 버스정류장까지 방향성 보행망 최단시간이며 10분 상한을 적용하지 않은 진단값.',
'diagnostic_population_500m':'같은 군집의 원래 500m 격자와 고령인구. 250m 보행시간 위에 인구를 표시하는 기준 도형.',
'nearest_boarding_stops':'각 출발점에서 보행시간이 가장 짧은 평일 버스 승차 정류장. 군집별 중복은 유지한다.',
'diagnostic_routes':'표본 경로의 승하차 정류장 설명선. 실제 차량 궤적이 아니다.','reached_facilities':'군집의 도달 기회에 기여하는 기관.'}
COMMON={
1:'src/analysis_io.py: 입력 검증과 원자적 저장.',2:'src/spatial_network.py: 최근접 접속과 통행 조건.',
3:'src/spatial_network.py: 기관 도착점 접속.',4:'src/spatial_network.py · src/stop_access.py · src/walking.py: 접속 도형, 방향성 거리망, 연속보행.',
5:'src/router.py · src/timetable.py · src/routing_runner.py: 시간표 경로 탐색과 중단 재개.',
6:'src/aggregation.py: 시각 평균과 인구 가중 집계. src/figures.py의 accessibility_distribution: 전체 500m 접근성 점수 지도와 하단 범례.',7:'src/aggregation.py: 경계 동점·Queen 군집·인구 순위. src/cluster_labels.py: 표·지도·보고서의 지역명 통일.',
8:'src/aggregation.py · src/routing_runner.py: 시나리오 계산. src/figures.py: 저장된 OD의 500m 집계와 비교 지도.',
9:'src/path_diagnosis.py: 경로 성분 재구성. src/cluster_diagnostics.py: 도달 상태·조건부 평균 및 버스정류장 최단보행 계산. src/diagnostic_figures.py: 군집별 막대그래프·보행시간과 고령인구 지도.'}

def progress(ctx):
    rows=['# 분석 실행 상태','',f'상태: {ctx.state["status"]}','','결과: outputs/step01 ~ step09. 계산 재개: python run.py processed. 그림·보고서: python run.py report.','','| 단계 | 상태 |','|---|---|']
    rows += [f'| Step {n} {title} | {ctx.state["stages"].get(str(n),{}).get("status","대기")} |' for n,title in enumerate(TITLES,1)]
    path=inside('docs/분석_진행상태.md');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(rows)+'\n',encoding='utf-8')

def document_steps(ctx):
    for n,title in enumerate(TITLES,1):
        folder=ctx.step(n);lines=[f'# Step {n} {title}','',METHODS[n-1],'','## 코드 구성','',
        f'- steps/step{n:02d}_{STEMS[n-1]}.py: 입력 읽기 → 계산 → 표·공간자료 저장.','- '+COMMON[n],
        '- src/reporting.py: 결과 설명과 보고서 구성.','- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.','',
        '## 공간 레이어','','| 파일 / 레이어 | 객체 수 | 의미 |','|---|---:|---|']
        for p in sorted(folder.glob('*.gpkg')):
            for layer,_ in pyogrio.list_layers(p):
                meaning=LAYERS.get(layer,'해당 하위 비율에서 다시 선정한 격자·군집.' if layer.startswith('cutoff_') else '기준 군집의 시간예산별 500m 점수. 군집·인구를 고정했다.')
                lines.append(f'| {p.name} / {layer} | {pyogrio.read_info(p,layer=layer)["features"]:,} | {meaning} |')
        if not list(folder.glob('*.gpkg')):lines+=['','비공간 경로 단계다. 출발점과 기관은 Step2·3의 원본 ID로 연결한다.']
        lines+=['','## 결과 파일','']
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or p.name in {'README.md','completion.json'} or p.suffix=='.gpkg':continue
            purpose={'.csv':'수치 표. UTF-8 BOM.','.png':'전체 결과 지도·그래프.','.parquet':'정밀도·자료형을 유지한 계산표.','.npz':'압축 배열.','.json':'계산 구조 명세.'}.get(p.suffix,'분석 결과.')
            if 'checkpoint' in p.name:purpose='완료된 출발점과 상세 경로 배열 위치. 배열은 .cache/analysis에 보관한다.'
            lines.append(f'- {p.relative_to(folder).as_posix()}: {purpose}')
        lines+=['','## 결과 요약','']
        lines += [f'- {k}: {v}' for k,v in ctx.state['stages'][str(n)].get('summary',{}).items() if k not in {'necessary_review_stops','reference_tests','unresolved_stop_candidates'}]
        lines+=['','## 해석','','좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)다. 미도달 0과 자료가 불완전한 NaN은 구분한다.',
        '도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함된다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아니다.']
        if n>=5:lines+=['',f'기본 보행속도는 {ctx.config["baseline_speed_mps"]:g}m/s이고 시간예산은 {ctx.config["baseline_budget_min"]}분이다.']
        if n==6:lines+=['','figures/accessibility_distribution.png는 accessibility.gpkg의 accessibility_500m 레이어에서 유효 점수 전체를 그린다. 범례는 지도 아래에 두며 0 / 0 초과~5 / 5 초과~15 / 15 초과~30 / 30 초과~60 / 60 초과(곳)의 고정 구간이다. 이는 군집 선정용 하위 30% 구분과 별개이며 수치와 군집을 바꾸지 않는다. 점수 0은 모든 출발시각에서 도달 기관이 없는 경우다. 고령인구가 있지만 점수를 산정하지 않은 격자는 빗금으로 구분한다. 중앙값은 유효 500m 격자 점수의 중앙값이다.', 'python run.py processed는 분석 후 그림까지 생성하고, python run.py report는 저장된 결과로 그림과 보고서만 재생성한다.']
        if n==8:lines+=['','지도 경계는 기본 30분 점수의 하위 30% 경계로 고정한다. 시간예산은 30·40·50분만 비교하며 기준 군집을 바꾸지 않는다. 평균 0 / 0 초과~경계 / 경계 초과를 공통 색으로 표현한다.']
        if n==9:lines+=['','arrival_status.csv는 상호 배타적인 도달 상태의 인구·출발시각 가중 비율이다. 첫 보행 불가는 첫 정류장과 의료기관 직접 보행이 모두 10분 이내에 불가능한 경우다. 80분 내 미도달은 첫 보행은 가능하지만 탐색 한도 안에 도달하지 못한 경우다. 자료 미해결은 별도 분류한다.', 'arrival_time_components.csv는 30분 이내 도달 및 30분 초과~80분 도달 그룹별 시간 성분 평균이다. 전체 비율은 고유 인원 비율이 아니며, 두 그룹의 차이는 정책의 인과효과가 아니다.', 'nearest_bus_walk.csv와 bus_walk_population.csv는 보행시간 상한 없이 가장 가까운 평일 버스 승차 정류장을 찾은 결과 및 구간별 인구 집계다. 신호·휴식·배차 대기는 제외한다. 지도는 보행 부담 진단이고 본 접근성 계산의 연속보행 10분 조건을 변경하지 않는다. 500m 인구는 원래 격자값이며 구간별 인구는 250m 배분값으로 합산한다.']
        (folder/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def image_block(ctx,rel,title,description=''):
    assert (ctx.output/rel).exists()
    return f'<figure><figcaption><h3>{escape(title)}</h3><p>{escape(description)}</p></figcaption><a href="{rel}"><img src="{rel}" alt="{escape(title)}" loading="lazy"></a></figure>'

def finish(ctx):
    from src.figures import render_all
    from src.output_layout import remove_retired_products
    remove_retired_products(ctx);render_all(ctx);document_steps(ctx)
    top=pd.read_csv(ctx.step(7)/'tables/cluster_summary.csv');top=top[top.is_top3].sort_values('rank')
    coverage=pd.read_csv(ctx.step(6)/'tables/coverage_summary.csv');valid=coverage[coverage.score_status.eq('valid')];total=float(coverage.population.sum())
    qa=read_json(ctx.step(7)/'cluster_qa.json')
    cards=[('대상 고령인구',f'{total:,.0f}','명'),('접근성 유효 격자',f'{qa["valid_grids"]:,}','개 · 500m'),('분석 의료기관',f'{ctx.state["stages"]["3"]["summary"]["facilities"]:,}','곳'),('기준 저접근 군집',str(len(top)),'개')]
    head='''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>고양시 고령자 의료접근성 분석</title>
<style>
:root{--ink:#213c53;--muted:#73869a;--line:#dbe3e9;--rose:#b02b4c}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f3f6f8;color:var(--ink);font-family:"Malgun Gothic",system-ui,sans-serif;line-height:1.75}
main{max-width:1380px;margin:auto;padding:48px 40px}header{padding:22px 0 32px;border-bottom:2px solid var(--ink)}h1{font-size:36px;line-height:1.4;margin:10px 0}h2{font-size:26px;margin:0 0 14px}h3{font-size:19px;margin:0}.kicker{font-size:12px;letter-spacing:2px;color:var(--muted)}.lead{font-size:18px;color:var(--muted);max-width:980px}
nav{display:flex;gap:22px;flex-wrap:wrap;padding:16px 0;font-size:14px}a{color:#3a718a;text-decoration:none}a:hover{text-decoration:underline}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}.card{background:white;border:1px solid var(--line);padding:21px}.card span{display:block;color:var(--muted);font-size:13px}.card strong{font-size:32px}
section{background:white;border:1px solid var(--line);padding:30px;margin:22px 0;scroll-margin-top:20px}.method{display:grid;grid-template-columns:1fr 1fr;gap:12px 32px}.method div{padding:12px 0;border-bottom:1px solid var(--line)}.method b{display:block;font-size:13px;color:var(--muted)}
figure{margin:32px 0 12px}figure img{display:block;width:100%;height:auto}figcaption p,.sub{color:var(--muted);font-size:14px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:12px;text-align:right}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}thead{background:#f1f5f8}.finding{border-left:4px solid var(--rose);padding:12px 20px;background:#fcf7f5}
.download{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.file{padding:18px;border:1px solid var(--line)}.file p{margin:8px 0 0;font-size:13px}details{margin:18px 0}summary{cursor:pointer;font-weight:bold}footer{font-size:13px;color:var(--muted);padding:20px 0}
@media(max-width:800px){main{padding:20px 14px}section{padding:18px}.cards,.method{grid-template-columns:1fr 1fr}.download{grid-template-columns:1fr}h1{font-size:27px}table{font-size:11px}th,td{padding:8px}}
@media print{body{background:white}main{padding:0}nav{display:none}section{border:0;break-inside:avoid}figure{break-inside:avoid}.cards{gap:8px}}
</style></head><body><main>'''
    parts=[head,'<header><div class="kicker">GOYANG · SENIOR MEDICAL ACCESSIBILITY</div><h1>고양시 고령자의 대중교통 의료접근성</h1><p class="lead">의료기관에 도달할 수 있는 기회의 공간적 차이를 살펴보고, 접근성이 낮으면서 고령인구가 집중된 지역의 이동부담을 분석한다.</p></header>',
    '<nav><a href="#method">분석 조건</a><a href="#baseline">접근성·군집</a><a href="#sensitivity">민감도</a><a href="#diagnosis">취약 원인</a><a href="#files">결과 자료</a></nav>',
    '<div class="cards">'+''.join(f'<div class="card"><span>{a}</span><strong>{b}</strong> {c}</div>' for a,b,c in cards)+'</div>',
    '<section id="method"><h2>분석 조건</h2><div class="method">']
    methods=[('지표','30분 이내 도달 가능한 의료기관 수의 평균'),('출발시각','08:30–17:00, 매분 511개 시각'),('공간 집계','250m에서 계산 → 고령인구 가중 500m 집계'),
    ('이동 조건',f'{ctx.config["baseline_speed_mps"]:g}m/s · 연속보행 10분 · 최대 3회 탑승'),('교통수단','시내·마을버스, 도시철도 및 일반철도'),('군집 선정','하위 30%·경계 동점 포함 · Queen 인접 · 고령인구 상위 3개')]
    parts += [f'<div><b>{a}</b>{b}</div>' for a,b in methods]
    parts+=['</div><p class="sub">고양시와 지정된 주변 지역의 내과 또는 정형외과 전문의가 있는 기관을 대상으로 한다. 기관 수는 진료용량이나 진료시간까지 고려한 공급량은 아니다.</p></section>',
    '<section id="baseline"><h2>접근성과 고령인구 집중 지역</h2>',
    image_block(ctx,'step06/figures/accessibility_distribution.png','고양시 전체 의료접근성 점수','30분 이내 평균 도달 의료기관 수를 500m 격자별로 표시했다. 지도 아래 범례는 실제 점수 구간이며, 점수 산정 제외와 0곳을 구분한다.'),
    image_block(ctx,'step07/figures/accessibility_clusters.png','기준 접근성과 상위 저접근 군집','공통 분류와 별도 군집 색으로 접근성 수준과 선정 범위를 구분했다.'),
    top[['rank','area_name','population','score','grid_count']].rename(columns={'rank':'인구 순위','area_name':'지역명','population':'고령인구(명)','score':'평균 기관 수(곳)','grid_count':'500m 격자 수'}).to_html(index=False,border=0,float_format=lambda x:f'{x:,.2f}'),
    f'<p class="sub">저접근 경계는 {qa["threshold"]:.4f}곳이다. 군집명은 구성 지역을 설명하는 명칭이며 행정동 전체를 뜻하지 않는다. 유효 점수의 고령인구 비중은 {float(valid.population.sum())/total:.3%}다.</p></section>',
    '<section id="sensitivity"><h2>민감도 분석</h2><p>시간예산 비교는 기준 군집의 격자·인구를 고정한다. 막대는 같은 군집에서 저접근 격자에 거주하는 고령인구 비율이다.</p>',
    image_block(ctx,'step08/figures/01_time_budget_top3.png','시간예산 30·40·50분','저접근 경계를 고정해 평균 기관 수와 남아 있는 저접근 인구를 함께 비교한다.'),
    image_block(ctx,'step08/figures/04_cutoff_cluster_maps.png','저접근 기준 하위 25·30·35%','전체 유효 격자에서 군집과 고령인구 순위를 다시 계산한다.'),
    '<details><summary>출발시각별 변화와 군집 중첩</summary>',image_block(ctx,'step08/figures/02_time_budget_profiles.png','출발시각별 평균 기관 수'),image_block(ctx,'step08/figures/05_cutoff_top3_overlap.png','군집 선정 범위의 중첩'),'</details></section>',
    '<section id="diagnosis"><h2>취약 원인 진단</h2>',
    '<p class="sub">전체 비율은 고령인구와 511개 출발시각을 가중한 값이다. 첫 보행 불가와 운행·환승을 거친 미도달을 구분하고, 도달한 경로는 30분 이내와 초과로 나누어 비교한다.</p>']
    for r in top.itertuples():
        parts += [f'<h3 id="diagnosis-{r.cluster_id}">{escape(cluster_title(r.area_name))}</h3>',
            image_block(ctx,f'step09/figures/arrival_diagnosis_{r.cluster_id}.png','도달 상태와 시간 구성','80분은 진단 탐색 한도다. 두 도달 그룹의 시간 차이는 관측된 경로 차이이며 정책 효과 추정이 아니다.'),
            image_block(ctx,f'step09/figures/bus_walk_population_{r.cluster_id}.png','정류장 보행시간과 고령인구','색은 250m 출발 격자의 최단 보행시간, 숫자는 500m 격자의 고령인구다. 이 지도만 보행시간 상한 없이 계산하며 본 분석의 연속보행 10분 조건은 유지한다. 가까운 정류장이 곧 의료기관 도달에 유리한 정류장을 뜻하지는 않는다.')]
    parts += ['<p class="finding">첫 정류장까지의 보행 부담과 도달 경로의 대기·차내 시간을 함께 살펴본다. 접속 위치의 근사와 일부 보완 시간표의 추정 시각은 자료상 한계다.</p></section>',
    '<section><details><summary>기초자료와 통합 교통망</summary>']
    for n,name,title in [(1,'population_500m','고령인구 분포'),(2,'origins_overview','주거 대표점'),(3,'facilities_overview','분석 의료기관'),(4,'network_overview','보행·정류장 통합망')]:parts.append(image_block(ctx,f'step{n:02d}/figures/{name}.png',title))
    parts+=['</details></section><section id="files"><h2>단계별 결과 자료</h2><p class="sub">공간 결과는 GeoPackage, 수치는 CSV, 지도는 각 단계의 figures 폴더에 저장된다.</p><div class="download">']
    for n,title in enumerate(TITLES,1):
        links=[f'<a href="step{n:02d}/README.md">파일·레이어 설명</a>']+[f'<a href="{p.relative_to(ctx.output).as_posix()}">{escape(p.name)}</a>' for p in sorted(ctx.step(n).glob('*.gpkg'))]
        parts.append(f'<div class="file"><b>Step {n} · {title}</b><p>'+'<br>'.join(links)+'</p></div>')
    parts+=['</div></section><footer>평일 시간표 기반 접근성 모형 · 인구가중 집계 · EPSG:5179</footer></main></body></html>']
    (ctx.output/'결과_보기.html').write_text('\n'.join(parts),encoding='utf-8')
    (ctx.output/'README.md').write_text('# 분석 결과\n\n결과_보기.html에서 지도와 표를 확인한다. step01~step09의 tables는 수치, figures는 전체 결과 그림이며 각 README는 코드·파일·공간 레이어를 설명한다.\n\n계산 재개: python run.py processed\n\n그림·보고서 재생성: python run.py report\n\n상세 경로 배열은 .cache/analysis에 보관한다. 캐시가 없으면 processed 명령으로 재계산할 수 있다.\n',encoding='utf-8')
    import shutil
    previews=inside('assets/results');previews.mkdir(parents=True,exist_ok=True)
    featured=top[top.area_name.eq(FEATURED_REGION)]
    if len(featured)!=1:raise ValueError('README 대표 지역이 기준 상위 군집에 없음: '+FEATURED_REGION)
    featured_id=featured.iloc[0].cluster_id
    for source,target in [('step07/figures/accessibility_clusters.png','accessibility_clusters.png'),(f'step09/figures/bus_walk_population_{featured_id}.png','beopgot_gusan_gajwa_bus_walk.png')]:
        shutil.copy2(ctx.output/source,previews/target)
    assert all(sha(p)==h for p,h in ctx.inputs.items())
    atomic_json(ctx.cache/'publication_validation.json',{'inputs_unchanged':True,'valid_500m_population_ratio':float(valid.population.sum())/total,'figures':len(list(ctx.output.glob('step*/figures/*.png')))})
    ctx.state['valid_500m_population_ratio']=float(valid.population.sum())/total;ctx.state.pop('decision_audit',None);ctx.state['interpretation_status']='model_results_complete';ctx.save()
