import bpy
import os
import json
import numpy as np
from mathutils import Matrix, Vector
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

    def extract_camera_parameters(self, camera_obj, render_settings, coordinate_system, export_mode=None):
        """Extract camera parameters with optimizations"""
        cam_data = camera_obj.data

        # Pre-calculate common values
        focal_mm = cam_data.lens
        sensor_w = cam_data.sensor_width
        sensor_h = cam_data.sensor_height
        render_w = render_settings.resolution_x
        render_h = render_settings.resolution_y

        # Field of view calculation and focal lengths
        if export_mode == "LICHTFELD":
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

        # Get transform matrix
        transform_matrix = camera_obj.matrix_world.copy()

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

    def generate_frame_data(self, frame_idx, cam_params, simplified=False):
        """Generate frame data entry"""
        frame_entry = {
            "transform_matrix": cam_params["transform"],
            "file_path": f"images/{frame_idx:04d}.png",
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

        # Get initial camera parameters
        scene.frame_set(scene.frame_start)
        initial_params = self.extract_camera_parameters(camera, scene.render, scene.coordinate_system, scene.export_mode)

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
        elif scene.export_mode == "LICHTFELD":
            # LichtFeld Studio mode: include full camera data at top level
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
            scene.frame_set(frame_idx)

            # Extract camera parameters for this frame
            frame_params = self.extract_camera_parameters(camera, scene.render, scene.coordinate_system, scene.export_mode)

            # Generate frame data
            simplified_mode = scene.export_mode in ["POSTSHOT", "LICHTFELD"]
            frame_data = self.generate_frame_data(
                frame_idx, frame_params, simplified=simplified_mode
            )

            output_json["frames"].append(frame_data)

        # Write output file
        output_path = bpy.path.abspath(scene.json_output_path)
        output_dir = os.path.dirname(output_path)

        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(output_path, "w") as f:
            json.dump(output_json, f, indent=2)

        self.report({"INFO"}, f"Exported {frame_count} frames to {output_path}")
        return {"FINISHED"}