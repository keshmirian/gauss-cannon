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


def _build_near_frustum_bvh(cam_data, cam_pos, look_dir, right, up, aspect):
    """
    Build a world-space BVH for the polyhedron between the camera position and
    its near plane. PERSP -> 5-vert pyramid, ORTHO -> 8-vert box.
    """
    near_clip = cam_data.clip_start

    if cam_data.type == "PERSP":
        tan_half = math.tan(cam_data.angle / 2.0)
        half_w = near_clip * tan_half * aspect
        half_h = near_clip * tan_half
        near_center = cam_pos + look_dir * near_clip

        verts = [
            cam_pos.copy(),                                         # 0: apex
            near_center - right * half_w + up * half_h,             # 1: TL
            near_center + right * half_w + up * half_h,             # 2: TR
            near_center + right * half_w - up * half_h,             # 3: BR
            near_center - right * half_w - up * half_h,             # 4: BL
        ]
        tris = [
            (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),  # sides
            (1, 2, 3), (1, 3, 4),                        # near quad
        ]
    else:
        half_w = cam_data.ortho_scale * aspect / 2.0
        half_h = cam_data.ortho_scale / 2.0
        forward = look_dir * near_clip

        verts = [
            cam_pos - right * half_w - up * half_h,                 # 0: BL near
            cam_pos + right * half_w - up * half_h,                 # 1: BR near
            cam_pos + right * half_w + up * half_h,                 # 2: TR near
            cam_pos - right * half_w + up * half_h,                 # 3: TL near
            cam_pos - right * half_w - up * half_h + forward,       # 4: BL far
            cam_pos + right * half_w - up * half_h + forward,       # 5: BR far
            cam_pos + right * half_w + up * half_h + forward,       # 6: TR far
            cam_pos - right * half_w + up * half_h + forward,       # 7: TL far
        ]
        tris = [
            (0, 1, 2), (0, 2, 3),    # near
            (4, 6, 5), (4, 7, 6),    # far
            (0, 3, 7), (0, 7, 4),    # left
            (1, 5, 6), (1, 6, 2),    # right
            (0, 4, 5), (0, 5, 1),    # bottom
            (2, 6, 7), (2, 7, 3),    # top
        ]

    return BVHTree.FromPolygons(verts, tris)


def build_visible_mesh_bvh_cache(context, helper_objects):
    """
    Build a per-export list of world-space BVHTrees for every visible
    non-helper mesh. The BVH is built from depsgraph-evaluated geometry so
    modifiers are respected, and vertices are baked into world space so the
    returned trees are directly comparable to a world-space frustum BVH and
    accept world-space queries (e.g. find_nearest).

    Args:
        context: Blender context
        helper_objects: Set of helper mesh objects to exclude

    Returns:
        list[BVHTree]
    """
    depsgraph = context.evaluated_depsgraph_get()
    cache = []

    for obj in context.view_layer.objects:
        if (
            obj.type != "MESH"
            or not obj.visible_get()
            or obj.hide_render
            or obj in helper_objects
        ):
            continue

        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        if mesh is None:
            continue

        try:
            world_matrix = obj.matrix_world
            world_verts = [world_matrix @ v.co for v in mesh.vertices]
            polys = [list(p.vertices) for p in mesh.polygons]
            if world_verts and polys:
                cache.append(BVHTree.FromPolygons(world_verts, polys))
        finally:
            obj_eval.to_mesh_clear()

    return cache


def is_geometry_within_near_clip(
    cam_data, cam_pos, look_dir, right, up, mesh_bvh_cache, aspect
):
    """
    Check if any visible geometry would be clipped by the camera's near plane.

    Two complementary checks run against the pre-built world-space BVH cache:

    1. ``BVHTree.find_nearest(cam_pos, near_clip)``: returns the closest
       surface point on each mesh that's within ``clip_start`` of the camera,
       or None if no such point exists. The ``distance`` argument lets the
       BVH skip whole branches whose bounds fall outside the near radius —
       most meshes get rejected without touching a leaf. We then verify the
       hit is forward of the camera and inside the view frustum. This catches
       meshes that sit fully inside the near volume (no triangle crosses a
       frustum face, so the overlap test below would miss them).

    2. ``BVHTree.overlap`` between a polyhedron representing the
       camera-to-near-plane volume and each mesh's BVH. Exact: any
       triangle-triangle intersection means at least one point of geometry
       is inside the near volume.

    Args:
        cam_data: Camera data (provides type, angle/ortho_scale, clip_start)
        cam_pos: Vector camera position in world space
        look_dir: Vector camera forward direction (unit length)
        right: Vector camera right axis (unit length)
        up: Vector camera up axis (unit length)
        mesh_bvh_cache: List of world-space BVHTrees from
            ``build_visible_mesh_bvh_cache``
        aspect: render aspect ratio (resolution_x / resolution_y)

    Returns:
        bool: True if any geometry intersects within the near clipping distance
    """
    if not mesh_bvh_cache:
        return False

    near_clip = cam_data.clip_start

    if cam_data.type == "PERSP":
        tan_half = math.tan(cam_data.angle / 2.0)
        tan_half_x = tan_half * aspect
        tan_half_y = tan_half
        ortho_half_w = 0.0
        ortho_half_h = 0.0
    else:
        tan_half_x = 0.0
        tan_half_y = 0.0
        ortho_half_w = cam_data.ortho_scale * aspect / 2.0
        ortho_half_h = cam_data.ortho_scale / 2.0

    def in_frustum(rel, forward):
        x_offset = abs(rel.dot(right))
        y_offset = abs(rel.dot(up))
        if cam_data.type == "PERSP":
            return x_offset <= forward * tan_half_x and y_offset <= forward * tan_half_y
        return x_offset <= ortho_half_w and y_offset <= ortho_half_h

    # Check 1: nearest surface point within near_clip on each mesh BVH.
    # find_nearest's distance argument prunes BVH branches whose bounds are
    # farther than near_clip, so most meshes terminate without leaf work.
    for mesh_bvh in mesh_bvh_cache:
        location, normal, index, dist = mesh_bvh.find_nearest(cam_pos, near_clip)
        if location is None:
            continue
        rel = location - cam_pos
        forward = rel.dot(look_dir)
        if forward <= 0.0:
            continue
        if in_frustum(rel, forward):
            return True

    # Check 2: BVH overlap between the near-volume polyhedron and each mesh.
    frustum_bvh = _build_near_frustum_bvh(cam_data, cam_pos, look_dir, right, up, aspect)
    for mesh_bvh in mesh_bvh_cache:
        if frustum_bvh.overlap(mesh_bvh):
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