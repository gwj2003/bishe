 
import os
import glob
import json
import time
from collections import defaultdict
import shutil
import subprocess

import math
import pandas as pd
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.strtree import STRtree
from shapely.ops import unary_union

try:
	from geopy.geocoders import Nominatim
except Exception:
	Nominatim = None
import urllib.request
import urllib.error

try:
	import py7zr
except Exception:
	py7zr = None

# Administrative suffix sets (as requested)
PROVINCE_SUFFIXES = ("省", "自治区", "特别行政区")
CITY_SUFFIXES = ("市", "盟", "州", "地区", "自治州")
DISTRICT_SUFFIXES = ("区", "县", "旗", "林区", "自治县", "市辖区", "镇", "乡", "村")
INVALID_REGION_CODE_FALLBACKS = {"CN", "HK", "TW", "MO"}

GBIF_DIR = os.path.join("data", "gbif_results")
CACHE_PATH = os.path.join(GBIF_DIR, "geocode_cache.json")
OUTPUT_PATH = os.path.join(GBIF_DIR, "gbif_dedup_by_admin_year.csv")
ADMIN_DIR = os.path.join("data", "admin_shapefiles")

# Chinese admin boundary source with Chinese names and HK/MO/TW coverage
AREACITY_OK_GEO_URL = "https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov/releases/download/2025.251231.260403/ok_geo.csv.7z"
AREACITY_OK_GEO_PROXY_URL = "https://gh-proxy.org/https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov/releases/download/2025.251231.260403/ok_geo.csv.7z"


def load_cache(path=CACHE_PATH):
	if os.path.exists(path):
		try:
			with open(path, "r", encoding="utf-8") as f:
				return json.load(f)
		except Exception:
			return {}
	return {}


def save_cache(cache, path=CACHE_PATH):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		json.dump(cache, f, ensure_ascii=False, indent=2)


def download_admin_shapefile(admin_dir=ADMIN_DIR):
	"""Download AreaCity ok_geo.csv.7z and extract ok_geo.csv."""
	os.makedirs(admin_dir, exist_ok=True)
	archive_path = os.path.join(admin_dir, "ok_geo.csv.7z")
	extract_dir = os.path.join(admin_dir, "AreaCity_ok_geo")
	csv_path = os.path.join(extract_dir, "ok_geo.csv")
	if os.path.exists(csv_path):
		return csv_path

	urls = [AREACITY_OK_GEO_URL, AREACITY_OK_GEO_PROXY_URL]
	last_error = None
	for url in urls:
		try:
			print(f"尝试下载 AreaCity 中国省市区边界数据：{url}")
			urllib.request.urlretrieve(url, archive_path, reporthook=lambda a, b, c: None)
			print(f"  下载完成：{archive_path}")
			break
		except Exception as e:
			last_error = e
			print(f"  下载失败：{e}")
	else:
		print(f"  所有下载地址均失败：{last_error}")
		return None

	os.makedirs(extract_dir, exist_ok=True)
	if py7zr is not None:
		try:
			with py7zr.SevenZipFile(archive_path, mode="r") as zf:
				zf.extractall(path=extract_dir)
			if os.path.exists(csv_path):
				print(f"  解压完成：{csv_path}")
				return csv_path
		except Exception as e:
			print(f"  py7zr 解压失败：{e}")

	seven_z = shutil.which("7z") or shutil.which("7za")
	if seven_z:
		try:
			subprocess.run([seven_z, "x", archive_path, f"-o{extract_dir}", "-y"], check=True)
			if os.path.exists(csv_path):
				print(f"  解压完成：{csv_path}")
				return csv_path
		except Exception as e:
			print(f"  7z 解压失败：{e}")

	print("  无法解压 ok_geo.csv.7z，请检查 py7zr 或 7z 是否可用")
	return None



def load_admin_boundaries(csv_path):
	"""Load AreaCity polygons and build a spatial index without geopandas/PROJ."""
	df = pd.read_csv(csv_path, dtype=str, low_memory=False)
	need_cols = [c for c in ["ext_path", "name", "polygon"] if c not in df.columns]
	if need_cols:
		raise ValueError(f"ok_geo.csv 缺少必要字段: {need_cols}")

	geometries = []
	properties = []
	for _, row in df.iterrows():
		polygon_text = str(row.get("polygon") or "").strip()
		if not polygon_text or polygon_text == "EMPTY":
			continue
		try:
			parts = []
			for block in polygon_text.split(";"):
				block = block.strip()
				if not block:
					continue
				coords = []
				for pair in block.split(","):
					pair = pair.strip()
					if not pair:
						continue
					lng_str, lat_str = pair.split()
					coords.append((float(lng_str), float(lat_str)))
				if len(coords) >= 3:
					parts.append(Polygon(coords))
			if not parts:
				continue
			geometry = parts[0] if len(parts) == 1 else MultiPolygon(parts)
			if geometry.is_empty:
				continue
			geometries.append(geometry)
			properties.append({
				"name": row.get("name"),
				"ext_path": row.get("ext_path"),
				"deep": row.get("deep"),
				"id": row.get("id"),
			})
		except Exception:
			continue

	if not geometries:
		return None, [], [], {}

	geometry_index = {id(geometry): index for index, geometry in enumerate(geometries)}
	return STRtree(geometries), geometries, properties, geometry_index


def out_of_china(lng, lat):
	return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def transform_lat(lng, lat):
	ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
	ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
	ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
	ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
	return ret


def transform_lng(lng, lat):
	ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
	ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
	ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
	ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
	return ret


def wgs84_to_gcj02(lng, lat):
	if out_of_china(lng, lat):
		return lng, lat
	a = 6378245.0
	ee = 0.00669342162296594323
	dlat = transform_lat(lng - 105.0, lat - 35.0)
	dlng = transform_lng(lng - 105.0, lat - 35.0)
	radlat = lat / 180.0 * math.pi
	magic = math.sin(radlat)
	magic = 1 - ee * magic * magic
	sqrtmagic = math.sqrt(magic)
	dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
	dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
	mglat = lat + dlat
	mglng = lng + dlng
	return mglng, mglat


def split_admin_path(ext_path):
	parts = [p for p in str(ext_path).split() if p]
	province = parts[0] if len(parts) > 0 else None
	city = parts[1] if len(parts) > 1 else None
	district = parts[2] if len(parts) > 2 else None
	if province and province.endswith("特别行政区"):
		if len(parts) <= 1 or all(part == province for part in parts):
			return province, None, None
		if city == province:
			city = None
		if district == province:
			district = None
	elif len(parts) == 2 and city == province:
		city = None
	return province, city, district


def format_admin_address(province, city, district):
	parts = [part for part in [province, city, district] if part]
	if not parts:
		return None
	if len(parts) == 1:
		return parts[0]
	if district:
		if city and city != province:
			return f"{province} {city} {district}"
		return f"{province} {district}"
	if city and city != province:
		return f"{province} {city}"
	return province


def boundary_depth_value(props):
	value = props.get("deep")
	try:
		return int(float(value))
	except Exception:
		pass
	ext_path = str(props.get("ext_path") or "")
	return len([part for part in ext_path.split() if part])


def choose_best_boundary(point, candidate_indices, admin_geometries, admin_properties):
	best_index = None
	best_depth = -1
	best_path_len = -1
	for candidate_index in candidate_indices:
		i = int(candidate_index)
		geometry = admin_geometries[i]
		if not geometry.covers(point):
			continue
		props = admin_properties[i]
		depth = boundary_depth_value(props)
		path_len = len([part for part in str(props.get("ext_path") or "").split() if part])
		if depth > best_depth or (depth == best_depth and path_len > best_path_len):
			best_index = i
			best_depth = depth
			best_path_len = path_len
	return best_index


def find_best_boundary(point, admin_tree, admin_geometries, admin_properties):
	if admin_tree is None:
		return None, -1, -1
	try:
		candidate_indices = admin_tree.query(point)
		best_index = choose_best_boundary(point, candidate_indices, admin_geometries, admin_properties)
		if best_index is None:
			return None, -1, -1
		props = admin_properties[best_index]
		depth = boundary_depth_value(props)
		path_len = len([part for part in str(props.get("ext_path") or "").split() if part])
		return best_index, depth, path_len
	except Exception:
		return None, -1, -1


def reverse_geocode(lat, lng, geolocator, cache, delay=1.0):
	# key with limited precision to allow reuse
	key = f"{float(lat):.5f},{float(lng):.5f}"
	if key in cache:
		return cache[key]

	if geolocator is None:
		return {"province": None, "city": None, "district": None, "display_name": None}

	try:
		loc = geolocator.reverse((lat, lng), language="zh-CN", exactly_one=True, timeout=10)
	except Exception:
		time.sleep(delay)
		try:
			loc = geolocator.reverse((lat, lng), language="zh-CN", exactly_one=True, timeout=10)
		except Exception:
			return {"province": None, "city": None, "district": None, "display_name": None}

	time.sleep(delay)

	if loc is None:
		res = {"province": None, "city": None, "district": None, "display_name": None}
		cache[key] = res
		return res

	adr = loc.raw.get("address", {}) if isinstance(loc.raw, dict) else {}

	# heuristics to extract admin levels from geopy/Nominatim address fields
	province = adr.get("state") or adr.get("province") or adr.get("region")
	city = adr.get("city") or adr.get("town") or adr.get("municipality") or adr.get("county")
	district = adr.get("county") or adr.get("suburb") or adr.get("city_district") or adr.get("village") or adr.get("hamlet")

	# normalize empty strings
	def norm(x):
		if x is None:
			return None
		x = str(x).strip()
		return x if x != "" else None

	res = {
		"province": norm(province),
		"city": norm(city),
		"district": norm(district),
		"display_name": getattr(loc, "address", None) or getattr(loc, "raw", {}).get("display_name")
	}
	cache[key] = res
	return res


def load_all_gbif(dirpath=GBIF_DIR):
	files = glob.glob(os.path.join(dirpath, "*.csv"))
	if not files:
		print(f"No GBIF CSV files found in {dirpath}")
		return pd.DataFrame()

	frames = []
	for p in files:
		try:
			df = pd.read_csv(p, dtype={"lat": float, "lng": float}, low_memory=False)
			df["_source_file"] = os.path.basename(p)
			frames.append(df)
		except Exception as e:
			print(f"Failed to read {p}: {e}")
	if frames:
		return pd.concat(frames, ignore_index=True)
	return pd.DataFrame()


def year_from_date(s):
	try:
		if pd.isna(s):
			return None
		return int(str(s)[:4])
	except Exception:
		return None


def representative_point(group_df):
	# choose centroid (mean lat/lng) of valid points
	lat = group_df["lat"].median() if not group_df["lat"].isna().all() else None
	lng = group_df["lng"].median() if not group_df["lng"].isna().all() else None
	return lat, lng


def build_ext_path_centroids(admin_geometries, admin_properties):
	"""Build centroid lookup by ext_path using merged geometry."""
	path_geometries = defaultdict(list)
	for geometry, props in zip(admin_geometries, admin_properties):
		ext_path = str(props.get("ext_path") or "").strip()
		if not ext_path:
			continue
		if geometry.is_empty:
			continue
		path_geometries[ext_path].append(geometry)

	centroids = {}
	for ext_path, geoms in path_geometries.items():
		try:
			merged = unary_union(geoms) if len(geoms) > 1 else geoms[0]
			if merged.is_empty:
				continue
			c = merged.centroid
			centroids[ext_path] = (float(c.y), float(c.x))
		except Exception:
			continue
	return centroids


def process_gbif(input_dir=GBIF_DIR, out_path=OUTPUT_PATH, use_reverse_geocode=False, use_admin_shapefile=True, admin_shp_dir=None, provider="nominatim"):
	df = load_all_gbif(input_dir)
	if df.empty:
		print("No data to process.")
		return

	# ensure expected columns exist
	for c in ["species_label", "lat", "lng", "province", "date"]:
		if c not in df.columns:
			df[c] = None

	# normalize column names that might be different
	if "decimalLatitude" in df.columns and df["lat"].isna().all():
		df["lat"] = df.get("decimalLatitude")
	if "decimalLongitude" in df.columns and df["lng"].isna().all():
		df["lng"] = df.get("decimalLongitude")
	if "eventDate" in df.columns and df["date"].isna().all():
		df["date"] = df.get("eventDate")


	# drop rows without coords
	df = df.dropna(subset=["lat", "lng"]) 

	df["year"] = df["date"].apply(year_from_date)
	df = df.dropna(subset=["year"])  # require year to aggregate

	# Load AreaCity Chinese admin boundaries and build a spatial index without geopandas/PROJ
	admin_tree = None
	admin_geometries = []
	admin_properties = []
	admin_geometry_index = {}
	ext_path_centroids = {}
	if use_admin_shapefile:
		search_dir = admin_shp_dir or ADMIN_DIR
		csv_path = None
		if os.path.exists(search_dir):
			for root, _, files in os.walk(search_dir):
				for f in files:
					if f == "ok_geo.csv":
						csv_path = os.path.join(root, f)
						break
				if csv_path:
					break

		if not csv_path:
			print("未找到本地中国行政边界 CSV，尝试下载 AreaCity ok_geo.csv.7z...")
			csv_path = download_admin_shapefile(search_dir)

		if csv_path:
			try:
				admin_tree, admin_geometries, admin_properties, admin_geometry_index = load_admin_boundaries(csv_path)
				if admin_tree is not None:
					ext_path_centroids = build_ext_path_centroids(admin_geometries, admin_properties)
					print("Loaded admin csv with", len(admin_geometries), "polygons from", csv_path)
				else:
					print("Loaded csv but no valid polygons were found:", csv_path)
			except Exception as e:
				print("Failed to load admin csv:", e)
				admin_tree = None

	# for each row, determine admin levels (prefer existing province/city/district in CSV)
	admin_records = []
	total = len(df)
	print(f"Processing {total} GBIF records...")

	for idx, row in df.iterrows():
		lat = row["lat"]
		lng = row["lng"]
		species = row.get("species_label") or row.get("gbif_scientific_name")
		year = int(row["year"])

		# Convert WGS84 input coordinates to GCJ-02, then map to the most fine-grained admin boundary
		gcj_lng, gcj_lat = wgs84_to_gcj02(float(lng), float(lat))
		province = None
		city = None
		district = None
		ext_path = None
		best_index, best_depth, best_path_len = find_best_boundary(Point(gcj_lng, gcj_lat), admin_tree, admin_geometries, admin_properties)
		raw_index, raw_depth, raw_path_len = find_best_boundary(Point(float(lng), float(lat)), admin_tree, admin_geometries, admin_properties)
		if raw_index is not None and (best_index is None or raw_depth > best_depth or (raw_depth == best_depth and raw_path_len > best_path_len)):
			best_index = raw_index
		if best_index is not None:
			props = admin_properties[best_index]
			ext_path = props.get("ext_path")
			province, city, district = split_admin_path(ext_path)



		# Fallback to region_code only when no boundary matched
		if not ext_path:
			region_code = row.get("region_code") if not pd.isna(row.get("region_code")) else None
			if region_code:
				region_code = str(region_code).strip()
				if region_code.upper() in INVALID_REGION_CODE_FALLBACKS:
					# Drop code-only fallback rows (CN/HK/TW/MO), as requested.
					continue
				ext_path = region_code
				district = region_code

		address = format_admin_address(province, city, district) if ext_path else None

		admin_records.append({
			"species_label": species,
			"lat": lat,
			"lng": lng,
			"province": province,
			"city": city,
			"district": district,
			"address": address,
			"ext_path": ext_path,
			"year": year,
		})

	# no online cache to save when geocoding disabled

	adm_df = pd.DataFrame(admin_records)
	# normalize strings
	for c in ["province", "city", "district", "address", "species_label"]:
		if c in adm_df.columns:
			adm_df[c] = adm_df[c].astype(object).where(adm_df[c].notna(), None)

	# group by species_label, year, and the full Chinese admin path
	grouped = adm_df.groupby(["species_label", "year", "ext_path"], dropna=False)

	out_rows = []
	for key, group in grouped:
		species_label, year, ext_path = key
		count = len(group)
		# Prefer geometry centroid for this administrative unit, fallback to median coordinates.
		lat = None
		lng = None
		if pd.notna(ext_path) and ext_path in ext_path_centroids:
			lat, lng = ext_path_centroids[ext_path]
		if lat is None or lng is None:
			lat = group["lat"].median()
			lng = group["lng"].median()
		province, city, district = split_admin_path(ext_path) if pd.notna(ext_path) and ext_path else (None, None, None)
		address = format_admin_address(province, city, district)
		
		if pd.isna(lat) or pd.isna(lng):
			continue
		out_rows.append({
			"species_label": species_label,
			"lat": float(lat),
			"lng": float(lng),
			"province": province,
			"city": city,
			"district": district,
			"address": address,
			"year": int(year),
			"count": int(count),
		})

	out_df = pd.DataFrame(out_rows)
	os.makedirs(os.path.dirname(out_path), exist_ok=True)
	out_df.to_csv(out_path, index=False, encoding="utf-8", lineterminator="\n")
	print(f"Wrote {len(out_df)} admin-level records to {out_path}")


if __name__ == '__main__':
	# Get admin levels from coordinates using geoBoundaries ADM3 (do NOT use GBIF's province/region)
	process_gbif(use_reverse_geocode=False, use_admin_shapefile=True)

