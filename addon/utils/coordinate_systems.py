from mathutils import Matrix
import numpy as np


def convert_coordinate_system(coordinate_system, transform_matrix=None, point=None):
    """
    Convert between Blender's Z-up and Y-up coordinate systems.

    Args:
        coordinate_system: "Y_UP" or "Z_UP"
        transform_matrix: 4x4 matrix to convert (for cameras)
        point: 3D point to convert (for point clouds)

    Returns:
        Converted matrix or point
    """
    if coordinate_system == "Y_UP":
        # Convert from Blender's Z-up to LichtFeld's Y-up coordinate system
        # Blender: X-right, Y-forward, Z-up
        # LichtFeld: X-right, Y-up, Z-forward

        if transform_matrix is not None:
            # For cameras: base conversion + 180-degree Z rotation in world space
            # Combined transformation: rotation_z_180 @ base_conversion
            # (equivalent to rotation_x_180 @ rotation_y_180 @ base_conversion;
            # the X-180 component aligns cameras with LichtFeld's updated
            # coordinate convention, which previously required only Y-180.)
            camera_conversion = Matrix([
                [-1,  0,  0, 0],
                [ 0,  0,  1, 0],
                [ 0,  1,  0, 0],
                [ 0,  0,  0, 1]
            ])
            return camera_conversion @ transform_matrix
        elif point is not None:
            # For points: basic coordinate conversion only (no rotation)
            # X stays X, Y' = Z, Z' = -Y
            return [point[0], point[2], -point[1]]

    # Z_UP - return unchanged
    if transform_matrix is not None:
        return transform_matrix
    elif point is not None:
        return [point[0], point[1], point[2]]


def write_ply_header(num_points):
    """Generate PLY file header for colored point cloud"""
    return f"""ply
format binary_little_endian 1.0
element vertex {num_points}
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
end_header
"""


def write_ply_bulk(filepath, points, colors, coordinate_system):
    """
    Write an entire colored point cloud to PLY in a single bulk operation.

    ``points`` and ``colors`` are numpy arrays of shape ``(N, 3)``. Coordinate
    conversion and color quantization are vectorized; the binary body is laid
    out into a structured array (12-byte position + 3-byte RGB per record,
    matching the PLY spec exactly) and written with one ``tofile`` call —
    significantly faster than per-point writes for large clouds.

    Args:
        filepath: Output .ply path
        points: (N, 3) numpy array of XYZ in Blender's Z-up world space
        colors: (N, 3) numpy array of RGB in 0..1 range
        coordinate_system: "Y_UP" or "Z_UP"
    """
    num_points = points.shape[0]
    header = write_ply_header(num_points).encode("ascii")

    if coordinate_system == "Y_UP":
        # Match convert_coordinate_system(point=...): [x, z, -y]
        out_points = np.empty_like(points, dtype=np.float32)
        out_points[:, 0] = points[:, 0]
        out_points[:, 1] = points[:, 2]
        out_points[:, 2] = -points[:, 1]
    else:
        out_points = points.astype(np.float32, copy=False)

    rgb = np.clip(colors * 255.0, 0.0, 255.0).astype(np.uint8)

    record_dtype = np.dtype([("pos", "<f4", 3), ("rgb", "u1", 3)])
    records = np.empty(num_points, dtype=record_dtype)
    records["pos"] = out_points
    records["rgb"] = rgb

    with open(filepath, "wb") as f:
        f.write(header)
        records.tofile(f)