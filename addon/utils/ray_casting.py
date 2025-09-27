import bpy
import math
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def is_camera_inside_mesh(context, camera_pos, view_direction, helper_objects):
    """
    Check if camera position is inside a mesh using the odd-even rule.

    Args:
        context: Blender context
        camera_pos: Vector position of camera
        view_direction: Vector direction camera is looking
        helper_objects: Set of helper mesh objects to exclude

    Returns:
        bool: True if camera is inside any mesh
    """
    scene = context.scene

    # Get all visible mesh objects in the scene, excluding helper meshes
    visible_meshes = [
        obj
        for obj in context.view_layer.objects
        if obj.type == "MESH"
        and obj.visible_get()
        and not obj.hide_render
        and obj not in helper_objects
    ]

    # Check each mesh to see if camera is inside
    for obj in visible_meshes:
        # Transform camera position to object space
        mat_inv = obj.matrix_world.inverted()
        camera_pos_local = mat_inv @ camera_pos

        # Cast a ray in any direction (we'll use +X) to count intersections
        ray_direction = Vector((1.0, 0.0, 0.0))

        # Count intersections using ray casting
        intersection_count = 0
        current_pos = camera_pos_local.copy()

        # Keep casting until we don't hit anything
        while True:
            result, location, normal, index = obj.ray_cast(
                current_pos, ray_direction
            )

            if not result:
                break

            intersection_count += 1
            # Move slightly past the hit point to continue ray casting
            current_pos = location + ray_direction * 0.0001

        # Odd number of intersections means we're inside
        if intersection_count % 2 == 1:
            return True

    return False


def cast_ray_through_pixel(scene, camera, pixel_x, pixel_y, res_x, res_y, selected_objects):
    """
    Cast ray through pixel and find intersection with selected objects.

    Args:
        scene: Blender scene
        camera: Camera object
        pixel_x, pixel_y: Pixel coordinates
        res_x, res_y: Resolution
        selected_objects: List of objects to intersect with

    Returns:
        Vector or None: Hit point in world space
    """
    cam_matrix = camera.matrix_world
    cam_data = camera.data

    # Calculate normalized device coordinates (-1 to 1)
    ndc_x = (2.0 * pixel_x / res_x) - 1.0
    ndc_y = 1.0 - (2.0 * pixel_y / res_y)

    # Get camera parameters
    aspect = res_x / res_y
    if cam_data.type == "PERSP":
        # Perspective camera
        fov = cam_data.angle
        tan_half_fov = math.tan(fov / 2.0)

        # Calculate ray direction in camera space
        ray_dir_cam = Vector(
            (ndc_x * tan_half_fov * aspect, ndc_y * tan_half_fov, -1.0)
        ).normalized()
    else:
        # Orthographic camera
        ortho_scale = cam_data.ortho_scale
        ray_dir_cam = Vector((0, 0, -1))
        offset_x = ndc_x * ortho_scale * aspect / 2.0
        offset_y = ndc_y * ortho_scale / 2.0

    # Transform ray to world space
    ray_origin = cam_matrix.translation.copy()
    ray_dir_world = cam_matrix.to_3x3() @ ray_dir_cam
    ray_dir_world.normalize()

    if cam_data.type == "ORTHO":
        # Offset origin for orthographic camera
        right = cam_matrix.to_3x3() @ Vector((1, 0, 0))
        up = cam_matrix.to_3x3() @ Vector((0, 1, 0))
        ray_origin += right * offset_x + up * offset_y

    # Find closest intersection
    closest_hit = None
    closest_dist = float("inf")

    for obj in selected_objects:
        if obj.type != "MESH":
            continue

        # Transform ray to object space
        obj_inv = obj.matrix_world.inverted()
        ray_origin_obj = obj_inv @ ray_origin
        ray_dir_obj = obj_inv.to_3x3() @ ray_dir_world
        ray_dir_obj.normalize()

        # Cast ray
        result, location, normal, index = obj.ray_cast(ray_origin_obj, ray_dir_obj)

        if result:
            # Transform hit point back to world space
            hit_world = obj.matrix_world @ location
            dist = (hit_world - ray_origin).length

            if dist < closest_dist:
                closest_dist = dist
                closest_hit = hit_world

    # Only return hit if it's beyond near clipping plane
    if closest_hit and closest_dist >= cam_data.clip_start:
        return closest_hit
    return None


def gpu_accelerated_ray_cast(scene, camera, resolution, selected_meshes, pixels):
    """
    GPU-accelerated ray casting using Blender's BVH trees.

    Args:
        scene: Blender scene
        camera: Camera object
        resolution: Square resolution for casting
        selected_meshes: List of mesh objects to intersect
        pixels: Rendered pixel data

    Returns:
        list: List of (hit_point, color) tuples
    """
    cam_matrix = camera.matrix_world
    cam_data = camera.data

    # Build BVH trees for all selected meshes
    bvh_trees = []
    for obj in selected_meshes:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()

        # Create BVH tree
        bvh = BVHTree.FromPolygons(
            [v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons]
        )
        bvh_trees.append((bvh, obj.matrix_world))
        obj_eval.to_mesh_clear()

    results = []

    # Process rays in batches for better performance
    for y in range(resolution):
        for x in range(resolution):
            # Calculate ray
            ndc_x = (2.0 * (x + 0.5) / resolution) - 1.0
            ndc_y = 1.0 - (2.0 * (y + 0.5) / resolution)

            aspect = 1.0  # Square aspect ratio
            if cam_data.type == "PERSP":
                fov = cam_data.angle
                tan_half_fov = math.tan(fov / 2.0)
                ray_dir_cam = Vector(
                    (ndc_x * tan_half_fov * aspect, ndc_y * tan_half_fov, -1.0)
                ).normalized()
            else:
                ortho_scale = cam_data.ortho_scale
                ray_dir_cam = Vector((0, 0, -1))
                offset_x = ndc_x * ortho_scale * aspect / 2.0
                offset_y = ndc_y * ortho_scale / 2.0

            # Transform to world space
            ray_origin = cam_matrix.translation.copy()
            ray_dir_world = cam_matrix.to_3x3() @ ray_dir_cam
            ray_dir_world.normalize()

            if cam_data.type == "ORTHO":
                right = cam_matrix.to_3x3() @ Vector((1, 0, 0))
                up = cam_matrix.to_3x3() @ Vector((0, 1, 0))
                ray_origin += right * offset_x + up * offset_y

            # Find closest hit using BVH
            closest_hit = None
            closest_dist = float("inf")

            for bvh, obj_matrix in bvh_trees:
                # Transform ray to object space
                obj_inv = obj_matrix.inverted()
                ray_origin_obj = obj_inv @ ray_origin
                ray_dir_obj = obj_inv.to_3x3() @ ray_dir_world
                ray_dir_obj.normalize()

                # Cast ray using BVH
                location, normal, index, dist = bvh.ray_cast(
                    ray_origin_obj, ray_dir_obj
                )

                if location:
                    # Transform hit back to world space
                    hit_world = obj_matrix @ location
                    world_dist = (hit_world - ray_origin).length

                    if world_dist < closest_dist:
                        closest_dist = world_dist
                        closest_hit = hit_world

            if closest_hit:
                # Check if hit is beyond near clipping plane
                if closest_dist >= cam_data.clip_start:
                    color = pixels[resolution - 1 - y, x, :3]
                    results.append((closest_hit, color))

    return results