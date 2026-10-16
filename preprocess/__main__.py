"""원자료와 프로젝트 내부 보정 CSV에서 전처리 결과를 재생성한다."""
from src.preprocessing_common import ROOT, initialize
initialize()
import subprocess
import sys


def preprocess_all():
    scripts=['01_boundaries.py','02_elderly_population.py','03_residential_buildings.py',
             '04_medical_institutions.py','05_osm_walk_network.py','06_gtfs.py','07_gtfs_supplements.py']
    for script in scripts:
        command=[sys.executable,str(ROOT/'preprocess'/script)]
        if script.startswith('04'): command.append('--offline')
        subprocess.run(command,cwd=ROOT,check=True)
    from src.preprocessing_validation import finalize
    finalize()


if __name__=='__main__':
    preprocess_all()
