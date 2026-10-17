"""Consistent publication labels; no changes to cluster membership or measurements."""

FEATURED_REGION = '법곳·구산·가좌 지역'
AREA_LABELS = {'가좌동·송포동·덕이동': FEATURED_REGION}


def area_label(name):
    return AREA_LABELS.get(name, name)


def cluster_title(name):
    name = area_label(name)
    return name if name.endswith(' 지역') else name.replace('동', '') + ' 군집'


def area_title(name):
    name = area_label(name)
    return name if name.endswith(' 지역') else name + ' 일대'
