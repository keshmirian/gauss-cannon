import bpy
import os
import numpy as np
import gpu
from ..utils.ray_casting import cast_ray_through_pixel, gpu_accelerated_ray_cast
from ..utils.coordinate_systems import write_ply_header, write_ply_point


class EXPORT_OT_pointcloud_ply(bpy.types.Operator):
    """Generate colored point cloud in PLY format from selected objects"""

    bl_idname = "export.pointcloud_ply"
    bl_label = "Generate Point Cloud PLY from Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.selected_objects
            and any(obj.type == "MESH" for obj in context.selected_objects)
            and context.scene.camera
            and context.scene.frame_end >= context.scene.frame_start
        )

    def check_gpu_available(self):
        """Check if GPU acceleration is available."""
        try:
            # Check if we can create GPU buffers
            test_data = np.array([1.0, 2.0, 3.0], dtype=np.float32)
            buffer = gpu.types.Buffer("FLOAT", 3, test_data)
            del buffer
            return True
        except Exception:
            return False

    def extract_mesh_data(self, mesh_obj):
        """Extract mesh data into a serializable format for multiprocessing."""
        mesh = mesh_obj.data
        vertices = np.array([v.co for v in mesh.vertices])
        # Handle variable-sized faces by converting to triangles
        faces = []
        for poly in mesh.polygons:
            verts = poly.vertices
            # Triangulate polygons with more than 3 vertices
            for i in range(1, len(verts) - 1):
                faces.append([verts[0], verts[i], verts[i + 1]])
        faces = np.array(faces)
        transform = np.array(mesh_obj.matrix_world)

        return {"vertices": vertices, "faces": faces, "transform": transform}

    def render_frame_to_pixels(self, scene, resolution):
        """Render current frame and return pixel data"""
        # Store original settings
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_percentage = scene.render.resolution_percentage
        orig_filepath = scene.render.filepath

        # Temporarily hide helper meshes from viewport
        helper_meshes = []
        for item in scene.helper_meshes:
            try:
                if item.mesh_object:
                    helper_meshes.append((item.mesh_object, item.mesh_object.hide_viewport))
            except (AttributeError, ReferenceError):
                pass
        for obj, _ in helper_meshes:
            obj.hide_viewport = True

        # Set low resolution
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100

        # Render to temporary image
        temp_path = os.path.join(
            bpy.app.tempdir, f"pointcloud_temp_{scene.frame_current}.png"
        )
        scene.render.filepath = temp_path

        try:
            # Render frame
            bpy.ops.render.render(write_still=True)

            # Load rendered image
            img = bpy.data.images.load(temp_path)

            # Get pixel data as numpy array
            pixels = np.array(img.pixels[:])
            pixels = pixels.reshape((resolution, resolution, 4))

            # Clean up
            bpy.data.images.remove(img)
            if os.path.exists(temp_path):
                os.remove(temp_path)

            return pixels

        finally:
            # Restore settings
            scene.render.resolution_x = orig_res_x
            scene.render.resolution_y = orig_res_y
            scene.render.resolution_percentage = orig_percentage
            scene.render.filepath = orig_filepath

            # Restore helper mesh visibility
            for obj, orig_hide in helper_meshes:
                obj.hide_viewport = orig_hide

    def write_ply(self, filepath, points, colors, coordinate_system):
        """Write point cloud to PLY file"""
        num_points = len(points)

        with open(filepath, "wb") as f:
            # Write PLY header
            header = write_ply_header(num_points)
            f.write(header.encode("ascii"))

            # Write binary data
            for i in range(num_points):
                point_data = write_ply_point(points[i], colors[i], coordinate_system)
                f.write(point_data)

    def execute(self, context):
        scene = context.scene
        camera = scene.camera
        resolution = scene.pointcloud_resolution

        # Get selected mesh objects, excluding helper meshes
        helper_mesh_objects = set()
        for item in scene.helper_meshes:
            try:
                if item.mesh_object:
                    helper_mesh_objects.add(item.mesh_object)
            except (AttributeError, ReferenceError):
                pass
        selected_meshes = [
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj not in helper_mesh_objects
        ]

        if not selected_meshes:
            self.report(
                {"ERROR"}, "No mesh objects selected (helper meshes are excluded)"
            )
            return {"CANCELLED"}

        # Check if GPU acceleration is available and enabled
        use_gpu = scene.use_gpu_acceleration and self.check_gpu_available()

        # Collect all points and colors
        all_points = []
        all_colors = []

        # Process each frame
        total_frames = scene.frame_end - scene.frame_start + 1
        wm = context.window_manager
        wm.progress_begin(0, total_frames)

        if use_gpu:
            self.report({"INFO"}, "Using GPU-accelerated BVH ray casting")
        else:
            self.report({"INFO"}, "Using CPU ray casting (slower fallback)")

        # Store original persistent data setting and enable it for faster animation rendering
        orig_persistent_data = scene.render.use_persistent_data
        scene.render.use_persistent_data = True

        try:
            for i, frame_idx in enumerate(
                range(scene.frame_start, scene.frame_end + 1)
            ):
                # Update progress
                wm.progress_update(i)

                scene.frame_set(frame_idx)

                # Render frame at low resolution
                self.report({"INFO"}, f"Processing frame {frame_idx}/{scene.frame_end}")
                pixels = self.render_frame_to_pixels(scene, resolution)

                if use_gpu:
                    # Use GPU-accelerated BVH ray casting
                    frame_results = gpu_accelerated_ray_cast(
                        scene, camera, resolution, selected_meshes, pixels
                    )
                    for hit_point, color in frame_results:
                        all_points.append(hit_point)
                        all_colors.append(color)
                else:
                    # Use simple CPU ray casting (fallback)
                    for y in range(resolution):
                        for x in range(resolution):
                            color = pixels[resolution - 1 - y, x, :3]

                            hit_point = cast_ray_through_pixel(
                                scene,
                                camera,
                                x + 0.5,
                                y + 0.5,
                                resolution,
                                resolution,
                                selected_meshes,
                            )

                            if hit_point:
                                all_points.append(hit_point)
                                all_colors.append(color)

        finally:
            # Restore original persistent data setting
            scene.render.use_persistent_data = orig_persistent_data
            wm.progress_end()

        # Write PLY file
        output_path = bpy.path.abspath(scene.pointcloud_output_path)
        output_dir = os.path.dirname(output_path)

        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.write_ply(output_path, all_points, all_colors, scene.coordinate_system)

        coord_info = "Y-up" if scene.coordinate_system == "Y_UP" else "Z-up"
        self.report(
            {"INFO"},
            f"Generated point cloud with {len(all_points)} points from {total_frames} frames ({coord_info})",
        )
        return {"FINISHED"}