import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import geopandas as gpd
from shapely.geometry import Point
import os

# --- 页面配置 ---
st.set_page_config(page_title="入侵物种省级分布识别", layout="wide")
st.title("🗺️ 基于经纬度空间识别的省级分布图")


# --- 1. 核心地理计算函数 ---
@st.cache_data  # 使用缓存，避免重复计算
def get_standard_province_data(csv_path):
    # 读取原始数据
    df = pd.read_csv(csv_path)

    # 将经纬度转为地理点对象
    geometry = [Point(xy) for xy in zip(df['lng'], df['lat'])]
    gdf_points = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

    # 获取中国省级行政边界 (使用高德/阿里源，坐标系为WGS84)
    china_geojson_url = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
    china_map = gpd.read_file(china_geojson_url)

    # 空间连接：判断点属于哪个省
    # sjoin 会将 china_map 中的 'name' 字段匹配给落在该范围内的点
    joined = gpd.sjoin(gdf_points, china_map[['name', 'geometry']], how="left", predicate='within')

    # 统计每个标准省份的名字和记录数
    prov_counts = joined['name'].value_counts().reset_index()
    prov_counts.columns = ['province_name', 'counts']

    return joined, prov_counts


# --- 2. 侧边栏与数据加载 ---
data_dir = "../data/gbif_results"
species_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
species_names = [f.replace(".csv", "") for f in species_files]

st.sidebar.header("数据控制")
selected_species = st.sidebar.selectbox("选择分析物种", species_names)
mode = st.sidebar.radio("显示模式", ["省级填色图", "原始分布点图"])

# 执行空间识别逻辑
csv_path = os.path.join(data_dir, f"{selected_species}.csv")
with st.spinner('正在进行地理空间匹配...'):
    df_with_prov, province_stats = get_standard_province_data(csv_path)

# --- 3. 地图绘制 ---
m = folium.Map(location=[35, 105], zoom_start=4, tiles="CartoDB positron")

if mode == "省级填色图":
    # 绘制填色图
    folium.Choropleth(
        geo_data="https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json",
        data=province_stats,
        columns=["province_name", "counts"],
        key_on="feature.properties.name",  # 这里的 name 会和省份统计表里的字段精准对应
        fill_color="YlOrRd",
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name="记录数量",
        nan_fill_color="white"
    ).add_to(m)
else:
    # 原始点图
    from folium.plugins import MarkerCluster

    cluster = MarkerCluster().add_to(m)
    for _, row in df_with_prov.iterrows():
        # 如果经纬度有效则打点
        if pd.notnull(row['lat']):
            folium.CircleMarker(
                location=[row['lat'], row['lng']],
                radius=4,
                color='red',
                fill=True,
                popup=f"识别省份: {row['name']}"
            ).add_to(cluster)

# 渲染地图
st_folium(m, width=1100, height=600)

# --- 4. 数据报表 ---
st.subheader("📋 分析结果摘要")
col1, col2 = st.columns(2)
with col1:
    st.write("各省分布强度排名：")
    st.dataframe(province_stats)
with col2:
    total_prov = len(province_stats.dropna())
    st.info(f"经过空间拓扑识别，**{selected_species}** 目前已入侵中国 **{total_prov}** 个省级行政区。")

# 导出识别后的数据
if st.sidebar.button("导出带省份标签的CSV"):
    csv = df_with_prov.to_csv(index=False).encode('utf-8-sig')
    st.sidebar.download_button("点击下载", csv, f"{selected_species}_tagged.csv", "text/csv")