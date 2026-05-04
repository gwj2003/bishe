# -*- coding: utf-8 -*-

species_list = [
    {
        "name": "非洲大蜗牛",
        "latin": "Achatina fulica",
        "gbif_taxon_key": 10928934,
        "baidu_url": None,
        "zh_wiki_url": None,
    },
    {
        "name": "福寿螺",
        "latin": "Pomacea canaliculata",
        "gbif_taxon_key": 2292582,
        "baidu_url": "https://baike.baidu.com/item/福寿螺/4201051",
        "zh_wiki_url": None,
    },
    {
        "name": "鳄雀鳝",
        "latin": "Atractosteus spatula",
        "gbif_taxon_key": 2346754,
        "baidu_url": None,
        "zh_wiki_url": None,
    },
    {
        "name": "豹纹翼甲鲶",
        "latin": "Pterygoplichthys pardalis",
        "gbif_taxon_key": 2339971,
        "baidu_url": None,
        "zh_wiki_url": None,
    },
    {
        "name": "齐氏罗非鱼",
        "latin": "Coptodon zillii",
        "gbif_taxon_key": 2370703,
        "baidu_url": None,
        "zh_wiki_url": "https://zh.wikipedia.org/wiki/罗非鱼",
    },
    {
        "name": "美洲牛蛙",
        "latin": "American bullfrog",
        "gbif_taxon_key": 2427091,
        "baidu_url": None,
        "zh_wiki_url": None,
    },
    {
        "name": "大鳄龟",
        "latin": "Macrochelys temminckii",
        "gbif_taxon_key": 5220318,
        "baidu_url": None,
        "zh_wiki_url": None,
    },
    {
        "name": "红耳彩龟",
        "latin": "Trachemys scripta elegans",
        "gbif_taxon_key": 2443002,
        "baidu_url": None,
        "zh_wiki_url": None,
    },
]

species_names = [item["name"] for item in species_list]
species_gbif_targets = {
    item["name"]: item["gbif_taxon_key"]
    for item in species_list
    if item.get("gbif_taxon_key") is not None
}

DEFAULT_ENCYCLOPEDIA_TYPES = [
    {"key": "baidu", "label": "百度百科"},
    {"key": "zh_wiki", "label": "中文维基"},
    {"key": "en_wiki", "label": "英文维基"},
]
