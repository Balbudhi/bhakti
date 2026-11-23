"""Write web/world.svg: land as an even dot grid in the Equal Earth projection.

Run only to change the map:
  python3 build_world.py ne_110m_land.geojson web/world.svg
Input is Natural Earth 1:110m land (public domain). web/owner.js projects visitor
places with the same constants and viewBox; test_owner_ui.js checks that they agree.
"""
import json
import math
import sys

# MARGIN trims open Pacific from both sides; Hawaii and New Zealand stay inside.
WIDTH, NORTH, SOUTH, SPACING, MARGIN = 1000, 80, -56, 6.5, 40
A1, A2, A3, A4, M = 1.340264, -0.081106, 0.000893, 0.003796, math.sqrt(3) / 2
SCALE = WIDTH / (2 * math.pi / (M * A1))


def northing(theta):
    return theta * (A1 + A2 * theta ** 2 + theta ** 6 * (A3 + A4 * theta ** 2))


def slope(theta):
    return A1 + 3 * A2 * theta ** 2 + theta ** 6 * (7 * A3 + 9 * A4 * theta ** 2)


def parametric(latitude):
    return math.asin(M * math.sin(math.radians(latitude)))


TOP = northing(parametric(NORTH))
HEIGHT = round((TOP - northing(parametric(SOUTH))) * SCALE)


def unproject(x, y):
    """Longitude and latitude of a viewBox point, or None outside the globe."""
    target = TOP - y / SCALE
    theta = target / A1
    for _ in range(12):
        theta -= (northing(theta) - target) / slope(theta)
    longitude = math.degrees((x - WIDTH / 2) / SCALE * M * slope(theta) / math.cos(theta))
    sine = math.sin(theta) / M
    if abs(longitude) > 180 or abs(sine) > 1:
        return None
    return longitude, math.degrees(math.asin(sine))


def inside(ring, longitude, latitude):
    result = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > latitude) != (y2 > latitude) and longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
            result = not result
    return result


def main(source, target):
    polygons = []
    for feature in json.load(open(source))['features']:
        geometry = feature['geometry']
        polygons += [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    path, rows = [], int(HEIGHT / (SPACING * math.sqrt(3) / 2))
    for row in range(rows + 1):
        y = row * SPACING * math.sqrt(3) / 2
        x = SPACING / 2 * (row % 2)
        previous = None
        while x <= WIDTH - MARGIN:
            point = unproject(x, y)
            if point and x >= MARGIN and any(inside(rings[0], *point) and not any(inside(hole, *point) for hole in rings[1:]) for rings in polygons):
                # A relative move per dot keeps the file small; round caps draw the dot.
                path.append(f'M{x:g} {y:.1f}h0' if previous is None else f'm{x - previous:g} 0h0')
                previous = x
            x += SPACING
    with open(target, 'w') as out:
        out.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{MARGIN} 0 {WIDTH - 2 * MARGIN} {HEIGHT}"><path d="{"".join(path)}" '
                  'fill="none" stroke="#f4ead0" stroke-opacity=".34" stroke-width="3.3" stroke-linecap="round"/></svg>\n')
    print(HEIGHT, TOP, SCALE, sum(1 for part in path))


if __name__ == '__main__':
    main(*sys.argv[1:])
