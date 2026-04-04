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
            # For cameras: base conversion + 180-degree Y rotation in world space
            # Combined transformation: rotation_y_180 @ base_conversion
            camera_conversion = Matrix([
                [-1,  0,  0, 0],
                [ 0,  0, -1, 0],
                [ 0, -1,  0, 0],
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


def write_ply_point(point, color, coordinate_system):
    """
    Write a single point and color to PLY format in binary.

    Args:
        point: 3D point coordinates
        color: RGB color values (0-1 range)
        coordinate_system: "Y_UP" or "Z_UP"

    Returns:
        bytes: Binary data for this point
    """
    converted_point = convert_coordinate_system(coordinate_system, point=point)

    # Position (3 floats)
    position_data = np.array(converted_point, dtype=np.float32).tobytes()

    # Color (3 unsigned chars)
    color_data = np.array(color * 255, dtype=np.uint8).tobytes()

    return position_data + color_data