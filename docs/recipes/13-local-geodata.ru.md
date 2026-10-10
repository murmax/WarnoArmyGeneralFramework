# Географические входы: свои файлы и устройство рендера

[Основная инструкция](13-geography.ru.md) · [English](13-local-geodata.md) · [Навигатор](../RECIPES_RU.md)

## Собственный GeoTIFF высот

Нужны высоты в метрах в первом растровом канале, действительная CRS и географическое преобразование. Непривязанный TIFF или RGB-спутниковый снимок не является источником высот. Горизонтальная CRS может перепроецироваться; вертикальные единицы автоматически не определяются.

Просмотр:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag geotiff-inspect data/my-dem.tif artifacts/dem-inspect-01
```

Откройте preview.png/geotiff.json. Preview севером вверх. Выберите полностью покрытый исходником район:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag geotiff-crop data/my-dem.tif 32.45 44.28 34.15 45.55 2048 artifacts/dem-crop-01 --elevation-ceiling-m 1200
```

Замените путь и координаты. Heightmap.png начинается с северо-запада, север находится сверху; bounds/hash берутся из crop.json. Каталог результата новый.

| Аргумент | Границы / действие |
| --- | --- |
| Источник | GeoTIFF с CRS, размерами от 2×2 и минимум одним каналом |
| west/south/east/north | Конечные WGS84; долгота −180…180, широта −90…90; размер каждой оси ≥0,001° |
| Область | Полностью внутри доступных перепроецированных границ источника |
| Resolution | Квадратное целое 128–8192 |
| Elevation ceiling | Конечное 1–10000 м, default 1600 |
| Destination | Новый каталог |

Используется билинейная интерполяция, отрицательные/нечисловые высоты превращаются в ноль, значения нормализуются по потолку в 16 бит. Район без высоты суши выше 0,75 м отвергается. Высоты выше потолка обрезаются. Подключение — в [настройках мира](13-geography.ru.md).

## Рендер собственного GeoPackage и DEM

У geodata-import нет ключей --osm-file/--dem-file: команда загружает выбранные источники сама. Для совместимых локальных файлов опубликована функция рендера. Её можно вызвать готовой командой без изменения кода:

```powershell
./.venv/Scripts/python.exe -B -c "from warno_ag.osm_tiles import render_osm_tiles; render_osm_tiles('data/source.gpkg', 'data/my-dem.tif', [32.45, 44.28, 34.15, 45.55], 'artifacts/local-surface-01', zoom=12, surface_size=4096, render_labels=False)"
```

Замените пути/координаты. Heightmap создайте отдельно через geotiff-crop. Рендер даст surface.png, tile-mosaic.png, PNG-тайлы, preliminary strategic-grid-cells.json и osm-tiles.json.

Требования GeoPackage:

- Геометрия EPSG:4326, долгота/широта. Произвольная векторная CRS автоматически не преобразуется.
- Поддерживаемый little-endian GeoPackage-заголовок и WKB.
- В обязательных таблицах столбцы geom, fclass, name. Таблица может быть пустой, но должна существовать.
- Подходящие polygon/line/point и multipart-геометрии.

| Обязательная таблица | Содержимое |
| --- | --- |
| gis_osm_landuse_a_free | Землепользование |
| gis_osm_natural_a_free | Природные территории |
| gis_osm_water_a_free | Водные полигоны |
| gis_osm_buildings_a_free | Контуры зданий |
| gis_osm_waterways_free | Водотоки |
| gis_osm_railways_free | Железные дороги |
| gis_osm_roads_free | Дороги/грунтовки/тропы |

Необязательная gis_osm_places_free используется при render_labels=True: рисуются именованные city/town. Обычный импорт выключает подписи, поскольку игровые labels остаются отдельными и переводимыми.

Произвольные PBF, Shapefile и иначе устроенные GPKG непосредственно не поддерживаются. Заранее подготовьте совместимый GeoPackage внешним процессом обработки геоданных. Интерфейс не задаёт собственные имена таблиц/полей, произвольную CRS или универсальную конвертацию векторов.

## Какие слои рисуются

Основа — цвета суши/моря и светотень градиента DEM. Далее последовательно накладываются OSM-слои. Стили полигонов:

- forest/wood; scrub/heath; grass/meadow/park/recreation_ground;
- farmland/farm/orchard/vineyard;
- residential/commercial; industrial/military/railway;
- beach/sand; cemetery/allotments.

Другие классы landuse/natural пропускаются. Water/buildings заполняются цветом. Водотоки и железные дороги имеют ширину 2 пикселя. Дороги с обводкой: внутренняя ширина motorway/trunk 7, primary/primary_link 6, secondary/secondary_link 5, tertiary/tertiary_link 4, residential/unclassified/living_street 3, service/track 2, другие 1. Это пиксели промежуточного рендера, а не ширина игровой клетки.

Цвета, толщины и фильтры фиксированы текущим рендерером. Публичных YAML/CLI-настроек стиля нет. Для другого вида можно подать готовую RGB-поверхность; правила движения от этого не изменятся.

Не рисуются административные границы, адреса, POI, маршруты транспорта и горизонтали. Это ограниченный рендерер, а не полный стиль OpenStreetMap Carto. Полигоны рисуются по внешнему кольцу: точность внутренних отверстий ограничена. Полной модели наложения мостов/туннелей нет.

Контраст умножается на 1,12, яркость — на 0,84 под стратегическое освещение. Промежуточный растр EPSG:3857 перепроецируется в выбранный EPSG:4326 и сохраняет север сверху с началом northwest. Для локального вызова тоже действуют zoom 8–13, surface_size 512–8192 и предел мозаики 48 миллионов пикселей.

## Предварительные типы местности

Результат — **101×101** всей области с усреднёнными масками:

| Приоритет | Условие | Тип |
| --- | --- | --- |
| 1 | Water mask ≥0,60 | StrategicWater |
| 2 | Urban mask ≥0,36 | StrategicUrban |
| 3 | Urban mask ≥0,11 | StrategicSemiUrban |
| 4 | Forest mask ≥0,42 | StrategicForest |
| 5 | Иначе | StrategicPlain |

Городское землепользование имеет вес 220/255, здания 1, лес 1. Водная маска берётся из DEM ≤0,7 м, **а не всех нарисованных OSM-водоёмов**. Высоко расположенное озеро может быть синим, но не водной клеткой; низкая суша — наоборот. Результат требует проверки и ручного исправления: пороги не гарантируют правильную стратегическую местность.

Дорожные признаки движения рендерер не создаёт. Нарисованные линии — внешний вид. Road true задаётся в логических клетках отдельно. Автоматического превращения современных геоданных в исторические и универсальной расстановки трёхмерных зданий/лесов нет.

## Подключить клетки для полной карты

Для первого прототипа с миром 2×2 можно сознательно сделать всю область игровой и логической. Пример переписывает map.yaml/profile.yaml: заранее сохраните копию исходников. Остальные значения сохраняются, но комментарии/форматирование могут измениться.

```powershell
@'
import json
from pathlib import Path
import yaml

source = Path('campaigns/my-campaign')
cells_file = Path('artifacts/my-geodata-01/surface/strategic-grid-cells.json')
bounds = [0, 0, 1310720, 1310720]
cells = json.loads(cells_file.read_text(encoding='utf-8'))

map_file = source / 'map.yaml'
map_data = yaml.safe_load(map_file.read_text(encoding='utf-8'))
map_data['strategic_grid'] = {
    'dimensions': {'width': 101, 'height': 101},
    'bounds': bounds, 'default_terrain': 'StrategicPlain', 'cells': cells,
}
profile_file = source / 'profile.yaml'
profile = yaml.safe_load(profile_file.read_text(encoding='utf-8'))
profile['bounds'] = bounds
profile['strategic_map'].update(
    bounds=bounds, playable_bounds=bounds,
    dimensions={'width': 101, 'height': 101},
)
for path, data in [(map_file, map_data), (profile_file, profile)]:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
'@ | ./.venv/Scripts/python.exe -B -
```

Применяется только при одинаковых world.bounds 2×2 и render_cases 2×2, когда вся область действительно должна стать playable. Старые сущности/объекты не переносятся, дороги не добавляются. Перед запеканием изменённого мира согласуйте новое map_name.

Для меньшей playable area или другого размера не используйте эти константы вслепую. Выведите размеры/границы логических клеток нужного региона, выберите/пересэмплируйте исходную классификацию. Штатный шаг движения остаётся 13000, разрешение картинки независимо. Универсальной публичной команды для любого обрезания/пересэмплирования этого JSON нет.

## Покрытие загрузки и кэш

Geodata-import использует [индекс регионов Geofabrik](https://download.geofabrik.de/index-v1.json) и [Copernicus GLO-30](https://registry.opendata.aws/copernicus-dem/). У загрузок есть URL, размер и SHA256. Совпадающий кэш сохраняет прежние байты; слово latest не обновляет его автоматически.

Выбирается один компактный пересекающийся регион OSM. Это не гарантирует полноту трансграничного прямоугольника: проверьте geodata.json/osm-source.json. Для таких районов нужен подготовленный совместимый объединённый extract либо область внутри одного доступного региона. Слишком большой OSM-архив или отсутствующий публичный DEM — реальные ограничения входов.

Для свежих данных используйте новый кэш и новый результат. Отсутствующий/изменённый receipt и неполная загрузка отвергаются вместо молчаливой замены. Сохраняйте атрибуцию участников OSM/ODbL и лицензию источника Copernicus вместе с производными ресурсами. Происхождение географии отдельно от игровых YAML-настроек.
