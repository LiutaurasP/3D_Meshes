"""Every supported file type: write a small known scan, read it back, compare."""

import struct

import numpy as np
import open3d as o3d
import pytest

from scan_formats import (
    ImportOptions,
    ScanReadError,
    guess_depth_down,
    read_scan,
    sniff_text,
)

UTM = np.array([512_345.0, 5_801_234.0, 0.0])  # real survey coordinates are this big


def survey(n=500, seed=0):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 20, size=(n, 2))
    z = -8 + 0.1 * xy[:, 0]
    return np.column_stack([xy, z]) + UTM, rng.uniform(10, 200, n)


def close(a, b, tolerance=1e-3):
    return a.shape == b.shape and np.abs(a - b).max() < tolerance


def test_las_and_laz_keep_big_coordinates_and_intensity(tmp_path):
    laspy = pytest.importorskip("laspy")
    points, intensity = survey()
    for suffix in (".las", ".laz"):
        header = laspy.LasHeader(point_format=1, version="1.2")
        header.scales = [0.001, 0.001, 0.001]
        header.offsets = UTM
        las = laspy.LasData(header)
        las.x, las.y, las.z = points.T
        las.intensity = intensity.astype(np.uint16)
        path = tmp_path / f"survey{suffix}"
        las.write(str(path))
        scan = read_scan(path)
        assert close(scan.points, points)
        assert np.allclose(scan.intensity, intensity.astype(np.uint16))
        assert suffix[1:].upper() in scan.kind


def test_e57(tmp_path):
    pye57 = pytest.importorskip("pye57")
    points, intensity = survey()
    points = points - UTM  # pye57's writer stores 32-bit floats; real E57 files use doubles
    path = tmp_path / "survey.e57"
    with pye57.E57(str(path), mode="w") as e57:
        e57.write_scan_raw({"cartesianX": points[:, 0], "cartesianY": points[:, 1], "cartesianZ": points[:, 2],
                            "intensity": intensity / 200})
    scan = read_scan(path)
    assert close(scan.points, points)
    assert scan.intensity is not None


def write_ply(path, points, intensity, binary=True):
    header = ["ply", f"format {'binary_little_endian' if binary else 'ascii'} 1.0", f"element vertex {len(points)}",
              "property double x", "property double y", "property double z", "property float intensity", "end_header"]
    with open(path, "wb") as handle:
        handle.write(("\n".join(header) + "\n").encode())
        for p, i in zip(points, intensity):
            if binary:
                handle.write(struct.pack("<dddf", *p, i))
            else:
                handle.write(f"{p[0]} {p[1]} {p[2]} {i}\n".encode())


@pytest.mark.parametrize("binary", [True, False])
def test_ply_keeps_intensity(tmp_path, binary):
    points, intensity = survey()
    path = tmp_path / "survey.ply"
    write_ply(path, points, intensity, binary)
    scan = read_scan(path)
    assert close(scan.points, points)
    assert np.allclose(scan.intensity, intensity, atol=1e-3)


def test_pcd(tmp_path):
    points, _ = survey()
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points - UTM))
    o3d.io.write_point_cloud(str(tmp_path / "s.pcd"), cloud)
    assert close(read_scan(tmp_path / "s.pcd").points, points - UTM)


def test_csv_with_header_in_any_order(tmp_path):
    points, intensity = survey()
    path = tmp_path / "export.csv"
    lines = ["Point,Northing,Easting,Depth,Backscatter"]
    lines += [f"{n},{p[1]:.3f},{p[0]:.3f},{-p[2]:.3f},{i:.1f}" for n, (p, i) in enumerate(zip(points, intensity), 1)]
    path.write_text("\n".join(lines))
    layout = sniff_text(path)
    assert layout.columns == {"x": 2, "y": 1, "z": 3, "intensity": 4}
    assert layout.skip_rows == 1
    scan = read_scan(path, ImportOptions(depth_down=True))
    assert close(scan.points, points)
    assert guess_depth_down(np.column_stack([points[:, :2], -points[:, 2]]))


def test_space_separated_xyz_without_header(tmp_path):
    points, _ = survey()
    path = tmp_path / "survey.xyz"
    np.savetxt(path, points, fmt="%.3f")
    scan = read_scan(path)
    assert close(scan.points, points)
    assert scan.intensity is None


def test_semicolon_text_with_point_numbers_and_comma_free_decimals(tmp_path):
    points, _ = survey(50)
    path = tmp_path / "survey.txt"
    rows = [f"{n};{p[0]:.3f};{p[1]:.3f};{p[2]:.3f}" for n, p in enumerate(points, 1)]
    path.write_text("Exported by survey software\n\n" + "\n".join(rows))
    layout = sniff_text(path)
    assert layout.delimiter == ";"
    assert layout.columns["x"] == 1  # the point number column is skipped
    assert close(read_scan(path).points, points)


def test_broken_rows_are_skipped(tmp_path):
    points, _ = survey(20)
    path = tmp_path / "broken.xyz"
    rows = [f"{p[0]} {p[1]} {p[2]}" for p in points]
    rows.insert(5, "error: sensor dropout")
    path.write_text("\n".join(rows))
    assert len(read_scan(path).points) == 20


def test_pts_with_count_line(tmp_path):
    points, intensity = survey(30)
    path = tmp_path / "scan.pts"
    path.write_text(f"{len(points)}\n" + "\n".join(f"{p[0]} {p[1]} {p[2]} {int(i)} 120 130 140"
                                                    for p, i in zip(points, intensity)))
    scan = read_scan(path)
    assert close(scan.points, points)
    assert scan.intensity is not None


def test_feet_are_converted(tmp_path):
    path = tmp_path / "feet.xyz"
    np.savetxt(path, [[0, 0, -10], [10, 0, -10], [0, 10, -12]])
    scan = read_scan(path, ImportOptions(unit="ft"))
    assert np.isclose(scan.points[1, 0], 3.048)


def test_esri_ascii_grid(tmp_path):
    path = tmp_path / "depth.asc"
    path.write_text("ncols 3\nnrows 2\nxllcorner 1000\nyllcorner 2000\ncellsize 2\nNODATA_value -9999\n"
                    "-5 -6 -9999\n-7 -8 -9\n")
    scan = read_scan(path)
    assert len(scan.points) == 5
    top_left = scan.points[0]
    assert np.allclose(top_left, [1001, 2003, -5])  # centre of the top left cell


def test_geotiff(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    values = np.array([[-5, -6], [-7, np.nan]], dtype=np.float32)
    path = tmp_path / "depth.tif"
    tifffile.imwrite(str(path), values, extratags=[
        (33550, "d", 3, (0.5, 0.5, 0.0), False),
        (33922, "d", 6, (0, 0, 0, 500_000.0, 5_800_000.0, 0.0), False),
    ])
    scan = read_scan(path)
    assert len(scan.points) == 3
    assert np.allclose(scan.points[0], [500_000.25, 5_799_999.75, -5])


@pytest.mark.parametrize("suffix", [".obj", ".stl"])
def test_meshes_become_points_on_the_surface(tmp_path, suffix):
    mesh = o3d.geometry.TriangleMesh.create_box(4, 2, 1)
    mesh.compute_vertex_normals()
    path = tmp_path / f"block{suffix}"
    o3d.io.write_triangle_mesh(str(path), mesh)
    scan = read_scan(path, ImportOptions(mesh_points=5000))
    assert len(scan.points) == 5000
    assert scan.points.min() >= -1e-6 and scan.points[:, 0].max() <= 4 + 1e-6


def test_raw_sonar_files_get_a_clear_message(tmp_path):
    path = tmp_path / "line_001.xtf"
    path.write_bytes(b"\x00" * 100)
    with pytest.raises(ScanReadError, match="Export the cleaned survey"):
        read_scan(path)


def test_empty_and_missing_files(tmp_path):
    with pytest.raises(ScanReadError):
        read_scan(tmp_path / "nothing.xyz")
    (tmp_path / "empty.xyz").write_text("")
    with pytest.raises(ScanReadError):
        read_scan(tmp_path / "empty.xyz")


def test_options_round_trip_through_json():
    options = ImportOptions(unit="ft", depth_down=True, columns={"x": 1, "y": 2, "z": 3}, delimiter=";")
    assert ImportOptions.from_json(options.to_json()) == options
