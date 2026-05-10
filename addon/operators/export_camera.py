import bpy
import os
import json
import numpy as np
from mathutils import Matrix, Vector, Euler
from ..utils.coordinate_systems import convert_coordinate_system


class EXPORT_OT_camera_json(bpy.types.Operator):
    """Export camera parameters to JSON"""

    bl_idname = "export.camera_json"
    bl_label = "Export Camera JSON"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.scene.camera
            and context.scene.frame_end >= context.scene.frame_start
            and context.scene.output_folder.strip()
        )

    def compute_scene_bounds(self):
        """Compute scene bounding box more efficiently"""
        # Collect all visible mesh vertices
        visible_meshes = [
            obj
            for obj in bpy.context.view_layer.objects
            if obj.type == "MESH" and not obj.hide_render and obj.visible_get()
        ]

        if not visible_meshes:
            return 1.0  # Default scale if no visible meshes

        # Use numpy for efficient min/max calculation
        all_verts = []
        for obj in visible_meshes:
            world_mat = obj.matrix_world
            # Get bounding box corners in world space
            bbox_world = [world_mat @ Vector(corner) for corner in obj.bound_box]
            all_verts.extend([(v.x, v.y, v.z) for v in bbox_world])

        if not all_verts:
            return 1.0

        verts_array = np.array(all_verts)
        bbox_min = verts_array.min(axis=0)
        bbox_max = verts_array.max(axis=0)
        bbox_size = bbox_max - bbox_min

        return float(np.max(bbox_size))

    def iter_action_fcurves(self, animation_data):
        """
        Yield F-curves from animation_data, working across Blender versions.

        Pre-4.4: F-curves live directly on Action.fcurves.
        4.4+ (Slotted Actions): F-curves live in Channelbags inside Strips
        inside Layers, keyed by the animation_data's action_slot.
        """
        if not animation_data or not animation_data.action:
            return
        action = animation_data.action

        legacy = getattr(action, "fcurves", None)
        if legacy is not None:
            for fc in legacy:
                yield fc
            return

        slot = getattr(animation_data, "action_slot", None)
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                cb = None
                if slot is not None and hasattr(strip, "channelbag"):
                    try:
                        cb = strip.channelbag(slot)
                    except Exception:
                        cb = None
                if cb is None:
                    # No slot match — fall back to any channelbags on the strip
                    for cb_alt in getattr(strip, "channelbags", []):
                        for fc in cb_alt.fcurves:
                            yield fc
                    continue
                for fc in cb.fcurves:
                    yield fc

    def build_fast_path_evaluator(self, camera):
        """
        Build a frame -> world-matrix evaluator that bypasses scene.frame_set.

        Reads keyframe values directly from the camera's location/rotation_euler
        F-curves so we don't trigger a full depsgraph evaluation for every frame
        (which is slow when the scene has rigged characters, simulations, etc.).

        Returns a callable on success, or None when the camera transform can't
        be reconstructed in isolation — caller should then fall back to
        scene.frame_set + camera.matrix_world.
        """
        # Anything that makes matrix_world depend on more than the camera's own
        # local transform forces the slow path.
        if camera.parent is not None:
            return None
        if len(camera.constraints) > 0:
            return None
        if camera.rotation_mode != "XYZ":
            return None
        cam_anim = camera.data.animation_data
        if cam_anim and any(True for _ in self.iter_action_fcurves(cam_anim)):
            # Animated intrinsics (lens, sensor, clip): we'd need depsgraph eval
            return None
        if not camera.animation_data or not camera.animation_data.action:
            return None

        needed = {
            ("location", 0): None,
            ("location", 1): None,
            ("location", 2): None,
            ("rotation_euler", 0): None,
            ("rotation_euler", 1): None,
            ("rotation_euler", 2): None,
        }
        for fc in self.iter_action_fcurves(camera.animation_data):
            key = (fc.data_path, fc.array_index)
            if key in needed:
                needed[key] = fc
        if any(fc is None for fc in needed.values()):
            return None

        def to_dict(fc):
            return {int(round(kp.co.x)): kp.co.y for kp in fc.keyframe_points}

        loc_maps = [to_dict(needed[("location", i)]) for i in range(3)]
        rot_maps = [to_dict(needed[("rotation_euler", i)]) for i in range(3)]

        scale_mat = Matrix.Diagonal(camera.scale).to_4x4()

        def evaluate(frame_idx):
            try:
                loc = Vector(
                    (loc_maps[0][frame_idx], loc_maps[1][frame_idx], loc_maps[2][frame_idx])
                )
                rot = Euler(
                    (rot_maps[0][frame_idx], rot_maps[1][frame_idx], rot_maps[2][frame_idx]),
                    "XYZ",
                )
            except KeyError:
                # Frame missing from keyframes for any channel; let caller fall back.
                return None
            return Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ scale_mat

        return evaluate

    def extract_camera_parameters(self, camera_obj, render_settings, coordinate_system, export_mode=None, world_matrix=None):
        """Extract camera parameters with optimizations"""
        cam_data = camera_obj.data

        # Pre-calculate common values
        focal_mm = cam_data.lens
        sensor_w = cam_data.sensor_width
        sensor_h = cam_data.sensor_height
        render_w = render_settings.resolution_x
        render_h = render_settings.resolution_y

        # Field of view calculation and focal lengths
        if export_mode in ("LICHTFELD", "BRUSH"):
            # For LichtFeld Studio, use Blender's actual FOV directly
            # Blender's cam_data.angle is the FOV in radians
            if cam_data.sensor_fit == 'HORIZONTAL' or (cam_data.sensor_fit == 'AUTO' and render_w >= render_h):
                # Horizontal FOV is the reference
                fov_x = cam_data.angle
                # Calculate vertical FOV from horizontal
                aspect_ratio = render_h / render_w
                fov_y = 2.0 * np.arctan(np.tan(fov_x / 2.0) * aspect_ratio)
            else:
                # Vertical FOV is the reference
                fov_y = cam_data.angle
                # Calculate horizontal FOV from vertical
                aspect_ratio = render_w / render_h
                fov_x = 2.0 * np.arctan(np.tan(fov_y / 2.0) * aspect_ratio)

            # Calculate focal lengths to match LichtFeld's expectation
            # LichtFeld uses: focal = 0.5 * resolution / tan(0.5 * fov_rad)
            fx = 0.5 * render_w / np.tan(0.5 * fov_x)
            fy = 0.5 * render_h / np.tan(0.5 * fov_y)
        else:
            # Standard calculation from sensor dimensions
            # Pixel-space focal lengths
            fx = (focal_mm * render_w) / sensor_w
            fy = (focal_mm * render_h) / sensor_h

            # Field of view
            fov_x = 2.0 * np.arctan(sensor_w / (2.0 * focal_mm))
            fov_y = 2.0 * np.arctan(sensor_h / (2.0 * focal_mm))

        # Get transform matrix (fast-path override avoids depsgraph eval)
        transform_matrix = (
            world_matrix if world_matrix is not None else camera_obj.matrix_world
        ).copy()

        # Apply coordinate system conversion if needed
        transform_matrix = convert_coordinate_system(coordinate_system, transform_matrix=transform_matrix)

        # Convert to nested list
        transform = [list(row) for row in transform_matrix]

        return {
            "focal_x": fx,
            "focal_y": fy,
            "fov_x": fov_x,
            "fov_y": fov_y,
            "transform": transform,
        }

    def get_render_extension(self):
        """Get file extension based on Blender's render output format"""
        format_map = {
            'PNG': '.png',
            'JPEG': '.jpg',
            'OPEN_EXR': '.exr',
            'OPEN_EXR_MULTILAYER': '.exr',
            'TIFF': '.tif',
            'BMP': '.bmp',
            'HDR': '.hdr',
            'WEBP': '.webp',
        }
        file_format = bpy.context.scene.render.image_settings.file_format
        return format_map.get(file_format, '.png')

    def generate_frame_data(self, frame_idx, cam_params, simplified=False):
        """Generate frame data entry"""
        ext = self.get_render_extension()
        frame_entry = {
            "transform_matrix": cam_params["transform"],
            "file_path": f"images/{frame_idx:04d}{ext}",
        }

        if not simplified:
            frame_entry.update(
                {
                    "w": bpy.context.scene.render.resolution_x,
                    "h": bpy.context.scene.render.resolution_y,
                    "fl_x": cam_params["focal_x"],
                    "fl_y": cam_params["focal_y"],
                    "camera_angle_x": cam_params["fov_x"],
                    "camera_angle_y": cam_params["fov_y"],
                }
            )

        return frame_entry

    def execute(self, context):
        scene = context.scene
        camera = scene.camera

        if not camera:
            self.report({"ERROR"}, "No camera found in scene")
            return {"CANCELLED"}

        # Calculate scene bounds
        scene_scale = self.compute_scene_bounds()

        # Brush uses LichtFeld's JSON layout but Z-up coordinates
        coordinate_system = "Z_UP" if scene.export_mode == "BRUSH" else scene.coordinate_system

        # Try to build a fast-path evaluator that reads camera transforms directly
        # from F-curve keyframe data, bypassing per-frame depsgraph evaluation.
        fast_eval = self.build_fast_path_evaluator(camera)
        slow_path_frames = 0

        # Get initial camera parameters
        initial_matrix = fast_eval(scene.frame_start) if fast_eval is not None else None
        if initial_matrix is None:
            scene.frame_set(scene.frame_start)
        initial_params = self.extract_camera_parameters(
            camera,
            scene.render,
            coordinate_system,
            scene.export_mode,
            world_matrix=initial_matrix,
        )

        # Build output structure based on export mode
        if scene.export_mode == "POSTSHOT":
            # Postshot mode: include camera data at top level
            output_json = {
                "aabb_scale": scene_scale,
                "w": scene.render.resolution_x,
                "h": scene.render.resolution_y,
                "camera_angle_x": initial_params["fov_x"],
                "camera_angle_y": initial_params["fov_y"],
                "cx": scene.render.resolution_x / 2.0,
                "cy": scene.render.resolution_y / 2.0,
                "frames": [],
            }
        elif scene.export_mode in ("LICHTFELD", "BRUSH"):
            # LichtFeld Studio / Brush mode: include full camera data at top level
            output_json = {
                "aabb_scale": scene_scale,
                "w": scene.render.resolution_x,
                "h": scene.render.resolution_y,
                "camera_angle_x": initial_params["fov_x"],
                "camera_angle_y": initial_params["fov_y"],
                "fl_x": initial_params["focal_x"],
                "fl_y": initial_params["focal_y"],
                "cx": scene.render.resolution_x / 2.0,
                "cy": scene.render.resolution_y / 2.0,
                "frames": [],
            }
        else:  # STANDARD mode
            # Standard mode: only include aabb_scale and frames
            output_json = {
                "aabb_scale": scene_scale,
                "frames": [],
            }

        # Process all frames
        frame_count = scene.frame_end - scene.frame_start + 1
        for frame_idx in range(scene.frame_start, scene.frame_end + 1):
            world_matrix = fast_eval(frame_idx) if fast_eval is not None else None
            if world_matrix is None:
                scene.frame_set(frame_idx)
                slow_path_frames += 1

            # Extract camera parameters for this frame
            frame_params = self.extract_camera_parameters(
                camera,
                scene.render,
                coordinate_system,
                scene.export_mode,
                world_matrix=world_matrix,
            )

            # Generate frame data
            simplified_mode = scene.export_mode in ["POSTSHOT", "LICHTFELD", "BRUSH"]
            frame_data = self.generate_frame_data(
                frame_idx, frame_params, simplified=simplified_mode
            )

            output_json["frames"].append(frame_data)

        # Write output file
        output_dir = bpy.path.abspath(scene.output_folder)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        output_path = os.path.join(output_dir, "transforms.json")

        with open(output_path, "w") as f:
            json.dump(output_json, f, indent=2)

        if fast_eval is not None and slow_path_frames == 0:
            path_msg = " (fast path: no depsgraph eval)"
        elif fast_eval is not None:
            path_msg = f" ({slow_path_frames}/{frame_count} frames used slow path)"
        else:
            path_msg = " (slow path: camera has parent/constraints/animated intrinsics)"

        self.report(
            {"INFO"},
            f"Exported {frame_count} frames to {output_path}{path_msg}",
        )
        return {"FINISHED"}