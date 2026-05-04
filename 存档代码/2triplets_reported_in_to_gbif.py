# -*- coding: utf-8 -*-
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict

import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

try:
	import py7zr
except Exception:
	py7zr = None


INPUT_DIR = os.path.join("data", "triplets")
OUTPUT_PATH = os.path.join("data", "gbif_results", "triplets_reported_in_dedup_by_admin_year.csv")
ADMIN_DIR = os.path.join("data", "admin_shapefiles")

AREACITY_OK_GEO_URL = "https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov/releases/download/2025.251231.260403/ok_geo.csv.7z"
AREACITY_OK_GEO_PROXY_URL = "https://gh-proxy.org/https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov/releases/download/2025.251231.260403/ok_geo.csv.7z"


def normalize_text(text):
	if text is None:
		return ""
	text = str(text).strip()
	if not text or text.lower() == "nan":
		return ""
	text = text.replace("\u3000", " ")
	text = re.sub(r"\s+", " ", text)
	return text


def parse_properties(prop_str):
	if pd.isna(prop_str):
		return {}
	text = str(prop_str).strip()
	if not text or text.lower() == "null":
		return {}
	props = {}
	for item in text.split(";"):
		item = item.strip()
		if not item or "=" not in item:
			continue
		key, value = item.split("=", 1)
		props[key.strip()] = value.strip()
	return props


def parse_reported_year(props):
	raw = normalize_text(props.get("year"))
	if not raw or raw.lower() == "null" or raw.lower() == "未知":
		return None
	if re.fullmatch(r"\d{4}", raw):
		return int(raw)
	return None


def download_admin_shapefile(admin_dir=ADMIN_DIR):
	os.makedirs(admin_dir, exist_ok=True)
	archive_path = os.path.join(admin_dir, "ok_geo.csv.7z")
	extract_dir = os.path.join(admin_dir, "AreaCity_ok_geo")
	csv_path = os.path.join(extract_dir, "ok_geo.csv")
	if os.path.exists(csv_path):
		return csv_path

	last_error = None
	for url in [AREACITY_OK_GEO_URL, AREACITY_OK_GEO_PROXY_URL]:
		try:
			print(f"尝试下载行政边界数据：{url}")
			import urllib.request
			urllib.request.urlretrieve(url, archive_path)
			last_error = None
			break
		except Exception as exc:
			last_error = exc
			print(f"  下载失败：{exc}")
	if last_error is not None:
		print(f"  所有下载地址均失败：{last_error}")
		return None

	os.makedirs(extract_dir, exist_ok=True)
	if py7zr is not None:
		try:
			with py7zr.SevenZipFile(archive_path, mode="r") as zf:
				zf.extractall(path=extract_dir)
			if os.path.exists(csv_path):
				return csv_path
		except Exception as exc:
			print(f"  py7zr 解压失败：{exc}")

	seven_z = shutil.which("7z") or shutil.which("7za")
	if seven_z:
		try:
			subprocess.run([seven_z, "x", archive_path, f"-o{extract_dir}", "-y"], check=True)
			if os.path.exists(csv_path):
				return csv_path
		except Exception as exc:
			print(f"  7z 解压失败：{exc}")

	print("  无法解压 ok_geo.csv.7z")
	return None


def load_admin_boundaries(csv_path):
	df = pd.read_csv(csv_path, dtype=str, low_memory=False)
	need_cols = [c for c in ["ext_path", "name", "polygon"] if c not in df.columns]
	if need_cols:
		raise ValueError(f"ok_geo.csv 缺少必要字段: {need_cols}")

	geometries = []
	properties = []
	for _, row in df.iterrows():
		polygon_text = normalize_text(row.get("polygon"))
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
				"name": normalize_text(row.get("name")),
				"ext_path": normalize_text(row.get("ext_path")),
				"deep": row.get("deep"),
				"id": row.get("id"),
			})
		except Exception:
			continue

	if not geometries:
		return [], [], {}

	geometry_index = {id(geometry): index for index, geometry in enumerate(geometries)}
	return geometries, properties, geometry_index


def split_admin_path(ext_path):
	parts = [p for p in normalize_text(ext_path).split() if p]
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
	ext_path = normalize_text(props.get("ext_path"))
	return len([part for part in ext_path.split() if part])


def build_ext_path_centroids(admin_geometries, admin_properties):
	path_geometries = defaultdict(list)
	for geometry, props in zip(admin_geometries, admin_properties):
		ext_path = normalize_text(props.get("ext_path"))
		if not ext_path or geometry.is_empty:
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


def load_triplet_csvs(input_dir):
	patterns = [os.path.join(input_dir, "**", "*_triplets.csv"), os.path.join(input_dir, "*_triplets.csv")]
	files = []
	for pattern in patterns:
		files.extend(glob.glob(pattern, recursive=True))
	return sorted(set(files))


def read_triplets_from_file(filepath):
	try:
		df = pd.read_csv(filepath, dtype=str, low_memory=False, encoding="utf-8-sig", on_bad_lines="skip")
	except Exception:
		df = pd.read_csv(filepath, dtype=str, low_memory=False, on_bad_lines="skip")
	df.columns = [c.strip() for c in df.columns]
	for column in ["Entity1", "Relationship", "Entity2", "Property"]:
		if column not in df.columns:
			df[column] = None
	return df[["Entity1", "Relationship", "Entity2", "Property"]]


def load_reported_in_records(input_dir):
	records = []
	files = load_triplet_csvs(input_dir)
	if not files:
		print(f"未找到 triplets CSV：{input_dir}")
		return records

	for filepath in files:
		try:
			df = read_triplets_from_file(filepath)
		except Exception as exc:
			print(f"读取失败：{filepath} -> {exc}")
			continue

		mask = df["Relationship"].astype(str).str.strip().str.upper().eq("REPORTED_IN")
		if not mask.any():
			continue

		for _, row in df.loc[mask].iterrows():
			species_label = normalize_text(row.get("Entity1"))
			location_text = normalize_text(row.get("Entity2"))
			if not species_label or not location_text:
				continue
			props = parse_properties(row.get("Property"))
			year = parse_reported_year(props)
			records.append({
				"species_label": species_label,
				"location_text": location_text,
				"year": year,
			})
	return records


def choose_admin_match(location_text, admin_properties):
	location_text = normalize_text(location_text)
	if not location_text:
		return None

	exact_ext = []
	exact_name = []
	suffix_matches = []
	contains_matches = []

	for index, props in enumerate(admin_properties):
		ext_path = normalize_text(props.get("ext_path"))
		name = normalize_text(props.get("name"))
		depth = boundary_depth_value(props)
		path_len = len(ext_path.split()) if ext_path else 0

		if location_text == ext_path:
			exact_ext.append((index, depth, path_len))
			continue
		if location_text == name:
			exact_name.append((index, depth, path_len))
			continue
		if ext_path and ext_path.endswith(location_text):
			suffix_matches.append((index, depth, path_len))
			continue
		if ext_path and location_text in ext_path:
			contains_matches.append((index, depth, path_len))
			continue
		if name and location_text in name:
			contains_matches.append((index, depth, path_len))

	if exact_ext:
		return min(exact_ext, key=lambda item: (item[1], item[2]))[0]
	if exact_name:
		return min(exact_name, key=lambda item: (item[1], item[2]))[0]
	if suffix_matches:
		return max(suffix_matches, key=lambda item: (item[1], item[2]))[0]
	if contains_matches:
		return max(contains_matches, key=lambda item: (item[1], item[2]))[0]
	return None


def build_admin_record(location_text, admin_properties, admin_geometries, ext_path_centroids, match_cache):
	location_text = normalize_text(location_text)
	if not location_text:
		return None
	if location_text in match_cache:
		return match_cache[location_text]

	match_index = choose_admin_match(location_text, admin_properties)
	if match_index is None:
		match_cache[location_text] = None
		return None

	props = admin_properties[match_index]
	ext_path = normalize_text(props.get("ext_path"))
	province, city, district = split_admin_path(ext_path)
	address = format_admin_address(province, city, district)
	lat, lng = None, None
	if ext_path in ext_path_centroids:
		lat, lng = ext_path_centroids[ext_path]
	else:
		try:
			geometry = admin_geometries[match_index]
			c = geometry.centroid
			lat, lng = float(c.y), float(c.x)
		except Exception:
			lat, lng = None, None

	if lat is None or lng is None:
		match_cache[location_text] = None
		return None

	record = {
		"province": province,
		"city": city,
		"district": district,
		"address": address,
		"lat": float(lat),
		"lng": float(lng),
		"ext_path": ext_path,
	}
	match_cache[location_text] = record
	return record


def process_triplets(input_dir=INPUT_DIR, out_path=OUTPUT_PATH, admin_dir=ADMIN_DIR):
	reported_records = load_reported_in_records(input_dir)
	if not reported_records:
		print("未找到可处理的 REPORTED_IN 记录。")
		return

	admin_csv = None
	if os.path.exists(admin_dir):
		for root, _, files in os.walk(admin_dir):
			if "ok_geo.csv" in files:
				admin_csv = os.path.join(root, "ok_geo.csv")
				break
	if not admin_csv:
		print("未找到本地行政边界 CSV，尝试下载。")
		admin_csv = download_admin_shapefile(admin_dir)
	if not admin_csv:
		raise RuntimeError("无法加载行政边界数据")

	admin_geometries, admin_properties, _ = load_admin_boundaries(admin_csv)
	if not admin_geometries:
		raise RuntimeError(f"行政边界数据无有效几何：{admin_csv}")

	ext_path_centroids = build_ext_path_centroids(admin_geometries, admin_properties)
	match_cache = {}
	resolved_rows = []
	skipped = 0

	for record in reported_records:
		admin_record = build_admin_record(
			record["location_text"],
			admin_properties,
			admin_geometries,
			ext_path_centroids,
			match_cache,
		)
		if not admin_record:
			skipped += 1
			continue
		resolved_rows.append({
			"species_label": record["species_label"],
			"year": record["year"] if record["year"] is not None else "",
			"ext_path": admin_record["ext_path"],
			"province": admin_record["province"],
			"city": admin_record["city"],
			"district": admin_record["district"],
			"address": admin_record["address"],
			"lat": admin_record["lat"],
			"lng": admin_record["lng"],
		})

	if not resolved_rows:
		raise RuntimeError("所有 REPORTED_IN 记录都未能匹配到行政边界")

	df = pd.DataFrame(resolved_rows)
	df["year_key"] = df["year"].apply(lambda value: "" if pd.isna(value) else str(value).strip())
	grouped = df.groupby(["species_label", "year_key", "ext_path"], dropna=False)
	out_rows = []

	for (species_label, year_key, ext_path), group in grouped:
		province = group.iloc[0]["province"]
		city = group.iloc[0]["city"]
		district = group.iloc[0]["district"]
		address = group.iloc[0]["address"]
		lat = group.iloc[0]["lat"]
		lng = group.iloc[0]["lng"]
		out_rows.append({
			"species_label": species_label,
			"lat": float(lat),
			"lng": float(lng),
			"province": province,
			"city": city,
			"district": district,
			"address": address,
			"year": int(year_key) if year_key else "",
			"count": int(len(group)),
		})

	out_df = pd.DataFrame(out_rows)
	if out_df.empty:
		raise RuntimeError("汇总后没有可输出的数据")

	out_df["year_sort"] = out_df["year"].apply(lambda value: int(value) if str(value).isdigit() else -1)
	out_df = out_df.sort_values(["species_label", "year_sort", "province", "city", "district"], kind="stable").drop(columns=["year_sort"])
	os.makedirs(os.path.dirname(out_path), exist_ok=True)
	out_df.to_csv(out_path, index=False, encoding="utf-8", lineterminator="\n", na_rep="")
	print(f"已写出 {len(out_df)} 条行政区汇总记录：{out_path}")
	if skipped:
		print(f"跳过未匹配行政边界的 REPORTED_IN 记录：{skipped}")


def main():
	parser = argparse.ArgumentParser(description="将 triplets 中的 REPORTED_IN 提取为按行政区和年份汇总的 CSV")
	parser.add_argument("--input-dir", default=INPUT_DIR, help="triplets CSV 所在目录")
	parser.add_argument("--output-path", default=OUTPUT_PATH, help="输出 CSV 路径")
	parser.add_argument("--admin-dir", default=ADMIN_DIR, help="行政边界数据目录")
	args = parser.parse_args()
	process_triplets(args.input_dir, args.output_path, args.admin_dir)


if __name__ == "__main__":
	main()